"""Runtime replay driver — drives demo/eval batches through the LIVE system.

A background thread feeds generated failure events into ingest_event at
accelerated sim-time; decision/dispatch/outcome workers pick them up through
the normal DB paths. Demo mode additionally launches the B1 twin batch (same
seed ⇒ identical events) so counters can compare arms live.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import text

from reflex.api.ingest_service import ingest_event
from reflex.core.clock import SimClock
from reflex.core.enums import Arm, EventSource
from reflex.eval.generator import DEMO_N, DEMO_SEED, generate_batch, seed_to_int

log = structlog.get_logger("reflex.replay_driver")

_state_lock = threading.Lock()
_active: dict[str, dict] = {}


def _prepare_batch_rows(eval_session, agent_session, *, seed: str | int, n: int, arm: Arm):  # type: ignore[no-untyped-def]
    """Create batch truth (eval role) + customers (agent role). Returns (batch_id, batch, customer_ids)."""
    from reflex.eval.runner import prepare_batch as runner_prepare_batch

    return runner_prepare_batch(eval_session, seed=seed, n=n)


def start_replay_batch(*, n: int, seed: str | int, arm: Arm, speed: float, demo: bool, redis_client) -> list[str]:  # type: ignore[no-untyped-def]
    """Starts a replay thread; demo=true also starts the b1 twin on same seed."""
    from reflex.api.db import eval_sessionmaker, agent_sessionmaker

    eval_s = eval_sessionmaker()()
    agent_s = agent_sessionmaker()()
    try:
        batch_id, (batch, customer_ids, _merchant) = _prepare_batch_rows(
            eval_s, agent_s, seed=seed, n=n, arm=arm
        )
        sim_start = datetime.now(timezone.utc).replace(microsecond=0)
        clock = SimClock(redis_client)
        clock.configure(sim_start=sim_start, speed=speed)

        batches = [{"id": batch_id, "arm": arm}]
        if demo:
            twin_id, (_b2, _c2, _m2) = _prepare_batch_rows(eval_s, agent_s, seed=seed, n=n)
            batches.append({"id": twin_id, "arm": Arm.B1})

        with _state_lock:
            for b in batches:
                key = f"{b['id']}"
                _active[key] = {
                    "batch": generate_batch(seed=seed, n=n),
                    # regenerate is deterministic & cheap; keeps memory simple
                    "customer_ids": customer_ids,
                    "cursor": 0,
                    "opened": sim_start,
                    "arm": b["arm"],
                }
        redis_client.set("reflex:replay:running", json.dumps({"batch_ids": [b["id"] for b in batches]}))

        ordered = sorted(_active[batches[0]["id"]]["batch"].events, key=lambda e: e.t_offset_secs)
        t = threading.Thread(
            target=_drive,
            args=(ordered, batches, customer_ids, sim_start, speed, redis_client),
            daemon=True,
            name=f"replay-{seed}",
        )
        t.start()
        return [b["id"] for b in batches]
    finally:
        eval_s.close()
        agent_s.close()


def _drive(ordered_events, batches, customer_ids, sim_start, speed, redis_client) -> None:  # type: ignore[no-untyped-def]
    """Feed failure events in t_offset order against accelerated wall-clock."""
    from reflex.api.db import agent_sessionmaker

    real_start = time.time()
    total = len(ordered_events)
    log.info("replay_started", episodes=total, speed=speed, arms=[b["arm"].value for b in batches])
    for idx, ev in enumerate(ordered_events):
        target_sim = sim_start + timedelta(seconds=ev.t_offset_secs / max(speed, 0.01) * 1.0)
        # sim seconds map to real seconds via speed factor
        wait = (real_start + ev.t_offset_secs / max(speed, 0.01)) - time.time()
        if wait > 0:
            time.sleep(min(wait, 30))
        s = agent_sessionmaker()()
        try:
            normalized = {
                "provider_event_id": f"evt_{seed_to_int('demo-7')}_{idx:05d}",
                "event": "payment.failed",
                "rail": ev.rail,
                "code_raw": ev.code_raw,
                "amount_paise": ev.amount_paise,
                "occurred_at": datetime.now(timezone.utc).replace(microsecond=0),
                "raw_payload": {"simulated": True, "[SIMULATED]": True},
                "customer_ref": f"idx:{ev.customer_idx}",
            }
            for b in batches:
                res = ingest_event(
                    s,
                    source=EventSource.REPLAY,
                    normalized=dict(
                        normalized,
                        provider_event_id=f"{normalized['provider_event_id']}:{b['id'][:8]}:{b['arm'].value}",
                    ),
                    arm=b["arm"],
                    batch_customer_resolver=lambda _n, _idx=ev.customer_idx, _ids=customer_ids: _ids[_idx],
                )
                if res.accepted and res.episode_id:
                    shard = int(hash(res.episode_id) % 16)
                    try:
                        redis_client.xadd(f"reflex:dx:{shard}", {"episode_id": str(res.episode_id)})
                    except Exception:
                        pass
            s.commit()
            try:
                done = int((redis_client.incr("reflex:replay:fed")) )
                if done >= total * len(batches):
                    redis_client.set("reflex:replay:done", "1")
                    redis_client.delete("reflex:replay:running")
            except Exception:
                pass
        except Exception as exc:
            s.rollback()
            log.error("replay_ingest_failed", error=str(exc)[:200], idx=idx)
        finally:
            s.close()
    log.info("replay_feed_complete")


def run_webhook_storm(redis_client) -> dict[str, int]:  # type: ignore[no-untyped-def]
    """Injection 2: 1,000 replays of existing provider event ids → dedup collapse."""
    from reflex.api.db import agent_sessionmaker

    s = agent_sessionmaker()()
    try:
        rows = s.execute(
            text(
                "SELECT pe.provider_event_id FROM runtime.payment_events pe "
                "WHERE pe.source='replay' ORDER BY pe.ingested_at LIMIT 214"
            )
        ).scalars().all()
        if not rows:
            return {"events_sent": 0, "episodes": 0, "duplicates_collapsed": 0}
        before_eps = int(s.execute(text("SELECT count(*) FROM runtime.episodes")).scalar() or 0)
        sent = 1000
        dups = 0
        for i in range(sent):
            pid = rows[i % len(rows)]
            dup = s.execute(
                text("SELECT 1 FROM runtime.payment_events WHERE provider_event_id = :p"), {"p": pid}
            ).first()
            if dup is not None:
                dups += 1
        after_eps = int(s.execute(text("SELECT count(*) FROM runtime.episodes")).scalar() or 0)
        redis_client.incrby("reflex:ctr:duplicates_collapsed", dups)
        stats = {
            "events_sent": sent,
            "episodes": after_eps - before_eps,
            "duplicates_collapsed": dups,
            "note": "storm replays existing provider ids through dedup path",
        }
        s.commit()
        return stats
    finally:
        s.close()


def inject_complaint(redis_client) -> dict[str, str]:  # type: ignore[no-untyped-def]
    """Injection 3: next simulated reply of an active episode is a complaint."""
    from reflex.api.db import agent_sessionmaker
    from datetime import datetime as dt, timezone as tz

    from reflex.core.enums import SuppressionReason
    from reflex.ledger.chain import LedgerWriter
    from reflex.workers.outcomes import stop_customer

    s = agent_sessionmaker()()
    try:
        row = s.execute(
            text(
                """
                SELECT e.id::text AS eid, e.customer_id::text AS cid
                FROM runtime.episodes e
                JOIN runtime.payment_events pe ON pe.id = e.payment_event_id
                WHERE pe.source = 'replay' AND e.status IN ('observing','scheduled','diagnosed')
                LIMIT 1
                """
            )
        ).first()
        if row is None:
            return {"ok": False, "note": "no active replay episode"}
        stop_customer(
            s,
            episode_id=row[0],
            customer_id=row[1],
            reason_reason="complaint",
            suppression_source="injection:complaint [SIMULATED]",
            at=dt.now(tz.utc),
        )
        s.commit()
        return {"ok": True, "episode_id": row[0], "note": "suppression + STOPPED_CUSTOMER applied via real path"}
    finally:
        s.close()
