"""Integration: per-episode trail verification on an interleaved chain.

The replay driver interleaves episodes' ledger rows in seq order; the slice
verifier must check each row against its OWN global predecessor or every
replay-era trail falsely reports a chain break (the 409 bug). This test
builds a real interleaved chain in Postgres, asserts both slices verify,
then tampers a row and asserts detection."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import text


@pytest.mark.integration
def test_interleaved_episode_slices_verify_and_tamper(clean_db):  # type: ignore[no-untyped-def]
    from reflex.api.db import eval_sessionmaker
    from reflex.api.ingest_service import ingest_event
    from reflex.core.enums import EventSource
    from reflex.eval.seed import ensure_reference_data
    from reflex.ledger.chain import LedgerWriter, verify_episode_slice, verify_rows

    s = eval_sessionmaker()()
    try:
        ensure_reference_data(s)
        base = datetime.now(UTC).replace(microsecond=0)

        def norm(i: int) -> dict:
            return {
                "provider_event_id": f"slice_{i}",
                "event": "payment.failed",
                "rail": "upi",
                "code_raw": "NSF - insufficient funds in account",
                "amount_paise": 19900,
                "occurred_at": base,
                "raw_payload": {"simulated": True},
                "customer_ref": f"idx:{i}",
            }

        for i in range(2):
            ingest_event(s, source=EventSource.REPLAY, normalized=norm(i), now_sim=base)
        s.commit()

        ep = dict(s.execute(
            text(
                "SELECT pe.provider_event_id, e.id::text FROM runtime.episodes e "
                "JOIN runtime.payment_events pe ON pe.id = e.payment_event_id "
                "WHERE pe.provider_event_id IN ('slice_0','slice_1')"
            )
        ).all())
        assert set(ep) == {"slice_0", "slice_1"}

        # Interleave the two episodes: A B A B A (on top of the two ingest rows)
        w = LedgerWriter(s)
        order = [
            ("slice_0", {"type": "ACTION_DISPATCHED", "n": 1}),
            ("slice_1", {"type": "ACTION_DISPATCHED", "n": 2}),
            ("slice_0", {"type": "SHIELD_BLOCKED", "n": 3}),
            ("slice_1", {"type": "SHIELD_BLOCKED", "n": 4}),
            ("slice_0", {"type": "ACTION_DISPATCHED", "n": 5}),
        ]
        for pid, ev in order:
            w.append(episode_id=ep[pid], event=ev)
        s.commit()

        # A's slice verifies against its own global predecessors
        valid, first_bad, checked, rows = verify_episode_slice(s, ep["slice_0"])
        assert valid and first_bad is None and checked == 4 and len(rows) == 4

        # Regression guard: the OLD genesis-seeded subset walk fails here —
        # this is precisely the 409 bug the per-row linkage fix removes.
        old_ok, _, _ = verify_rows(rows)
        assert not old_ok

        # B's slice verifies too
        valid_b, _, checked_b, _ = verify_episode_slice(s, ep["slice_1"])
        assert valid_b and checked_b == 3

        # Tamper an event inside A's slice → detected at that row
        seq_to_tamper = int(rows[1]["seq"])
        s.execute(
            text("UPDATE runtime.action_ledger SET event = event || '{\"tampered\": true}' WHERE seq = :s"),
            {"s": seq_to_tamper},
        )
        s.commit()
        valid_t, bad_t, _, _ = verify_episode_slice(s, ep["slice_0"])
        assert not valid_t and bad_t == seq_to_tamper

        # Unknown episode → empty, valid trail
        import uuid

        valid_u, _, checked_u, rows_u = verify_episode_slice(s, str(uuid.uuid4()))
        assert valid_u and checked_u == 0 and rows_u == []
    finally:
        s.close()
