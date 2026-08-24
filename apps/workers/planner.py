"""Episode planner — Brain ranks, Shield disposes (TASK-025 integration).

Horizon-1: enumerate candidates → propensity → EV → persist ALL candidates with
4-term breakdown (FR-006) → rank → Shield in fixed order → schedule/approval/
block. Every step ledgered. Negative-EV ⇒ STOP_LOW_EV logged WITH the math.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import structlog
from reflex.brain.candidates import CandidateSpec, enumerate_candidates
from reflex.brain.ev import (
    EpisodeFeatures,
    channel_cost,
    compute_ev,
    propensity,
)
from reflex.brain.policy_store import load_active_policy
from reflex.core.enums import (
    ActionStatus,
    CanonicalCode,
    Channel,
    Intervention,
    Mode,
)
from reflex.core.state_machine import can_transition_action
from reflex.ledger.chain import LedgerWriter
from reflex.shield.guardrails import (
    ActionProposal,
    MerchantGuardrails,
    ShieldInput,
)
from reflex.shield.guardrails import (
    EpisodeState as ShieldEpisodeState,
)
from reflex.shield.guardrails import (
    evaluate as shield_evaluate,
)
from reflex.workers.context import EpisodeContext
from sqlalchemy import text
from sqlalchemy.orm import Session

log = structlog.get_logger("reflex.planner")

# Ablation A2: fixed-priority policy (EV off) — deterministic fallback ranking.
FIXED_PRIORITY: tuple[Intervention, ...] = (
    Intervention.RETRY_SAME_RAIL,
    Intervention.PAYMENT_LINK_PUSH,
    Intervention.UPI_LINK_PUSH,
    Intervention.MANDATE_REREG_SIM,
    Intervention.WAIT,
)


@dataclass(frozen=True)
class PlanOutcome:
    kind: str  # SCHEDULED | APPROVAL | BLOCKED | STOPPED_LOW_EV | NO_ACTION
    action_id: str | None
    scheduled_for: datetime | None
    reason: str


def plan_episode(
    session: Session,
    ctx: EpisodeContext,
    *,
    diagnosis_code: CanonicalCode,
    now_sim: datetime,
    mode: Mode,
    policy_version: str | None = None,
    policy_params: dict[str, Any] | None = None,
    ev_enabled: bool = True,
    timing_enabled: bool = True,
    at_optimal_hour: bool = True,
    allow_wait: bool = True,
) -> PlanOutcome:
    from reflex.brain.scheduling import next_allowed_contact, schedule_for

    if policy_version is None:
        policy_version, policy_params = load_active_policy(session)

    specs = enumerate_candidates(diagnosis_code)
    if not allow_wait:
        # repeated deferrals exhausted: waiting again is not a strategy
        specs = tuple(s for s in specs if s.intervention is not Intervention.WAIT) or specs
    features = EpisodeFeatures(
        canonical_code=diagnosis_code,
        amount_paise=ctx.amount_paise,
        rail=ctx.rail,  # type: ignore[arg-type]
        contact_count=ctx.actions_used,
        hour_ist=now_sim.astimezone(__import__("zoneinfo").ZoneInfo("Asia/Kolkata")).hour,
        day_of_month=ctx.day_of_month,
        ltv_band=ctx.ltv_band,  # type: ignore[arg-type]
        prior_recovered=ctx.prior_recovered,
        channel=None,
    )

    scored: list[tuple[CandidateSpec, float, Any]] = []
    for spec in specs:
        feats = EpisodeFeatures(**{**features.__dict__, "channel": spec.channel})
        p = propensity(
            feats,
            spec.intervention,
            params=policy_params,
        )
        cost = channel_cost(spec.channel)
        ev = compute_ev(
            p_recover=p,
            amount_paise=ctx.amount_paise,
            cost_paise=cost,
            contact_count=ctx.actions_used,
            ltv_band=ctx.ltv_band,  # type: ignore[arg-type]
        )
        scored.append((spec, p, ev))

    # persist ALL candidates with full breakdown (FR-006) — single round trip
    if scored:
        session.execute(
            text(
                """
                INSERT INTO runtime.candidate_interventions
                  (episode_id, intervention, p_recover, expected_gain_paise, cost_paise,
                   annoyance_paise, ev_paise, policy_version)
                SELECT CAST(:e AS uuid), i::runtime.intervention, p, g, c, a, ev, :pv
                FROM unnest(
                    CAST(:ints AS text[]), CAST(:ps AS float8[]), CAST(:gs AS bigint[]),
                    CAST(:cs AS bigint[]), CAST(:as_ AS bigint[]), CAST(:evs AS bigint[])
                ) AS t(i, p, g, c, a, ev)
                """
            ),
            {
                "e": ctx.episode_id,
                "pv": policy_version,
                "ints": [s.intervention.value for s, _p, _ev in scored],
                "ps": [float(p) for _s, p, _ev in scored],
                "gs": [ev.expected_gain_paise for _s, _p, ev in scored],
                "cs": [ev.cost_paise for _s, _p, ev in scored],
                "as_": [ev.annoyance_paise for _s, _p, ev in scored],
                "evs": [ev.ev_paise for _s, _p, ev in scored],
            },
        )

    ledger = LedgerWriter(session)

    def _rank_key(item: tuple[CandidateSpec, float, Any]) -> tuple[float, int]:
        spec, _p, ev = item
        if not ev_enabled:  # ablation A2: fixed priority order
            try:
                prio = FIXED_PRIORITY.index(spec.intervention)
            except ValueError:
                prio = len(FIXED_PRIORITY)
            return (-float(prio), 0)
        return (float(-ev.ev_paise), 0)

    scored.sort(key=_rank_key)
    top_spec, top_p, top_ev = scored[0]

    ledger.append(
        episode_id=ctx.episode_id,
        event={
            "type": "CANDIDATES_RANKED",
            "policy": policy_version,
            "top": top_spec.intervention.value,
            "top_ev_paise": top_ev.ev_paise,
            "candidates": [
                {"intervention": s.intervention.value, "p_recover": p, **ev.as_dict()}
                for s, p, ev in scored
            ],
        },
        at=now_sim,
    )

    # STOP conditions: explicit stop candidate chosen, or every actionable EV < 0.
    actionable = [(s, p, ev) for s, p, ev in scored if s.intervention is not Intervention.STOP_LOW_EV]
    if top_spec.intervention is Intervention.STOP_LOW_EV or (
        ev_enabled and all(ev.ev_paise < 0 for _s, _p, ev in actionable)
    ):
        worst = min(scored, key=lambda x: x[2].ev_paise)
        ledger.append(
            episode_id=ctx.episode_id,
            event={
                "type": "STOPPED_LOW_EV",
                "reason": "all actionable candidates have negative EV",
                "best_ev_paise": top_ev.ev_paise,
                "math": {
                    "p_recover": top_ev.p_recover,
                    "expected_gain_paise": top_ev.expected_gain_paise,
                    "cost_paise": top_ev.cost_paise,
                    "annoyance_paise": top_ev.annoyance_paise,
                },
                "worst_candidate": worst[0].intervention.value,
            },
            at=now_sim,
        )
        return PlanOutcome("STOPPED_LOW_EV", None, None, f"EV {top_ev.ev_paise} < 0")

    # WAIT candidates carry no dispatch; they reschedule planning itself.
    if top_spec.intervention is Intervention.WAIT:
        wait_until = schedule_for(
            diagnosis_code, Intervention.WAIT, now_sim, ctx.day_of_month, timing_enabled
        )
        action_id = _create_action(
            session,
            ctx,
            intervention=Intervention.WAIT,
            channel=None,
            cost=0,
            status=ActionStatus.SHIELD_PASS,
            mode=mode,
            policy_version=policy_version,
            guardrail_snapshot={"note": "wait bookkeeping", "mode": mode.value},
            scheduled_for=wait_until,
            now_sim=now_sim,
            ledger=ledger,
        )
        return PlanOutcome("SCHEDULED", str(action_id), wait_until, "wait")

    # ---- Shield decides -------------------------------------------------------
    proposal = ActionProposal(
        intervention=top_spec.intervention,
        channel=top_spec.channel,
        amount_paise=ctx.amount_paise,
        cost_paise=top_ev.cost_paise,
    )
    decision = shield_evaluate(
        ShieldInput(
            proposal=proposal,
            episode=ShieldEpisodeState(
                episode_id=ctx.episode_id,
                actions_used=ctx.actions_used,
                customer_id=ctx.customer_id,
                contacts_today=ctx.contacts_today,
                suppressed=ctx.suppressed,
                dnd_flag=ctx.dnd_flag,
            ),
            mode=mode,
            guardrails=MerchantGuardrails.from_merchant_cfg(ctx.merchant_cfg),
            budget_spent_today_paise=ctx.budget_spent_today_paise,
            now_sim=now_sim,
        )
    )

    action_status = {
        "PASS": ActionStatus.SHIELD_PASS,
        "APPROVAL": ActionStatus.WAITING_APPROVAL,
        "BLOCKED": ActionStatus.BLOCKED,
    }[decision.outcome]

    scheduled_for: datetime | None = None
    if decision.passed:
        raw_for = schedule_for(
            diagnosis_code,
            top_spec.intervention,
            now_sim,
            ctx.day_of_month,
            timing_enabled and at_optimal_hour,
        )
        scheduled_for = next_allowed_contact(raw_for) if top_spec.channel is not None else raw_for

    action_id = _create_action(
        session,
        ctx,
        intervention=top_spec.intervention,
        channel=top_spec.channel,
        cost=top_ev.cost_paise,
        status=action_status,
        mode=mode,
        policy_version=policy_version,
        guardrail_snapshot=decision.snapshot() | {"checks": decision.checks, "reason": decision.reason},
        scheduled_for=scheduled_for,
        now_sim=now_sim,
        ledger=ledger,
        ev_terms=top_ev.as_dict(),
    )

    if decision.passed:
        # advance shield_pass → scheduled immediately (same transaction; Shield
        # will re-check at dispatch time — Rules §3.3)
        from reflex.workers.dispatcher import transition_action

        transition_action(session, str(action_id), ActionStatus.SCHEDULED)

    if decision.needs_approval:
        session.execute(
            text(
                "INSERT INTO runtime.approvals (episode_id, action_id) VALUES (:e, :a)"
            ),
            {"e": ctx.episode_id, "a": action_id},
        )
        ledger.append(
            episode_id=ctx.episode_id,
            action_id=action_id,
            event={"type": "APPROVAL_REQUESTED", "reason": decision.reason},
            at=now_sim,
        )
        return PlanOutcome("APPROVAL", str(action_id), None, decision.reason)

    if decision.outcome == "BLOCKED":
        return PlanOutcome("BLOCKED", str(action_id), None, decision.reason)

    return PlanOutcome("SCHEDULED", str(action_id), scheduled_for, decision.reason)


def _create_action(
    session: Session,
    ctx: EpisodeContext,
    *,
    intervention: Intervention,
    channel: Channel | None,
    cost: int,
    status: ActionStatus,
    mode: Mode,
    policy_version: str,
    guardrail_snapshot: dict[str, Any],
    scheduled_for: datetime | None,
    now_sim: datetime,
    ledger: LedgerWriter,
    ev_terms: dict[str, Any] | None = None,
) -> Any:
    assert can_transition_action(ActionStatus.PROPOSED, status), f"bad first status {status}"
    seq_now = int(
        session.execute(
            text("SELECT count(*) FROM runtime.actions WHERE episode_id = :e"),
            {"e": ctx.episode_id},
        ).scalar()
        or 0
    ) + 1
    idem = f"act:{ctx.episode_id}:{seq_now}"
    row = session.execute(
        text(
            """
            INSERT INTO runtime.actions
              (episode_id, intervention, status, idempotency_key, channel, cost_paise,
               mode, policy_version, guardrail_snapshot, scheduled_for)
            VALUES
              (:e, CAST(:i AS runtime.intervention), CAST(:st AS runtime.action_status),
               :idem, CAST(:ch AS runtime.channel), :cost, CAST(:m AS runtime.mode),
               :pv, CAST(:gs AS jsonb), :sf)
            RETURNING id
            """
        ),
        {
            "e": ctx.episode_id,
            "i": intervention.value,
            "st": status.value,
            "idem": idem,
            "ch": channel.value if channel else None,
            "cost": cost,
            "m": mode.value,
            "pv": policy_version,
            "gs": __import__("json").dumps(guardrail_snapshot),
            "sf": scheduled_for,
        },
    ).first()
    action_id = row[0]

    event: dict[str, Any] = {
        "type": "ACTION_CREATED",
        "intervention": intervention.value,
        "channel": channel.value if channel else None,
        "status": status.value,
        "idempotency_key": idem,
        "reason": guardrail_snapshot.get("reason"),
        "mode": mode.value,
    }
    if ev_terms:
        event["ev"] = ev_terms
    ledger.append(episode_id=ctx.episode_id, action_id=action_id, event=event, at=now_sim)
    log.info(
        "action_created",
        episode_id=ctx.episode_id,
        intervention=intervention.value,
        status=status.value,
        mode=mode.value,
    )
    return action_id
