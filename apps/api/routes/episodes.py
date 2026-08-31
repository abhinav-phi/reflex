"""Episode read APIs (viewer+)."""

from __future__ import annotations

from datetime import UTC
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from reflex.api.params import require_uuid
from reflex.api.security import require_role
from reflex.core.enums import Role
from sqlalchemy import text

router = APIRouter()


def _rate(request: Request, bucket: str, user: dict) -> None:
    limiter = request.app.state.rate
    limiter.check(bucket, user["user_id"])


@router.get("/episodes")
def list_episodes(
    request: Request,
    status: str | None = Query(default=None),
    code: str | None = Query(default=None),
    arm: str | None = Query(default=None),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    user: dict[str, Any] = Depends(require_role(Role.VIEWER)),
) -> dict:
    _rate(request, "episodes_list", user)
    from reflex.api.db import agent_sessionmaker

    s = agent_sessionmaker()()
    try:
        rows = s.execute(
            text(
                """
                SELECT e.id, c.pseudonym, e.amount_paise, e.status::text AS status,
                       e.arm::text AS arm, pe.rail::text AS rail, e.actions_used,
                       e.opened_at, e.closes_at,
                       d.canonical_code::text AS dx_code, d.confidence::float8 AS dx_conf,
                       d.method::text AS dx_method, d.rationale AS dx_rationale,
                       (SELECT ev_paise FROM runtime.candidate_interventions ci
                         WHERE ci.episode_id = e.id ORDER BY ranked_at DESC, ev_paise DESC LIMIT 1) AS top_ev
                FROM runtime.episodes e
                JOIN runtime.customers c ON c.id = e.customer_id
                JOIN runtime.payment_events pe ON pe.id = e.payment_event_id
                LEFT JOIN LATERAL (
                    SELECT * FROM runtime.diagnoses dx WHERE dx.episode_id = e.id
                    ORDER BY dx.created_at DESC LIMIT 1
                ) d ON true
                WHERE (CAST(:status AS text) IS NULL OR e.status::text = :status)
                  AND (CAST(:arm AS text) IS NULL OR e.arm::text = :arm)
                  AND (CAST(:code AS text) IS NULL OR d.canonical_code::text = :code)
                ORDER BY e.opened_at DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            {"status": status, "arm": arm, "code": code, "limit": limit, "offset": offset},
        ).mappings().all()
        total = s.execute(text("SELECT count(*) FROM runtime.episodes")).scalar()
        return {
            "total": int(total or 0),
            "items": [
                {
                    "id": str(r["id"]),
                    "customer_pseudonym": r["pseudonym"],
                    "amount_paise": int(r["amount_paise"]),
                    "status": r["status"],
                    "arm": r["arm"],
                    "rail": r["rail"],
                    "actions_used": int(r["actions_used"]),
                    "opened_at": r["opened_at"].isoformat(),
                    "closes_at": r["closes_at"].isoformat(),
                    "top_ev_paise": int(r["top_ev"]) if r["top_ev"] is not None else None,
                    "diagnosis": (
                        {
                            "canonical_code": r["dx_code"],
                            "confidence": float(r["dx_conf"] or 0),
                            "method": r["dx_method"],
                            "rationale": r["dx_rationale"] or "",
                            "created_at": r["opened_at"].isoformat(),
                        }
                        if r["dx_code"]
                        else None
                    ),
                }
                for r in rows
            ],
        }
    finally:
        s.close()


@router.get("/episodes/{episode_id}")
def get_episode(
    request: Request,
    episode_id: str,
    user: dict[str, Any] = Depends(require_role(Role.VIEWER)),
) -> dict:
    _rate(request, "episode_get", user)
    episode_id = require_uuid(episode_id, "episode_id")
    from reflex.api.db import agent_sessionmaker

    s = agent_sessionmaker()()
    try:
        ep = s.execute(
            text(
                """
                SELECT e.id, c.pseudonym, e.amount_paise, e.status::text AS status,
                       e.arm::text AS arm, e.actions_used, e.opened_at, e.closes_at,
                       pe.rail::text AS rail, pe.code_raw
                FROM runtime.episodes e
                JOIN runtime.customers c ON c.id = e.customer_id
                JOIN runtime.payment_events pe ON pe.id = e.payment_event_id
                WHERE e.id = CAST(:eid AS uuid)
                """
            ),
            {"eid": episode_id},
        ).mappings().first()
        if ep is None:
            raise HTTPException(status_code=404, detail="episode not found")

        diagnoses = s.execute(
            text(
                "SELECT canonical_code::text AS canonical_code, confidence::float8 AS confidence, "
                "method::text AS method, rationale, created_at "
                "FROM runtime.diagnoses WHERE episode_id = CAST(:e AS uuid) ORDER BY created_at"
            ),
            {"e": episode_id},
        ).mappings().all()
        candidates = s.execute(
            text(
                "SELECT intervention::text AS intervention, p_recover::float8 AS p_recover, "
                "expected_gain_paise, cost_paise, annoyance_paise, ev_paise, policy_version "
                "FROM runtime.candidate_interventions "
                "WHERE episode_id = CAST(:e AS uuid) ORDER BY ev_paise DESC"
            ),
            {"e": episode_id},
        ).mappings().all()
        actions = s.execute(
            text(
                "SELECT id::text AS id, intervention::text AS intervention, status::text AS status, "
                "channel::text AS channel, cost_paise, mode::text AS mode, policy_version, "
                "guardrail_snapshot, scheduled_for, dispatched_at, message_final, created_at "
                "FROM runtime.actions WHERE episode_id = CAST(:e AS uuid) ORDER BY created_at"
            ),
            {"e": episode_id},
        ).mappings().all()
        outcomes = s.execute(
            text(
                "SELECT outcome::text AS outcome, action_id::text AS action_id, observed_at, latency_secs "
                "FROM runtime.outcomes WHERE episode_id = CAST(:e AS uuid)"
            ),
            {"e": episode_id},
        ).mappings().all()

        return {
            "id": str(ep["id"]),
            "customer_pseudonym": ep["pseudonym"],
            "amount_paise": int(ep["amount_paise"]),
            "status": ep["status"],
            "arm": ep["arm"],
            "rail": ep["rail"],
            "code_raw": ep["code_raw"],
            "actions_used": int(ep["actions_used"]),
            "opened_at": ep["opened_at"].isoformat(),
            "closes_at": ep["closes_at"].isoformat(),
            "diagnoses": [
                {
                    "canonical_code": d["canonical_code"],
                    "confidence": float(d["confidence"]),
                    "method": d["method"],
                    "rationale": d["rationale"],
                    "created_at": d["created_at"].isoformat(),
                }
                for d in diagnoses
            ],
            "candidates": [dict(c) for c in candidates],
            "actions": [
                {
                    "id": a["id"],
                    "intervention": a["intervention"],
                    "status": a["status"],
                    "channel": a["channel"],
                    "cost_paise": int(a["cost_paise"]),
                    "mode": a["mode"],
                    "policy_version": a["policy_version"],
                    "guardrail_snapshot": dict(a["guardrail_snapshot"] or {}),
                    "scheduled_for": a["scheduled_for"].isoformat() if a["scheduled_for"] else None,
                    "dispatched_at": a["dispatched_at"].isoformat() if a["dispatched_at"] else None,
                    "message_final": a["message_final"],
                    "created_at": a["created_at"].isoformat(),
                }
                for a in actions
            ],
            "outcomes": [
                {
                    "outcome": o["outcome"],
                    "action_id": o["action_id"],
                    "observed_at": o["observed_at"].isoformat(),
                    "latency_secs": o["latency_secs"],
                }
                for o in outcomes
            ],
        }
    finally:
        s.close()


@router.post("/episodes/{episode_id}/escalate")
def escalate(
    request: Request,
    episode_id: str,
    user: dict[str, Any] = Depends(require_role(Role.OPERATOR)),
) -> dict:
    request.app.state.rate.check("control_mode", user["user_id"])
    episode_id = require_uuid(episode_id, "episode_id")
    from datetime import datetime

    from reflex.api.db import agent_sessionmaker
    from reflex.workers.outcomes import escalate_human

    s = agent_sessionmaker()()
    try:
        escalate_human(
            s,
            episode_id=episode_id,
            note=f"manual escalation by {user['user_id']}",
            at=datetime.now(UTC),
        )
        s.commit()
        return {"ok": True}
    except Exception as exc:
        s.rollback()
        raise HTTPException(status_code=409, detail=str(exc)[:200]) from exc
    finally:
        s.close()
