"""Integration: golden path through the REAL pipeline against Postgres (FR-015)."""

from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from reflex.core.enums import Arm
from reflex.eval.runner import prepare_batch
from reflex.eval.pipeline import run_arm


@pytest.mark.integration
def test_golden_path_terminal_states_and_attribution(clean_db):  # type: ignore[no-untyped-def]
    from reflex.api.db import eval_sessionmaker
    from reflex.eval.seed import ensure_reference_data

    s = eval_sessionmaker()()
    try:
        ensure_reference_data(s)
        batch_id, bt = prepare_batch(s, seed=7, n=12)
        batch, cust_ids, mid = bt
        result = run_arm(
            s, batch_id=batch_id, batch=batch, merchant_id=mid,
            customer_ids=cust_ids, arm=Arm.REFLEX,
            opened_at=datetime.now(timezone.utc).replace(microsecond=0),
        )
        # every episode reaches a terminal state (FR-015 acceptance)
        rows = s.execute(text("""
            SELECT e.status::text, count(*) FROM runtime.episodes e GROUP BY 1
        """)).all()
        terminal = {"recovered", "expired", "stopped_cap", "stopped_low_ev",
                    "stopped_customer", "stopped_approval_declined", "escalated", "halted"}
        for status, cnt in rows:
            assert status in terminal, f"non-terminal episodes remain: {status} x{cnt}"

        # single recovery per episode + attribution unambiguous
        dupes = s.execute(text("""
            SELECT episode_id FROM runtime.outcomes WHERE outcome='recovered'
            GROUP BY episode_id HAVING count(*) > 1
        """)).all()
        assert not dupes

        # ledger chain verifies across the whole run (PRD §20 #6)
        from reflex.ledger.chain import verify_db
        ok, bad, checked = verify_db(s)
        assert ok and bad is None and checked > 10

        # every dispatched action is ledgered (G4)
        n_actions = s.execute(text("SELECT count(*) FROM runtime.actions WHERE dispatched_at IS NOT NULL")).scalar()
        n_dispatch_events = s.execute(text("""
            SELECT count(*) FROM runtime.action_ledger WHERE event->>'type' = 'ACTION_DISPATCHED'
        """)).scalar()
        assert n_dispatch_events >= n_actions > 0

        assert result.episodes_total == 12
    finally:
        s.close()


@pytest.mark.integration
def test_webhook_storm_dedup(clean_db):  # type: ignore[no-untyped-def]
    """F2/PRD FR-002: 1000 replays of existing events collapse to zero dup episodes."""
    from datetime import timedelta

    from reflex.api.db import eval_sessionmaker
    from reflex.api.ingest_service import ingest_event
    from reflex.core.enums import EventSource
    from reflex.eval.seed import ensure_reference_data

    s = eval_sessionmaker()()
    try:
        ensure_reference_data(s)
        base = datetime.now(timezone.utc).replace(microsecond=0)

        def norm(i: int) -> dict:
            return {
                "provider_event_id": f"storm_{i}",
                "event": "payment.failed",
                "rail": "upi",
                "code_raw": "Sim:insufficient balance — try later",
                "amount_paise": 29900,
                "occurred_at": base,
                "raw_payload": {"simulated": True},
                "customer_ref": f"idx:{i % 40}",
            }

        created = 0
        for i in range(214):
            res = ingest_event(s, source=EventSource.REPLAY, normalized=norm(i), now_sim=base)
            created += int(res.accepted)
        before_eps = s.execute(text("SELECT count(*) FROM runtime.episodes")).scalar()

        dups = 0
        for i in range(1000):
            idx = i % 214
            res = ingest_event(s, source=EventSource.REPLAY, normalized=norm(idx), now_sim=base + timedelta(seconds=idx))
            if res.duplicate:
                dups += 1
        after_eps = s.execute(text("SELECT count(*) FROM runtime.episodes")).scalar()

        assert created == 214 and dups == 1000 and after_eps == before_eps == 214
    finally:
        s.close()
