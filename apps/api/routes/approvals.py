"""Approval queue APIs (approver role; FR-012)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from reflex.api.security import require_role
from reflex.core.enums import Decision
from reflex.core.schemas import ApprovalDecisionRequest
from sqlalchemy import text

router = APIRouter()


@router.get("/approvals")
def list_approvals(
    request: Request,
    user: dict[str, Any] = Depends(require_role(__import__("reflex.core.enums", fromlist=["Role"]).Role.APPROVER)),
) -> dict:
    request.app.state.rate.check("approvals", user["user_id"])
    from reflex.api.db import agent_sessionmaker

    s = agent_sessionmaker()()
    try:
        rows = s.execute(
            text(
                """
                SELECT ap.id::text AS id, ap.requested_at, ap.decided_at,
                       ap.decision::text AS decision, ap.reason,
                       e.id::text AS episode_id, e.amount_paise, e.status::text AS ep_status,
                       c.pseudonym, a.intervention::text AS intervention,
                       a.status::text AS action_status, a.message_final, a.guardrail_snapshot,
                       (SELECT d.canonical_code::text FROM runtime.diagnoses d
                         WHERE d.episode_id = e.id ORDER BY created_at DESC LIMIT 1) AS dx_code,
                       (SELECT ci.ev_paise FROM runtime.candidate_interventions ci
                         WHERE ci.episode_id = e.id ORDER BY ranked_at DESC, ev_paise DESC LIMIT 1) AS top_ev
                FROM runtime.approvals ap
                JOIN runtime.episodes e ON e.id = ap.episode_id
                JOIN runtime.customers c ON c.id = e.customer_id
                JOIN runtime.actions a ON a.id = ap.action_id
                WHERE ap.decided_at IS NULL
                ORDER BY ap.requested_at
                """
            )
        ).mappings().all()
        return {
            "items": [
                {
                    "id": r["id"],
                    "requested_at": r["requested_at"].isoformat(),
                    "episode_id": r["episode_id"],
                    "amount_paise": int(r["amount_paise"]),
                    "pseudonym": r["pseudonym"],
                    "dx_code": r["dx_code"],
                    "intervention": r["intervention"],
                    "action_status": r["action_status"],
                    "message_final": r["message_final"],
                    "guardrail_snapshot": dict(r["guardrail_snapshot"] or {}),
                    "top_ev_paise": int(r["top_ev"]) if r["top_ev"] is not None else None,
                    "timeout_at": (r["requested_at"] + timedelta(hours=4)).isoformat(),
                }
                for r in rows
            ]
        }
    finally:
        s.close()


@router.post("/approvals/{approval_id}/decide")
def decide(
    approval_id: str,
    body: ApprovalDecisionRequest,
    request: Request,
    user: dict[str, Any] = Depends(require_role(__import__("reflex.core.enums", fromlist=["Role"]).Role.APPROVER)),
) -> dict:
    request.app.state.rate.check("approvals", user["user_id"])
    from reflex.api.db import agent_sessionmaker
    from reflex.ledger.chain import LedgerWriter

    s = agent_sessionmaker()()
    try:
        row = s.execute(
            text(
                "SELECT id, action_id, episode_id, decided_at FROM runtime.approvals "
                "WHERE id = CAST(:id AS uuid) FOR UPDATE"
            ),
            {"id": approval_id},
        ).first()
        if row is None:
            raise HTTPException(status_code=404, detail="approval not found")
        if row[3] is not None:
            raise HTTPException(status_code=409, detail="already decided")

        decision = Decision(body.decision)
        s.execute(
            text(
                "UPDATE runtime.approvals SET decided_at = now(), decided_by = CAST(:u AS uuid), "
                "decision = CAST(:d AS runtime.decision), reason = :r WHERE id = CAST(:id AS uuid)"
            ),
            {"u": user["user_id"], "d": decision.value, "r": body.reason or "", "id": approval_id},
        )

        ledger_note: dict[str, Any] = {
            "type": "APPROVAL_DECIDED",
            "decision": decision.value,
            "by": user["user_id"],
            "reason": body.reason or "",
        }
        if decision is Decision.DECLINE:
            # Decline → branch closed; fail-closed.
            s.execute(
                text("UPDATE runtime.actions SET status = 'blocked' WHERE id = :a AND status = 'waiting_approval'"),
                {"a": row[1]},
            )
            s.execute(
                text(
                    "UPDATE runtime.episodes SET status = 'stopped_approval_declined' "
                    "WHERE id = :e AND status = 'waiting_approval'"
                ),
                {"e": row[2]},
            )
        else:
            # Approve → dispatch proceeds; Shield re-checks at dispatch time.
            s.execute(
                text(
                    "UPDATE runtime.actions SET status = 'scheduled', scheduled_for = now() "
                    "WHERE id = :a AND status = 'waiting_approval'"
                ),
                {"a": row[1]},
            )
            s.execute(
                text("UPDATE runtime.episodes SET status = 'scheduled' WHERE id = :e AND status = 'waiting_approval'"),
                {"e": row[2]},
            )

        LedgerWriter(s).append(episode_id=row[2], action_id=row[1], event=ledger_note)
        s.commit()
        return {"ok": True, "decision": decision.value}
    except HTTPException:
        s.rollback()
        raise
    except Exception as exc:
        s.rollback()
        raise HTTPException(status_code=409, detail=str(exc)[:200]) from exc
    finally:
        s.close()
