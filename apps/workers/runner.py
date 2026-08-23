"""Worker process runner: python -m reflex.workers.runner --role <role>

Roles (TechSpec §6):
- diagnosis : Redis Streams consumer (16 shards by episode hash) — rules→LLM tail
- decision  : plans DIAGNOSED episodes (reflex→Brain+Shield, b1→naive), dispatches due actions
- outcome   : applies simulator events, watch windows, expiry + approval sweeps

All loops poll the DB under the agent DB role; the decision/outcome loops hold an
additional eval-role session ONLY for the Proof simulator bridge (hidden truth).
Agent decisions never touch replay.* — the role boundary is enforced by grants.
"""

from __future__ import annotations

import argparse
import signal
import threading
import time
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import text

from reflex.core.clock import SimClock, effective_mode
from reflex.core.enums import Arm, CanonicalCode, DxMethod, Mode

log = structlog.get_logger("reflex.workers")

TICK_SECS = 0.2  # kill-switch drain budget ≤1s ⇒ tick fast
DX_SHARDS = 16


def _redis():  # type: ignore[no-untyped-def]
    from reflex.api.db import get_redis

    return get_redis()


def _agent_session():  # type: ignore[no-untyped-def]
    from reflex.api.db import agent_sessionmaker

    return agent_sessionmaker()()


def _eval_session():  # type: ignore[no-untyped-def]
    from reflex.api.db import eval_sessionmaker

    return eval_sessionmaker()()


def _now_sim(redis_client) -> datetime:  # type: ignore[no-untyped-def]
    return SimClock(redis_client).now_sim()


def _mode(redis_client) -> Mode:  # type: ignore[no-untyped-def]
    s = _agent_session()
    try:
        return effective_mode(redis_client, _db_mode(s))
    finally:
        s.close()


def _db_mode(session) -> str:  # type: ignore[no-untyped-def]
    return str(
        session.execute(
            text("SELECT mode::text FROM runtime.merchants ORDER BY created_at LIMIT 1")
        ).scalar()
        or "advisory"
    )


def _bump(r, key: str) -> None:  # type: ignore[no-untyped-def]
    try:
        r.incr(f"reflex:ctr:{key}")
    except Exception:
        pass


def _rp_client():  # type: ignore[no-untyped-def]
    import os

    from reflex.connectors.razorpay import RazorpayTestModeClient

    return RazorpayTestModeClient(
        key_id=os.environ.get("RAZORPAY_KEY_ID", ""),
        key_secret=os.environ.get("RAZORPAY_KEY_SECRET", ""),
    )


def _sim_bridge(agent_session, eval_session):  # type: ignore[no-untyped-def]
    from reflex.workers.simulator import SimulatorBridge

    row = agent_session.execute(
        text("SELECT id::text, seed FROM replay.replay_batches ORDER BY created_at DESC LIMIT 1")
    ).first()
    if row is None:
        return None
    return SimulatorBridge(eval_session, seed=int(row[1]), batch_id=row[0])


# ---- diagnosis role -----------------------------------------------------------


def run_diagnosis(stop: threading.Event) -> None:
    from reflex.api.db import get_redis
    from reflex.ledger.chain import LedgerWriter
    from reflex.workers.diagnosis import diagnose_episode
    from reflex.workers.llm_client import LlmClient

    r = get_redis()
    llm = LlmClient(redis_client=r)
    groups_ready = False
    while not stop.is_set():
        if not groups_ready:
            for shard in range(DX_SHARDS):
                try:
                    r.xgroup_create(f"reflex:dx:{shard}", "dx", id="0", mkstream=True)
                except Exception:
                    pass  # BUSYGROUP — fine
            groups_ready = True
        got_any = False
        for shard in range(DX_SHARDS):
            try:
                msgs = r.xread({f"reflex:dx:{shard}": ">"}, count=10, block=200)
            except Exception:
                continue
            for stream_name, entries in msgs or []:
                for msg_id, fields in entries:
                    got_any = True
                    try:
                        _process_diagnosis(r, llm, fields.get("episode_id"))
                    finally:
                        try:
                            r.xack(stream_name, "dx", msg_id)
                            r.xdel(stream_name, msg_id)
                        except Exception:
                            pass
        if not got_any:
            stop.wait(TICK_SECS)


def _process_diagnosis(r, llm, episode_id: str | None) -> None:  # type: ignore[no-untyped-def]
    if not episode_id:
        return
    from reflex.ledger.chain import LedgerWriter
    from reflex.workers.diagnosis import diagnose_episode

    s = _agent_session()
    try:
        row = s.execute(
            text(
                """
                SELECT e.id::text AS eid, pe.code_raw, pe.rail::text AS rail,
                       pe.amount_paise, pe.occurred_at, pe.raw_payload
                FROM runtime.episodes e JOIN runtime.payment_events pe ON pe.id = e.payment_event_id
                WHERE e.id = CAST(:e AS uuid) AND e.status = 'waiting_diagnosis'
                FOR UPDATE OF e
                """
            ),
            {"e": episode_id},
        ).mappings().first()
        if row is None:
            return
        now = _now_sim(r)
        mode = effective_mode(r, _db_mode(s))
        dx = diagnose_episode(
            s,
            llm,
            r,
            episode_id=row["eid"],
            code_raw=str(row["code_raw"]),
            rail=str(row["rail"]),
            amount_paise=int(row["amount_paise"]),
            occurred_at=row["occurred_at"],
            raw_payload=dict(row["raw_payload"] or {}),
            degraded=mode is Mode.DEGRADED,
        )
        s.execute(
            text(
                "INSERT INTO runtime.diagnoses (episode_id, canonical_code, confidence, method, rationale) "
                "VALUES (:e, CAST(:c AS runtime.canonical_code), :cf, CAST(:m AS runtime.dx_method), :r)"
            ),
            {
                "e": row["eid"],
                "c": dx.canonical_code.value,
                "cf": dx.confidence,
                "m": dx.method.value,
                "r": dx.rationale[:240],
            },
        )
        LedgerWriter(s).append(
            episode_id=row["eid"],
            event={
                "type": "DIAGNOSIS_STORED",
                "canonical_code": dx.canonical_code.value,
                "confidence": dx.confidence,
                "method": dx.method.value,
            },
            at=now,
        )
        s.execute(
            text("UPDATE runtime.episodes SET status = 'diagnosed' WHERE id = CAST(:e AS uuid)"),
            {"e": row["eid"]},
        )
        _bump(r, "dx_rule" if dx.method is DxMethod.RULE else "dx_llm")
        s.commit()
    except Exception as exc:
        s.rollback()
        log.error("diagnosis_failed", error=str(exc)[:300], episode_id=episode_id)
    finally:
        s.close()


# ---- decision + dispatch role ---------------------------------------------------


def run_decision(stop: threading.Event) -> None:
    from reflex.workers.llm_client import LlmClient

    r = _redis()
    llm = LlmClient(redis_client=r)
    rp = _rp_client()
    while not stop.is_set():
        mode = _mode(r)
        if mode is Mode.HALTED:
            time.sleep(0.05)
            continue
        planned = _plan_due(r, llm, mode)
        dispatched = _dispatch_due(r, llm, rp, mode)
        if not planned and not dispatched:
            time.sleep(0.25)


def _plan_due(r, llm, mode: Mode) -> int:  # type: ignore[no-untyped-def]
    from reflex.workers.baselines import plan_b1
    from reflex.workers.context import load_context
    from reflex.workers.planner import plan_episode

    n = 0
    s = _agent_session()
    try:
        rows = s.execute(
            text(
                """
                SELECT e.id::text AS eid, e.arm::text AS arm
                FROM runtime.episodes e
                WHERE e.status = 'diagnosed'
                ORDER BY e.opened_at LIMIT 20
                """
            )
        ).mappings().all()
        if not rows:
            return 0
        now = _now_sim(r)
        for row in rows:
            ctx = load_context(s, row["eid"])
            if ctx is None:
                continue
            if row["arm"] == Arm.B0.value:
                # B0 never acts; park in scheduled-less limbo → expire at 72h
                continue
            if row["arm"] == Arm.B1.value:
                plan_b1(s, episode_id=row["eid"], amount_paise=ctx.amount_paise, now_sim=now)
                s.execute(
                    text("UPDATE runtime.episodes SET status='scheduled' WHERE id=CAST(:e AS uuid) AND status='diagnosed'"),
                    {"e": row["eid"]},
                )
                n += 1
                continue
            plan = plan_episode(
                s, ctx, diagnosis_code=_latest_dx(s, row["eid"]), now_sim=now, mode=mode
            )
            n += 1
            if plan.kind == "SCHEDULED":
                s.execute(
                    text("UPDATE runtime.episodes SET status='scheduled' WHERE id=CAST(:e AS uuid) AND status='diagnosed'"),
                    {"e": row["eid"]},
                )
                _bump(r, "shield_pass")
            elif plan.kind == "APPROVAL":
                s.execute(
                    text("UPDATE runtime.episodes SET status='waiting_approval' WHERE id=CAST(:e AS uuid) AND status='diagnosed'"),
                    {"e": row["eid"]},
                )
                _bump(r, "shield_approval")
            elif plan.kind == "BLOCKED":
                s.execute(
                    text("UPDATE runtime.episodes SET status='stopped_cap' WHERE id=CAST(:e AS uuid) AND status='diagnosed'"),
                    {"e": row["eid"]},
                )
                _bump(r, "shield_block")
            elif plan.kind == "STOPPED_LOW_EV":
                s.execute(
                    text("UPDATE runtime.episodes SET status='stopped_low_ev' WHERE id=CAST(:e AS uuid) AND status='diagnosed'"),
                    {"e": row["eid"]},
                )
        s.commit()
        return n
    except Exception as exc:
        s.rollback()
        log.error("planning_failed", error=str(exc)[:300])
        return 0
    finally:
        s.close()


def _latest_dx(session, episode_id: str) -> CanonicalCode:  # type: ignore[no-untyped-def]
    val = session.execute(
        text(
            "SELECT canonical_code::text FROM runtime.diagnoses WHERE episode_id = CAST(:e AS uuid) "
            "ORDER BY created_at DESC LIMIT 1"
        ),
        {"e": episode_id},
    ).scalar()
    return CanonicalCode(val or "UNKNOWN_AMBIGUOUS")


def _dispatch_due(r, llm, rp, mode: Mode) -> int:  # type: ignore[no-untyped-def]
    from reflex.workers.dispatcher import dispatch_action

    n = 0
    s = _agent_session()
    evs = None
    try:
        rows = s.execute(
            text(
                """
                SELECT a.id::text AS aid FROM runtime.actions a
                JOIN runtime.episodes e ON e.id = a.episode_id
                WHERE a.status = 'scheduled' AND a.scheduled_for <= :now
                  AND e.status NOT IN ('recovered','expired','stopped_cap','stopped_low_ev',
                                       'stopped_customer','stopped_approval_declined','escalated','halted')
                ORDER BY a.scheduled_for LIMIT 25
                """
            ),
            {"now": _now_sim(r)},
        ).scalars().all()
        if not rows:
            return 0
        evs = _eval_session()
        bridge = _sim_bridge(s, evs)
        for aid in rows:
            dr = dispatch_action(
                agent_session=s,
                sim_bridge=bridge,
                llm=llm,
                redis_client=r,
                rp_client=rp,
                action_id=aid,
                now_sim=_now_sim(r),
                mode=mode,
            )
            if dr.status == "dispatched":
                n += 1
                _bump(r, "shield_pass")
                _bump(r, "dispatched")
        s.commit()
        return n
    except Exception as exc:
        s.rollback()
        log.error("dispatch_loop_failed", error=str(exc)[:300])
        return 0
    finally:
        s.close()
        if evs is not None:
            evs.close()


# ---- outcome role ---------------------------------------------------------------


def run_outcome(stop: threading.Event) -> None:
    r = _redis()
    while not stop.is_set():
        try:
            mode = _mode(r)
            if mode is Mode.HALTED:
                time.sleep(0.1)
                continue
            _apply_sim_events(r)
            _expire_windows_and_approvals(r)
        except Exception as exc:
            log.error("outcome_loop_failed", error=str(exc)[:300])
        time.sleep(0.3)


def _apply_sim_events(r) -> None:  # type: ignore[no-untyped-def]
    """Apply due hidden-truth events through the real outcome path (Proof side)."""
    from reflex.workers.outcomes import apply_recovery, stop_customer

    s = _agent_session()
    evs = None
    try:
        batch = s.execute(
            text("SELECT id::text, seed, created_at FROM replay.replay_batches ORDER BY created_at DESC LIMIT 1")
        ).first()
        if batch is None:
            return
        clock_state = SimClock(r).state()
        if clock_state is None:
            return
        anchor_sim = datetime.fromtimestamp(clock_state["anchor_sim"], tz=timezone.utc)
        anchor_real = datetime.fromtimestamp(clock_state["anchor_real"], tz=timezone.utc)
        elapsed_real = (datetime.now(timezone.utc) - anchor_real).total_seconds()
        sim_now = anchor_sim + timedelta(seconds=elapsed_real * clock_state["speed"])
        opened = batch[2] if batch[2].tzinfo else batch[2].replace(tzinfo=timezone.utc)
        elapsed_sim = (sim_now - opened).total_seconds()
        if elapsed_sim < 0:
            return

        evs = _eval_session()
        rows = evs.execute(
            text(
                """
                SELECT se.id::text AS sid, se.episode_id::text AS eid, se.kind,
                       se.payload, se.t_offset_secs
                FROM replay.sim_events se
                WHERE se.batch_id = CAST(:b AS uuid)
                  AND se.t_offset_secs <= :el AND se.kind IN ('pay','reply')
                ORDER BY se.t_offset_secs LIMIT 50
                """
            ),
            {"b": batch[0], "el": int(elapsed_sim)},
        ).mappings().all()
        for row in rows:
            payload = dict(row["payload"] or {})
            action_id = payload.get("action_id")
            if row["kind"] == "pay":
                latency: int | None = None
                if action_id:
                    dispatched = s.execute(
                        text("SELECT dispatched_at FROM runtime.actions WHERE id = CAST(:a AS uuid)"),
                        {"a": action_id},
                    ).scalar()
                    if dispatched is not None:
                        d = dispatched if dispatched.tzinfo else dispatched.replace(tzinfo=timezone.utc)
                        latency = max(1, int((sim_now - d).total_seconds()))
                if apply_recovery(
                    s,
                    episode_id=row["eid"],
                    observed_at=sim_now,
                    action_id=action_id,
                    latency_secs=latency,
                    source_note=str(payload.get("via", "")) + " [SIMULATED]",
                ):
                    _bump(r, "recovered")
            elif row["kind"] == "reply":
                label = str(payload.get("label", "AMBIGUOUS"))
                if label in ("COMPLAINT", "OPTOUT"):
                    cust = s.execute(
                        text("SELECT customer_id::text FROM runtime.episodes WHERE id = CAST(:e AS uuid)"),
                        {"e": row["eid"]},
                    ).scalar()
                    if cust:
                        stop_customer(
                            s,
                            episode_id=row["eid"],
                            customer_id=cust,
                            reason_reason=label.lower(),
                            suppression_source="[SIMULATED] reply classifier",
                            at=sim_now,
                        )
            evs.execute(
                text("DELETE FROM replay.sim_events WHERE id = CAST(:i AS uuid)"), {"i": row["sid"]}
            )
        if rows:
            s.commit()
            evs.commit()
    finally:
        s.close()
        if evs is not None:
            evs.close()


def _expire_windows_and_approvals(r) -> None:  # type: ignore[no-untyped-def]
    from reflex.workers.outcomes import apply_watch_window_expiry, expire_due

    s = _agent_session()
    try:
        now = _now_sim(r)
        rows = s.execute(
            text(
                """
                SELECT a.id::text AS aid, a.episode_id::text AS eid
                FROM runtime.actions a JOIN runtime.episodes e ON e.id = a.episode_id
                WHERE a.status = 'observed' AND e.status = 'observing'
                  AND a.dispatched_at IS NOT NULL
                  AND a.dispatched_at + interval '6 hours' <= :now
                LIMIT 30
                """
            ),
            {"now": now},
        ).mappings().all()
        for row in rows:
            res = apply_watch_window_expiry(
                s, episode_id=row["eid"], action_id=row["aid"], observed_at=now
            )
            if res == "REPLAN":
                # re-plan with the existing diagnosis (horizon-1 observe loop)
                s.execute(
                    text("UPDATE runtime.episodes SET status='diagnosed' WHERE id=CAST(:e AS uuid) AND status='observing'"),
                    {"e": row["eid"]},
                )
        expire_due(s, now)
        s.commit()
    finally:
        s.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--role", required=True, choices=["diagnosis", "decision", "outcome"])
    args = parser.parse_args()

    stop = threading.Event()

    def _sig(*_a: object) -> None:
        stop.set()

    try:
        signal.signal(signal.SIGINT, _sig)
        signal.signal(signal.SIGTERM, _sig)
    except Exception:
        pass

    log.info("worker_started", role=args.role)
    {"diagnosis": run_diagnosis, "decision": run_decision, "outcome": run_outcome}[args.role](stop)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
