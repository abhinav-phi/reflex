"""Ledger APIs: episode trail + chain verification (FR-010)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from reflex.api.params import require_uuid
from reflex.api.security import require_role
from reflex.core.enums import Role
from sqlalchemy import text

router = APIRouter()


@router.get("/episodes/{episode_id}/ledger")
def episode_ledger(
    request: Request,
    episode_id: str,
    user: dict[str, Any] = Depends(require_role(Role.VIEWER)),
) -> dict:
    request.app.state.rate.check("episodes_list", user["user_id"])
    episode_id = require_uuid(episode_id, "episode_id")
    from reflex.api.db import agent_sessionmaker

    s = agent_sessionmaker()()
    try:
        rows = s.execute(
            text(
                "SELECT seq, episode_id::text AS episode_id, action_id::text AS action_id, "
                "event, event::text AS event_text, prev_hash, hash, created_at FROM runtime.action_ledger "
                "WHERE episode_id = CAST(:e AS uuid) ORDER BY seq"
            ),
            {"e": episode_id},
        ).mappings().all()
        valid, first_bad, checked = _verify_range(s, [dict(r) for r in rows])
        if not valid:
            raise HTTPException(status_code=409, detail="chain break detected in this episode's trail")
        return {
            "valid": valid,
            "events": [
                {
                    "seq": r["seq"],
                    "episode_id": r["episode_id"],
                    "action_id": r["action_id"],
                    "event": dict(r["event"]),
                    "prev_hash": r["prev_hash"],
                    "hash": r["hash"],
                    "created_at": r["created_at"].isoformat(),
                }
                for r in rows
            ],
        }
    finally:
        s.close()


def _verify_range(session, rows: list[dict]) -> tuple[bool, int | None, int]:  # type: ignore[no-untyped-def]
    """Verify a contiguous slice; also confirm linkage to the global head."""
    from reflex.ledger.chain import verify_rows

    return verify_rows(rows)


@router.get("/ledger/verify")
def verify(request: Request, user: dict[str, Any] = Depends(require_role(Role.VIEWER))) -> dict:
    request.app.state.rate.check("ledger_verify", user["user_id"])
    from reflex.api.db import agent_sessionmaker
    from reflex.ledger.chain import verify_db

    s = agent_sessionmaker()()
    try:
        valid, first_bad, checked = verify_db(s)
        return {"valid": valid, "first_bad_seq": first_bad, "checked": checked}
    finally:
        s.close()
