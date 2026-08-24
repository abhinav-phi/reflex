"""Data export APIs (TASK-039): CSV/JSON dumps of episodes and the ledger.

Every response carries the mandatory watermark — an `X-Reflex-Data-Watermark`
response header AND an inline first CSV comment line / `_watermark` JSON field:
`# REFLEX SIMULATION DATA - NOT REAL TRANSACTIONS` (honesty labeling, Rules §16).
Exports are viewer+ and rate-limited like every other read path.
"""

from __future__ import annotations

import csv
import io
import json
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import text

from reflex.api.security import require_role
from reflex.core.enums import Role

router = APIRouter()

WATERMARK = "# REFLEX SIMULATION DATA - NOT REAL TRANSACTIONS"
WATERMARK_HEADER = "X-Reflex-Data-Watermark"


def _rate(request: Request, bucket: str, user: dict) -> None:  # type: ignore[type-arg]
    request.app.state.rate.check(bucket, user["user_id"])


def _csv_response(filename: str, header_row: list[str], rows: list[list[Any]]) -> Response:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([WATERMARK])
    writer.writerow(header_row)
    writer.writerows(rows)
    return Response(
        content=buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={
            WATERMARK_HEADER: WATERMARK,
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


def _json_response(items: list[dict]) -> Response:
    body = {"_watermark": WATERMARK, "count": len(items), "items": items}
    return Response(
        content=json.dumps(body, default=str),
        media_type="application/json",
        headers={WATERMARK_HEADER: WATERMARK},
    )


@router.get("/episodes/export")
def export_episodes(
    request: Request,
    format: str = Query(default="csv", pattern="^(csv|json)$"),
    limit: int = Query(default=1000, le=5000, ge=1),
    user: dict[str, Any] = Depends(require_role(Role.VIEWER)),
) -> Response:
    _rate(request, "episodes_list", user)
    from reflex.api.db import agent_sessionmaker

    s = agent_sessionmaker()()
    try:
        rows = s.execute(
            text(
                """
                SELECT e.id, c.pseudonym, e.amount_paise, e.status::text AS status,
                       e.arm::text AS arm, pe.rail::text AS rail, e.actions_used,
                       e.opened_at,
                       d.canonical_code::text AS dx_code, d.confidence::float8 AS dx_conf
                FROM runtime.episodes e
                JOIN runtime.customers c ON c.id = e.customer_id
                JOIN runtime.payment_events pe ON pe.id = e.payment_event_id
                LEFT JOIN LATERAL (
                    SELECT * FROM runtime.diagnoses dx WHERE dx.episode_id = e.id
                    ORDER BY dx.created_at DESC LIMIT 1
                ) d ON true
                ORDER BY e.opened_at DESC
                LIMIT :limit
                """
            ),
            {"limit": limit},
        ).mappings().all()
    finally:
        s.close()

    if format == "csv":
        header = [
            "episode_id", "customer_pseudonym", "amount_paise", "status", "arm",
            "rail", "actions_used", "opened_at", "dx_code", "dx_confidence",
        ]
        out_rows = [
            [
                str(r["id"]), r["pseudonym"], int(r["amount_paise"]), r["status"],
                r["arm"], r["rail"], int(r["actions_used"]),
                r["opened_at"].isoformat(), r["dx_code"], r["dx_conf"],
            ]
            for r in rows
        ]
        return _csv_response("reflex_episodes_simulated.csv", header, out_rows)

    items = [
        {
            "episode_id": str(r["id"]),
            "customer_pseudonym": r["pseudonym"],
            "amount_paise": int(r["amount_paise"]),
            "status": r["status"],
            "arm": r["arm"],
            "rail": r["rail"],
            "actions_used": int(r["actions_used"]),
            "opened_at": r["opened_at"].isoformat(),
            "dx_code": r["dx_code"],
            "dx_confidence": None if r["dx_conf"] is None else float(r["dx_conf"]),
        }
        for r in rows
    ]
    return _json_response(items)


@router.get("/ledger/export")
def export_ledger(
    request: Request,
    format: str = Query(default="csv", pattern="^(csv|json)$"),
    limit: int = Query(default=1000, le=10000, ge=1),
    user: dict[str, Any] = Depends(require_role(Role.VIEWER)),
) -> Response:
    _rate(request, "episodes_ledger", user)
    from reflex.api.db import agent_sessionmaker

    s = agent_sessionmaker()()
    try:
        rows = s.execute(
            text(
                """
                SELECT seq, episode_id::text AS episode_id, action_id::text AS action_id,
                       event, prev_hash, hash, created_at
                FROM runtime.action_ledger
                ORDER BY seq
                LIMIT :limit
                """
            ),
            {"limit": limit},
        ).mappings().all()
    finally:
        s.close()

    if format == "csv":
        header = ["seq", "episode_id", "action_id", "event_json", "prev_hash", "hash", "created_at"]
        out_rows = [
            [
                int(r["seq"]), r["episode_id"], r["action_id"],
                json.dumps(r["event"], default=str), r["prev_hash"], r["hash"],
                r["created_at"].isoformat(),
            ]
            for r in rows
        ]
        return _csv_response("reflex_action_ledger_simulated.csv", header, out_rows)

    items = [
        {
            "seq": int(r["seq"]),
            "episode_id": r["episode_id"],
            "action_id": r["action_id"],
            "event": dict(r["event"]),
            "prev_hash": r["prev_hash"],
            "hash": r["hash"],
            "created_at": r["created_at"].isoformat(),
        }
        for r in rows
    ]
    return _json_response(items)
