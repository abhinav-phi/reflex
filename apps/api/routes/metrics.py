"""Metrics: live counters + eval results (FR-019)."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from reflex.api.params import require_uuid
from reflex.api.security import require_role
from reflex.core.enums import Role
from sqlalchemy import text

router = APIRouter()

COUNTER_KEYS = [
    "events_ingested", "duplicates_collapsed", "episodes_created",
    "dx_rule", "dx_llm", "shield_pass", "shield_block", "shield_approval",
    "dispatched", "recovered",
]


@router.get("/metrics/live")
def live(request: Request, arm: str | None = Query(default=None), user: dict[str, Any] = Depends(require_role(Role.VIEWER))) -> dict:
    request.app.state.rate.check("metrics_live", user["user_id"])
    from reflex.api.db import agent_sessionmaker

    s = agent_sessionmaker()()
    try:
        failed = s.execute(
            text("SELECT COALESCE(sum(amount_paise),0) FROM runtime.episodes")
        ).scalar()
        recovered_reflex = s.execute(
            text(
                """
                SELECT COALESCE(sum(e.amount_paise),0) FROM runtime.outcomes o
                JOIN runtime.episodes e ON e.id = o.episode_id
                WHERE o.outcome = 'recovered' AND (CAST(:arm AS text) IS NULL OR e.arm::text = :arm)
                """
            ),
            {"arm": arm},
        ).scalar()
        recovered_b1 = s.execute(
            text(
                "SELECT COALESCE(sum(e.amount_paise),0) FROM runtime.outcomes o "
                "JOIN runtime.episodes e ON e.id = o.episode_id "
                "WHERE o.outcome = 'recovered' AND e.arm = 'b1'"
            )
        ).scalar()
        complaints = s.execute(
            text("SELECT count(*) FROM runtime.suppressions WHERE reason = 'complaint'")
        ).scalar()
        episodes_total = s.execute(text("SELECT count(*) FROM runtime.episodes")).scalar()
        terminal = s.execute(
            text(
                "SELECT count(*) FROM runtime.episodes WHERE status IN "
                "('recovered','expired','stopped_cap','stopped_low_ev','stopped_customer',"
                "'stopped_approval_declined','escalated','halted')"
            )
        ).scalar()
        cost = s.execute(
            text(
                "SELECT COALESCE(sum(a.cost_paise),0) FROM runtime.actions a "
                "JOIN runtime.episodes e ON e.id = a.episode_id "
                "WHERE a.dispatched_at IS NOT NULL AND (e.arm::text = :arm OR :arm IS NULL)"
            ),
            {"arm": arm},
        ).scalar()
        mode_row = s.execute(text("SELECT mode::text FROM runtime.merchants ORDER BY created_at LIMIT 1")).scalar()
        merchant_row = s.execute(
            text("SELECT name, cfg FROM runtime.merchants ORDER BY created_at LIMIT 1")
        ).first()
        # Shield card live state: actions dispatched since local midnight (contacts)
        try:
            contacts_today = s.execute(
                text(
                    "SELECT count(*) FROM runtime.actions a "
                    "WHERE a.dispatched_at >= date_trunc('day', now())"
                )
            ).scalar()
        except Exception:
            contacts_today = 0
        redis = request.app.state.redis
        speed = 1.0
        try:
            clock = json.loads(redis.get("reflex:clock") or "{}") if hasattr(redis, "get") else {}
            speed = float(clock.get("speed", 1.0))
        except Exception:
            pass

        counters = {k: int(redis.get(f"reflex:ctr:{k}") or 0) for k in COUNTER_KEYS}

        recovered_val = int(recovered_reflex or 0)
        cfg = dict(merchant_row[1] or {}) if merchant_row else {}
        return {
            "failed_today_paise": int(failed or 0),
            "recovered_reflex_paise": recovered_val,
            "recovered_b1_paise": int(recovered_b1 or 0),
            "complaint_rate": (float(complaints) / episodes_total) if episodes_total else 0.0,
            "cost_per_100p": (float(cost) * 100 / recovered_val) if recovered_val and cost is not None else None,
            "episodes_open": int(episodes_total or 0) - int(terminal or 0),
            "episodes_terminal": int(terminal or 0),
            "speed": speed,
            "mode": str(mode_row or "advisory"),
            "llm_outage": bool(redis.get("reflex:inject:llm_outage")) if hasattr(redis, "get") else False,
            "merchant_name": str(merchant_row[0]) if merchant_row else None,
            "contacts_today": int(contacts_today or 0),
            "contacts_per_day": int(cfg.get("contacts_per_day", 2)),
            "quiet_hours": str(cfg.get("quiet_hours", "21:00-09:00")),
            "counters": counters,
        }
    finally:
        s.close()


@router.get("/metrics/eval")
def eval_metrics(
    request: Request,
    run_id: str | None = Query(default=None),
    user: dict[str, Any] = Depends(require_role(Role.VIEWER)),
) -> dict:
    """All values [SIMULATED] — eval evidence from committed runs."""
    request.app.state.rate.check("metrics_eval", user["user_id"])
    if run_id:
        run_id = require_uuid(run_id, "run_id")
    from reflex.api.db import eval_sessionmaker

    s = eval_sessionmaker()()
    try:
        if run_id:
            run = s.execute(
                text("SELECT id::text FROM eval.eval_runs WHERE id = CAST(:r AS uuid)"), {"r": run_id}
            ).scalar()
            if run is None:
                return {"runs": [], "metrics": []}
        rows = s.execute(
            text(
                """
                SELECT r.id::text AS run_id, r.arm::text AS arm, r.ablation, r.preregistered_tag,
                       r.created_at, m.metric, m.value::float8 AS value,
                       m.ci_low::float8 AS ci_low, m.ci_high::float8 AS ci_high, m.seed
                FROM eval.eval_runs r LEFT JOIN eval.eval_metrics m ON m.run_id = r.id
                WHERE (CAST(:run_id AS text) IS NULL OR r.id::text = :run_id)
                ORDER BY r.created_at DESC
                """
            ),
            {"run_id": run_id},
        ).mappings().all()
        runs: dict[str, dict] = {}
        for row in rows:
            entry = runs.setdefault(
                str(row["run_id"]),
                {
                    "run_id": row["run_id"],
                    "arm": row["arm"],
                    "ablation": row["ablation"],
                    "preregistered_tag": row["preregistered_tag"],
                    "created_at": row["created_at"].isoformat(),
                    "[SIMULATED]": True,
                    "metrics": [],
                },
            )
            if row["metric"]:
                entry["metrics"].append(
                    {
                        "metric": row["metric"],
                        "value": row["value"],
                        "ci_low": row["ci_low"],
                        "ci_high": row["ci_high"],
                        "seed": row["seed"],
                    }
                )
        return {"[SIMULATED]": True, "runs": list(runs.values())}
    finally:
        s.close()
