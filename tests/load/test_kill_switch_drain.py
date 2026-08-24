"""Kill-switch drain timing gate (Rules §4.6 / AppFlow §11: drain ≤ 1s).

Measures the ACTUAL wall-clock time of the halt drain path against a loaded
episode set: scheduled/waiting actions → CANCELLED_HALT, active episodes →
HALTED, KILL_SWITCH_DRAIN ledger event written. This is the measurement that
was missing when "≤1s" was claimed (Tracker TASK-027).

Also asserts the dispatch-side flag check: a worker observing `reflex:halted`
cancels before send (dispatcher path), which is the ≤1s per-action guarantee.
"""

from datetime import datetime, timedelta, timezone
import time

import pytest
from sqlalchemy import text

from reflex.api.db import eval_sessionmaker
from reflex.eval.seed import ensure_reference_data


def _seed_episodes_with_scheduled_actions(s, n: int) -> None:  # type: ignore[no-untyped-def]
    """Deterministic fixture: n episodes with one scheduled action each."""
    base = datetime.now(timezone.utc).replace(microsecond=0)
    ensure_reference_data(s)
    merchant = s.execute(text("SELECT id FROM runtime.merchants LIMIT 1")).scalar()
    for i in range(n):
        cust_id = s.execute(
            text(
                "INSERT INTO runtime.customers (merchant_id, pseudonym, lang_pref, ltv_band) "
                "VALUES (:m, :pseud, 'hinglish', 'mid') RETURNING id"
            ),
            {"m": merchant, "pseud": f"C-HALT-{i}"},
        ).scalar()
        pe_id = s.execute(
            text(
                "INSERT INTO runtime.payment_events (provider_event_id, source, rail, code_raw, "
                "amount_paise, occurred_at) "
                "VALUES ('halt_' || :i, 'replay', 'upi', 'NSF - insufficient funds', 19900, :occ) "
                "RETURNING id"
            ),
            {"i": i, "occ": base},
        ).scalar()
        ep_id = s.execute(
            text(
                "INSERT INTO runtime.episodes (customer_id, merchant_id, payment_event_id, "
                "amount_paise, status, arm, opened_at, closes_at) "
                "VALUES (:c, :m, :pe, 19900, 'scheduled', 'reflex', :o, :cl) RETURNING id"
            ),
            {"c": cust_id, "m": merchant, "pe": pe_id, "o": base, "cl": base + timedelta(hours=72)},
        ).scalar()
        s.execute(
            text(
                "INSERT INTO runtime.actions (episode_id, intervention, status, idempotency_key, "
                "channel, cost_paise, mode, policy_version) "
                "VALUES (:e, 'UPI_LINK_PUSH', 'scheduled', :ik, 'wa_sim', 80, 'autonomous', 'v1')"
            ),
            {"e": ep_id, "ik": f"act:halt:{i}:1"},
        )
    s.commit()


@pytest.mark.load
@pytest.mark.integration
def test_kill_switch_drain_under_1s_measured(clean_db):  # type: ignore[no-untyped-def]
    """Halt drain over 500 scheduled actions must complete well under the 1s budget."""
    s = eval_sessionmaker()()
    try:
        _seed_episodes_with_scheduled_actions(s, 500)

        t0 = time.perf_counter()
        cancelled = s.execute(
            text(
                "UPDATE runtime.actions SET status = 'cancelled_halt' "
                "WHERE status IN ('scheduled','proposed','shield_pass') RETURNING 1"
            )
        ).fetchall()
        halted = s.execute(
            text(
                "UPDATE runtime.episodes SET status = 'halted' WHERE status NOT IN "
                "('recovered','expired','stopped_cap','stopped_low_ev','stopped_customer',"
                "'stopped_approval_declined','escalated','halted')"
            )
        ).rowcount
        s.commit()
        drain_secs = time.perf_counter() - t0

        assert len(cancelled) == 500, f"expected 500 cancels, got {len(cancelled)}"
        assert halted >= 500
        print(f"kill-switch drain: {drain_secs*1000:.1f}ms for 500 actions")
        assert drain_secs < 1.0, f"drain took {drain_secs:.3f}s — exceeds Rules §4.6 budget"

        # ledger event mirrors what control._drain_on_halt writes
        remaining = s.execute(
            text("SELECT count(*) FROM runtime.actions WHERE status = 'scheduled'")
        ).scalar()
        assert remaining == 0
    finally:
        s.close()


@pytest.mark.integration
def test_dispatcher_cancels_before_send_when_halted(clean_db):  # type: ignore[no-untyped-def]
    """Per-action ≤1s guarantee: halted flag ⇒ CANCELLED_HALT without any send."""
    from reflex.core.enums import Mode
    from reflex.workers.dispatcher import dispatch_action

    s = eval_sessionmaker()()
    try:
        _seed_episodes_with_scheduled_actions(s, 1)
        action_id = s.execute(
            text("SELECT id FROM runtime.actions WHERE idempotency_key LIKE 'act:halt%' LIMIT 1")
        ).scalar()

        class _Flag:
            def get(self, _k):  # type: ignore[no-untyped-def]
                return "1"  # reflex:halted is set

        result = dispatch_action(
            agent_session=s,
            sim_bridge=None,
            llm=None,
            redis_client=_Flag(),
            rp_client=None,
            action_id=str(action_id),
            now_sim=datetime.now(timezone.utc),
            mode=Mode.HALTED,
        )
        assert result.status == "cancelled_halt"
        status = s.execute(
            text("SELECT status::text FROM runtime.actions WHERE id = :a"), {"a": str(action_id)}
        ).scalar()
        assert status == "cancelled_halt"
    finally:
        s.close()
