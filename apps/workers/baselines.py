"""Baseline arms B0 / B1 (PRD FR-016) — measurement policies, not the agent.

B0 do-nothing: organic recovery only; no actions ever.
B1 tuned naive: immediate same-rail retry ×3 (t+0/6/24h) + generic English SMS
blast ×2 (t+2h/30h). Tuning offsets are pre-registered in eval/PROTOCOL.md §3;
the tuning SEARCH ran on dev seeds only and is documented in eval/results.

Baselines still ledger every action (100% actions ledgered is a system
invariant), but they deliberately bypass Brain/Shield — that IS the naive
policy being measured. The simulator enforces the compliance floor: customers
do not respond to off-quiet-hours contacts.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import structlog
from sqlalchemy import text
from sqlalchemy.orm import Session

from reflex.core.enums import Channel, EpisodeStatus, Intervention, Mode
from reflex.ledger.chain import LedgerWriter

log = structlog.get_logger("reflex.baselines")

# Pre-registered B1 shape (eval/PROTOCOL.md §3); tuning search may adjust via params.
B1_DEFAULTS = {
    "retry_offsets_hours": (0.0, 6.0, 24.0),
    "sms_offsets_hours": (2.0, 30.0),
}


@dataclass(frozen=True)
class BaselinePlan:
    actions: list[dict]  # {intervention, channel, cost_paise, scheduled_for}


def plan_b1(
    session: Session,
    *,
    episode_id: str,
    amount_paise: int,
    now_sim: datetime,
    params: dict | None = None,
    mode: Mode = Mode.AUTONOMOUS,
    policy_version: str = "b1-tuned",
) -> BaselinePlan:
    p = dict(B1_DEFAULTS)
    if params:
        p.update(params)
    ledger = LedgerWriter(session)
    seq_now = int(
        session.execute(
            text("SELECT count(*) FROM runtime.actions WHERE episode_id = :e"),
            {"e": episode_id},
        ).scalar()
        or 0
    )
    from datetime import timedelta

    actions: list[dict] = []
    for i, h in enumerate(p["retry_offsets_hours"]):
        seq_now += 1
        actions.append(
            {
                "intervention": Intervention.RETRY_SAME_RAIL,
                "channel": Channel.RAZORPAY_TM,
                "cost_paise": 0,
                "scheduled_for": now_sim + timedelta(hours=h),
                "idem": f"act:{episode_id}:{seq_now}",
                "note": f"b1 retry #{i+1}",
            }
        )
    for i, h in enumerate(p["sms_offsets_hours"]):
        seq_now += 1
        actions.append(
            {
                "intervention": Intervention.PAYMENT_LINK_PUSH,
                "channel": Channel.SMS_SIM,
                "cost_paise": 18,
                "scheduled_for": now_sim + timedelta(hours=h),
                "idem": f"act:{episode_id}:{seq_now}",
                "note": f"b1 generic SMS blast #{i+1} [SIMULATED]",
            }
        )

    created: list[dict] = []
    for a in actions:
        row = session.execute(
            text(
                """
                INSERT INTO runtime.actions
                  (episode_id, intervention, status, idempotency_key, channel, cost_paise,
                   mode, policy_version, guardrail_snapshot, scheduled_for)
                VALUES (:e, CAST(:i AS runtime.intervention), 'scheduled', :idem,
                        CAST(:ch AS runtime.channel), :cost, CAST(:m AS runtime.mode),
                        :pv, CAST(:gs AS jsonb), :sf)
                ON CONFLICT (idempotency_key) DO NOTHING
                RETURNING id
                """
            ),
            {
                "e": episode_id,
                "i": a["intervention"].value,
                "idem": a["idem"],
                "ch": a["channel"].value,
                "cost": a["cost_paise"],
                "m": mode.value,
                "pv": policy_version,
                "gs": '{"policy":"b1","naive":true}',
                "sf": a["scheduled_for"],
            },
        ).first()
        if row is not None:
            ledger.append(
                episode_id=episode_id,
                action_id=row[0],
                event={
                    "type": "ACTION_CREATED",
                    "policy": "b1-tuned-naive",
                    "intervention": a["intervention"].value,
                    "channel": a["channel"].value,
                    "note": a["note"],
                    "[SIMULATED]": a["channel"] != Channel.RAZORPAY_TM,
                },
                at=now_sim,
            )
            created.append(a)
    return BaselinePlan(actions=created)


def plan_b0(*args: object, **kwargs: object) -> BaselinePlan:
    """B0 does nothing — organic recovery only."""
    return BaselinePlan(actions=[])
