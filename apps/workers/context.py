"""Episode execution context — what Shield and the planner need to see.

Counts are computed over the runtime schema ONLY (agent-visible world).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from reflex.core.clock import ist_date_key
from reflex.core.enums import Channel, SuppressionReason


@dataclass(frozen=True)
class EpisodeContext:
    episode_id: str
    customer_id: str
    merchant_id: str
    pseudonym: str
    lang_pref: str
    ltv_band: str
    dnd_flag: bool
    suppressed: bool
    amount_paise: int
    rail: str
    code_raw: str
    actions_used: int
    contacts_today: int
    prior_recovered: bool
    day_of_month: int
    hour_ist: int
    merchant_cfg: dict
    budget_spent_today_paise: int
    opened_at: datetime
    closes_at: datetime


def load_context(session: Session, episode_id: str) -> EpisodeContext | None:
    row = session.execute(
        text(
            """
            SELECT e.id, e.customer_id, e.merchant_id, c.pseudonym, c.lang_pref,
                   c.ltv_band, c.dnd_flag, e.amount_paise,
                   e.actions_used, e.opened_at, e.closes_at,
                   m.cfg
            FROM runtime.episodes e
            JOIN runtime.customers c ON c.id = e.customer_id
            JOIN runtime.merchants m ON m.id = e.merchant_id
            WHERE e.id = :eid
            """
        ),
        {"eid": episode_id},
    ).mappings().first()
    # rail_effective doesn't exist in schema; fetch rail from opening payment_event
    row2 = session.execute(
        text(
            "SELECT pe.rail, pe.code_raw FROM runtime.payment_events pe WHERE pe.id = "
            "(SELECT payment_event_id FROM runtime.episodes WHERE id = :eid)"
        ),
        {"eid": episode_id},
    ).first()
    if row is None or row2 is None:
        return None
    rail = row2[0]
    code_raw = str(row2[1] or "")

    customer_id = str(row["customer_id"])
    day_key = ist_date_key(datetime.now(row["opened_at"].tzinfo or __import__("datetime").timezone.utc))
    # Arm-scoped counts: parallel eval arms share customers/merchants, so
    # contacts/budget must never leak across arms (isolation invariant).
    arm_scope = " AND e2.arm = (SELECT arm FROM runtime.episodes WHERE id = CAST(:eid AS uuid))"

    contacts_today = int(
        session.execute(
            text(
                """
                SELECT count(*) FROM runtime.actions a
                JOIN runtime.episodes e2 ON e2.id = a.episode_id
                WHERE e2.customer_id = :cid"""
                + arm_scope
                + """
                  AND a.status IN ('dispatched','delivered_sim','observed','succeeded')
                  AND a.dispatched_at::date = :day_key
                """
            ),
            {"cid": customer_id, "day_key": day_key, "eid": episode_id},
        ).scalar()
        or 0
    )
    merchant_id = str(row["merchant_id"])
    budget_spent = int(
        session.execute(
            text(
                """
                SELECT COALESCE(sum(a.cost_paise), 0) FROM runtime.actions a
                JOIN runtime.episodes e2 ON e2.id = a.episode_id
                WHERE e2.merchant_id = :mid"""
                + arm_scope
                + """
                  AND a.dispatched_at::date = :day_key
                """
            ),
            {"mid": merchant_id, "day_key": day_key, "eid": episode_id},
        ).scalar()
        or 0
    )
    suppressed = (
        session.execute(
            text("SELECT 1 FROM runtime.suppressions WHERE customer_id = :cid LIMIT 1"),
            {"cid": customer_id},
        ).first()
        is not None
    )
    prior_recovered = (
        session.execute(
            text(
                "SELECT 1 FROM runtime.outcomes o JOIN runtime.episodes e3 ON e3.id = o.episode_id "
                "WHERE e3.customer_id = :cid AND o.outcome = 'recovered' LIMIT 1"
            ),
            {"cid": customer_id},
        ).first()
        is not None
    )

    return EpisodeContext(
        episode_id=str(row["id"]),
        customer_id=customer_id,
        merchant_id=merchant_id,
        pseudonym=row["pseudonym"],
        lang_pref=row["lang_pref"],
        ltv_band=row["ltv_band"],
        dnd_flag=bool(row["dnd_flag"]),
        suppressed=suppressed,
        amount_paise=int(row["amount_paise"]),
        rail=rail,
        code_raw=code_raw,
        actions_used=int(row["actions_used"]),
        contacts_today=contacts_today,
        prior_recovered=prior_recovered,
        day_of_month=row["opened_at"].day,
        hour_ist=row["opened_at"].hour,
        merchant_cfg=dict(row["cfg"] or {}),
        budget_spent_today_paise=budget_spent,
        opened_at=row["opened_at"],
        closes_at=row["closes_at"],
    )


def suppression_reasons(session: Session, customer_id: str) -> list[str]:
    rows = session.execute(
        text("SELECT reason FROM runtime.suppressions WHERE customer_id = :cid"),
        {"cid": customer_id},
    ).scalars().all()
    return [str(r) for r in rows]
