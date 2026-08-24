"""Control plane: modes, kill switch, failure injections (FR-013/014/020)."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from reflex.api.security import require_role
from reflex.core.enums import Mode, Role
from reflex.core.schemas import ModeChangeRequest
from reflex.ledger.chain import LedgerWriter
from sqlalchemy import text

router = APIRouter()


@router.post("/control/mode")
def set_mode(
    body: ModeChangeRequest,
    request: Request,
    user: dict[str, Any] = Depends(require_role(Role.OPERATOR)),
) -> dict:
    request.app.state.rate.check("control_mode", user["user_id"])
    redis = request.app.state.redis
    from reflex.api.db import agent_sessionmaker
    from reflex.ledger.chain import LedgerWriter

    new_mode = Mode(body.mode)
    s = agent_sessionmaker()()
    try:
        row = s.execute(text("SELECT mode::text FROM runtime.merchants ORDER BY created_at LIMIT 1")).first()
        if row is None:
            raise HTTPException(status_code=404, detail="no merchant configured")
        old = Mode(row[0])

        # kill switch semantics (AppFlow §11): halted flag in Redis + DB mode
        if new_mode is Mode.HALTED:
            redis.set("reflex:halted", "1")
        else:
            redis.delete("reflex:halted")
        s.execute(
            text("UPDATE runtime.merchants SET mode = CAST(:m AS runtime.mode)"),
            {"m": new_mode.value},
        )
        s.execute(
            text(
                "INSERT INTO runtime.mode_changes (merchant_id, from_mode, to_mode, actor, reason) "
                "SELECT id, CAST(:f AS runtime.mode), CAST(:t AS runtime.mode), :a, :r "
                "FROM runtime.merchants ORDER BY created_at LIMIT 1"
            ),
            {"f": old.value, "t": new_mode.value, "a": user["user_id"], "r": body.reason or ""},
        )
        LedgerWriter(s).append(
            episode_id=_any_episode(s) or _zero_uuid(),
            event={
                "type": "MODE_CHANGED",
                "from": old.value,
                "to": new_mode.value,
                "actor": user["user_id"],
                "reason": body.reason or "",
            },
        )
        s.commit()
    except HTTPException:
        s.rollback()
        raise
    except Exception as exc:
        s.rollback()
        raise HTTPException(status_code=400, detail=str(exc)[:200]) from exc
    finally:
        s.close()

    # drain: cancel scheduled actions immediately when halting (≤1s budget)
    if new_mode is Mode.HALTED:
        _drain_on_halt()

    from reflex.api.main import publish_event
    publish_event(redis, {"type": "mode.changed", "mode": new_mode.value})
    return {"ok": True, "mode": new_mode.value}


def _drain_on_halt() -> int:
    """Cancel scheduled/waiting actions → CANCELLED_HALT; episodes → HALTED."""
    from reflex.api.db import agent_sessionmaker

    s = agent_sessionmaker()()
    try:
        n = s.execute(
            text(
                "UPDATE runtime.actions SET status = 'cancelled_halt' "
                "WHERE status IN ('scheduled','proposed','shield_pass') RETURNING 1"
            )
        ).fetchall()
        s.execute(
            text(
                "UPDATE runtime.episodes SET status = 'halted' WHERE status NOT IN "
                "('recovered','expired','stopped_cap','stopped_low_ev','stopped_customer',"
                "'stopped_approval_declined','escalated','halted')"
            )
        )
        LedgerWriter(s).append(
            episode_id=_any_episode(s) or _zero_uuid(),
            event={"type": "KILL_SWITCH_DRAIN", "cancelled_actions": len(n)},
        )
        s.commit()
        return len(n)
    finally:
        s.close()


@router.post("/control/inject/{scenario}")
def inject(scenario: str, request: Request, user: dict[str, Any] = Depends(require_role(Role.OPERATOR))) -> dict:
    """Demo integrity: injections are labeled events through the REAL system path —
    never silent fakery (TechSpec §10 / Rules §16.4)."""
    request.app.state.rate.check("control_inject", user["user_id"])
    redis = request.app.state.redis

    if scenario == "llm_outage":
        redis.set("reflex:inject:llm_outage", json.dumps({"by": user["user_id"], "at": "now"}))
        _publish(request, {"type": "banner.updated", "banner": "DEGRADED", "reason": "LLM outage injected"})
        return {"ok": True, "scenario": scenario}
    if scenario == "llm_restore":
        redis.delete("reflex:inject:llm_outage")
        _publish(request, {"type": "banner.updated", "banner": None})
        return {"ok": True, "scenario": scenario}
    if scenario == "webhook_storm":
        from reflex.eval.replay_driver import run_webhook_storm

        stats = run_webhook_storm(redis_client=redis)
        _publish(request, {"type": "storm.stats", **stats})
        return {"ok": True, "scenario": scenario, **stats}
    if scenario == "complaint":
        from reflex.eval.replay_driver import inject_complaint

        result = inject_complaint(redis_client=redis)
        _publish(request, {"type": "complaint.injected", **result})
        return {"ok": True, "scenario": scenario, **result}

    raise HTTPException(status_code=404, detail="unknown scenario")


def _publish(request: Request, event: dict) -> None:
    from reflex.api.main import publish_event

    publish_event(request.app.state.redis, event)


def _any_episode(session) -> str | None:  # type: ignore[no-untyped-def]
    return session.execute(text("SELECT id::text FROM runtime.episodes ORDER BY opened_at DESC LIMIT 1")).scalar()


def _zero_uuid() -> str:
    return "00000000-0000-0000-0000-000000000000"
