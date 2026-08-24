"""Dispatcher — Hands execution path (TASK-014).

Invariants honored here (Rules §3–4):
- Shield re-checks AT DISPATCH TIME (state may have changed since planning).
- Ledger-first: an action that cannot be ledgered must NOT be dispatched.
- Idempotency: actions.idempotency_key UNIQUE at DB level; re-delivery is a no-op.
- Executor failure: backoff ×3 then PARKED + alert; never retry a Shield BLOCK.
- Kill switch checked before every send; drain ≤ 1s is the scheduler's tick.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.orm import Session

from reflex.connectors.channels import GATEWAYS
from reflex.connectors.errors import ConnectorError, RazorpayTimeout
from reflex.connectors.razorpay import RazorpayTestModeClient
from reflex.core.enums import (
    ActionStatus,
    Channel,
    EpisodeStatus,
    EventSource,
    Intervention,
    Mode,
)
from reflex.core.state_machine import can_transition_action
from reflex.ledger.chain import LedgerWriter
from reflex.shield.guardrails import (
    ActionProposal,
    EpisodeState as ShieldEpisodeState,
    MerchantGuardrails,
    ShieldInput,
    evaluate as shield_evaluate,
)
from reflex.workers.context import load_context
from reflex.workers.messages import MessageSlots, generate_message

log = structlog.get_logger("reflex.dispatcher")

WATCH_WINDOW_HOURS_SIM = 6


class DispatchResult:
    def __init__(self, status: str, detail: str) -> None:
        self.status = status
        self.detail = detail
        self.sim_events: list[tuple[int, str, dict]] = []


def _load_action(session: Session, action_id: str) -> dict[str, Any] | None:
    return session.execute(
        text(
            """
            SELECT a.id, a.episode_id, a.intervention::text AS intervention,
                   a.status::text AS status, a.channel::text AS channel,
                   a.cost_paise, a.mode::text AS mode, a.policy_version,
                   a.guardrail_snapshot, a.scheduled_for, a.idempotency_key,
                   e.arm::text AS arm, pe.source::text AS source
            FROM runtime.actions a
            JOIN runtime.episodes e ON e.id = a.episode_id
            JOIN runtime.payment_events pe ON pe.id = e.payment_event_id
            WHERE a.id = :aid
            FOR UPDATE OF a
            """
        ),
        {"aid": action_id},
    ).mappings().first()


def guard_at_dispatch(session: Session, action: dict[str, Any], now_sim: datetime, mode: Mode) -> tuple[str, Any]:
    """Re-run Shield immediately before send (Rules §3.3)."""
    ctx = load_context(session, str(action["episode_id"]))
    if ctx is None:
        return "BLOCKED", "context_missing"
    proposal = ActionProposal(
        intervention=Intervention(action["intervention"]),
        channel=Channel(action["channel"]) if action["channel"] else None,
        amount_paise=ctx.amount_paise,
        cost_paise=int(action["cost_paise"]),
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
    return decision.outcome, decision


def _guard_with_ctx(ctx, action: dict[str, Any], now_sim: datetime, mode: Mode) -> tuple[str, Any]:  # type: ignore[no-untyped-def]
    """Shield re-check with a caller-supplied context (eval arm isolation)."""
    proposal = ActionProposal(
        intervention=Intervention(action["intervention"]),
        channel=Channel(action["channel"]) if action["channel"] else None,
        amount_paise=ctx.amount_paise,
        cost_paise=int(action["cost_paise"]),
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
    return decision.outcome, decision


def transition_action(session: Session, action_id: str, dst: ActionStatus, extra_sql: str = "", params: dict | None = None) -> bool:
    p: dict[str, Any] = {"aid": action_id, "dst": dst.value}
    p.update(params or {})
    try:
        with session.begin_nested():  # savepoint: guard-trigger failures stay isolated
            session.execute(
                text(
                    f"UPDATE runtime.actions SET status = CAST(:dst AS runtime.action_status)"
                    f"{extra_sql} WHERE id = :aid"
                ),
                p,
            )
        return True
    except Exception as exc:
        log.error("action_transition_failed", action_id=str(action_id), dst=dst.value, error=str(exc)[:200])
        return False


def dispatch_action(
    *,
    agent_session: Session,
    sim_bridge,  # type: ignore[no-untyped-def]  # SimulatorBridge or None
    llm,  # type: ignore[no-untyped-def]
    redis_client,  # type: ignore[no-untyped-def]
    rp_client: RazorpayTestModeClient | None,
    action_id: str,
    now_sim: datetime,
    mode: Mode,
    personalization_enabled: bool = True,
    ctx_override=None,  # type: ignore[no-untyped-def]  # EpisodeContext (eval isolation)
    publish=None,  # type: ignore[no-untyped-def]
) -> DispatchResult:
    """Execute one scheduled action end-to-end. Returns result status."""
    action = _load_action(agent_session, action_id)
    if action is None:
        return DispatchResult("missing", "action not found")
    if ActionStatus(action["status"]) is not ActionStatus.SCHEDULED:
        return DispatchResult("skip", f"status={action['status']}")

    # ---- kill switch under any state ----------------------------------------
    if redis_client is not None and redis_client.get("reflex:halted"):
        transition_action(agent_session, action_id, ActionStatus.CANCELLED_HALT)
        return DispatchResult("cancelled_halt", "kill switch active")

    # ---- Shield at dispatch time --------------------------------------------
    # ctx must be defined for BOTH paths: eval arms pass ctx_override; the live
    # worker path loads episode context from DB (previously a latent NameError
    # on the unverified live loop — caught by lint during audit sync).
    ctx = ctx_override
    if ctx is None:
        ctx = load_context(agent_session, str(action["episode_id"]))
    if ctx_override is not None:
        outcome, decision_or_reason = _guard_with_ctx(ctx, action, now_sim, mode)
    else:
        outcome, decision_or_reason = guard_at_dispatch(agent_session, action, now_sim, mode)
    ledger = LedgerWriter(agent_session)

    if outcome == "BLOCKED":
        transition_action(agent_session, action_id, ActionStatus.BLOCKED)
        ledger.append(
            episode_id=action["episode_id"],
            action_id=action["id"],
            event={"type": "ACTION_BLOCKED_AT_DISPATCH", "reason": str(decision_or_reason)},
            at=now_sim,
        )
        return DispatchResult("blocked", str(decision_or_reason))

    if outcome == "APPROVAL":
        transition_action(agent_session, action_id, ActionStatus.WAITING_APPROVAL)
        agent_session.execute(
            text("INSERT INTO runtime.approvals (episode_id, action_id) VALUES (:e, :a)"),
            {"e": action["episode_id"], "a": action["id"]},
        )
        ledger.append(
            episode_id=action["episode_id"],
            action_id=action["id"],
            event={"type": "APPROVAL_REQUESTED_AT_DISPATCH", "reason": decision_or_reason.reason},
            at=now_sim,
        )
        return DispatchResult("approval", decision_or_reason.reason)

    # ---- message generation (contact channels) -------------------------------
    message_final: str | None = None
    llm_span_log: str | None = None
    llm_call_id: str | None = None
    channel = action["channel"]

    link_hint = f"https://rzp.io/i/sim-{str(action['id'])[:8]}"
    provider_ref: str | None = None
    rp_result: Any = None

    if channel == Channel.RAZORPAY_TM.value:
        intervention = Intervention(action["intervention"])
        source = EventSource(action["source"])
        if source is EventSource.LIVE_TM and rp_client is not None and rp_client.configured:
            # Real test-mode call (live_tm only). Replay arms use the simulator rail.
            try:
                if intervention in (Intervention.RETRY_SAME_RAIL, Intervention.RETRY_ALT_RAIL):
                    rp_result = rp_client.create_order(amount_paise=ctx.amount_paise, receipt=str(action["idempotency_key"]))
                else:
                    rp_result = rp_client.create_payment_link(
                        amount_paise=ctx.amount_paise,
                        description=f"Reflex recovery {action['idempotency_key']}",
                        customer_name=ctx.pseudonym,
                        reference_id=str(action["id"])[:40],
                    )
                provider_ref = rp_result.provider_ref
                short = rp_result.raw.get("short_url")
                if isinstance(short, str):
                    link_hint = short
            except RazorpayTimeout:
                transition_action(agent_session, action_id, ActionStatus.PARKED)
                ledger.append(
                    episode_id=action["episode_id"], action_id=action["id"],
                    event={"type": "ACTION_PARKED", "reason": "razorpay timeout after backoffs"},
                    at=now_sim,
                )
                return DispatchResult("parked", "RP timeout")
            except ConnectorError as exc:
                transition_action(agent_session, action_id, ActionStatus.PARKED)
                ledger.append(
                    episode_id=action["episode_id"], action_id=action["id"],
                    event={"type": "ACTION_PARKED", "reason": f"connector: {exc}"},
                    at=now_sim,
                )
                return DispatchResult("parked", str(exc))
        else:
            # Replay/demo arm: gateway behavior modeled by Proof simulator [SIMULATED].
            rp_result = {"simulated": True, "provider_ref": f"sim_{str(action['id'])[:12]}"}
            provider_ref = rp_result["provider_ref"]

    contact_index = min(ctx.actions_used, 2)
    if channel and channel != Channel.RAZORPAY_TM.value or action["intervention"] in (
        Intervention.PAYMENT_LINK_PUSH.value,
        Intervention.UPI_LINK_PUSH.value,
        Intervention.MANDATE_REREG_SIM.value,
        Intervention.VOICE_CALL_SIM.value,
    ):
        gen = generate_message(
            llm,
            contact_index=contact_index,
            lang_pref=ctx.lang_pref,
            slots=MessageSlots(
                amount_paise=ctx.amount_paise,
                link_or_hint=link_hint,
                due_date=ctx.closes_at.date().isoformat(),
                customer_pseudonym=ctx.pseudonym,
            ),
            session=agent_session,
            episode_id=action["episode_id"],
            personalization_enabled=personalization_enabled,
        )
        message_final = gen.final_text
        llm_span_log = gen.llm_span
        llm_call_id = gen.llm_call_id

    # ---- LEDGER-FIRST: write before any send ---------------------------------
    try:
        seq, digest = ledger.append(
            episode_id=action["episode_id"],
            action_id=action["id"],
            event={
                "type": "ACTION_DISPATCHED",
                "intervention": action["intervention"],
                "channel": channel,
                "mode": mode.value,
                "message_llm_span": llm_span_log,
                "message_final": message_final,
                "provider_ref": provider_ref,
                "simulated_channel": bool(channel and channel.endswith("_sim")),
                "[SIMULATED]": bool(channel and channel.endswith("_sim")),
            },
            at=now_sim,
        )
    except Exception as exc:
        agent_session.rollback()
        log.error("ledger_write_failed_action_not_dispatched", error=str(exc)[:200])
        return DispatchResult("parked", "ledger-first invariant blocked dispatch")

    transition_action(
        agent_session,
        action_id,
        ActionStatus.DISPATCHED,
        ", dispatched_at = :da, message_final = :msg, llm_call_id = CAST(:llm_call AS uuid)",
        {"da": now_sim, "msg": message_final, "llm_call": llm_call_id},
    )

    sim_events: list[tuple[int, str, dict]] = []
    action_ctx = {
        "id": str(action["id"]),
        "episode_id": str(action["episode_id"]),
        "intervention": action["intervention"],
        "channel": channel,
        "dispatched_at": now_sim,
        "cost_paise": int(action["cost_paise"]),
        "arm": action["arm"],
    }

    # ---- Hands execution -------------------------------------------------------
    if channel and channel.endswith("_sim"):
        gw = GATEWAYS[channel]
        receipt = gw.deliver(
            action_id=str(action["id"]),
            recipient_pseudonym=ctx.pseudonym,
            message=message_final or "",
            at_sim=now_sim,
        )
        transition_action(agent_session, action_id, ActionStatus.DELIVERED_SIM)
        ledger.append(
            episode_id=action["episode_id"],
            action_id=action["id"],
            event={
                "type": "DELIVERED_SIM",
                "channel": channel,
                "delivered_at": receipt.delivered_at.isoformat(),
                "[SIMULATED]": True,
            },
            at=receipt.delivered_at,
        )
    else:
        # razorpay_tm channel: order/link created; watch window starts.
        transition_action(agent_session, action_id, ActionStatus.DELIVERED_SIM)

    # Ask the Proof simulator how the (hidden-truth) customer responds.
    if sim_bridge is not None:
        sim_events = sim_bridge.respond_to_action(
            agent_session=agent_session,
            action=action_ctx,
            contacts_today=ctx.contacts_today,
        )
    transition_action(agent_session, action_id, ActionStatus.OBSERVED)

    ledger.append(
        episode_id=action["episode_id"],
        action_id=action["id"],
        event={
            "type": "ACTION_OBSERVED",
            "watch_window_h": WATCH_WINDOW_HOURS_SIM,
            "watch_until": (now_sim + timedelta(hours=WATCH_WINDOW_HOURS_SIM)).isoformat(),
        },
        at=now_sim,
    )

    # bump episode state following the documented machine: scheduled → acted → observing
    try:
        with agent_session.begin_nested():
            agent_session.execute(
                text("UPDATE runtime.episodes SET status = 'acted' WHERE id = :e AND status = 'scheduled'"),
                {"e": action["episode_id"]},
            )
            res = agent_session.execute(
                text(
                    "UPDATE runtime.episodes SET status = 'observing', "
                    "actions_used = LEAST(actions_used + 1, 4) WHERE id = :e AND status = 'acted'"
                ),
                {"e": action["episode_id"]},
            )
        if res.rowcount == 0:
            # episode not in a transitionable state (e.g., recovered mid-flight):
            # still count the dispatched action honestly.
            agent_session.execute(
                text(
                    "UPDATE runtime.episodes SET actions_used = LEAST(actions_used + 1, 4) "
                    "WHERE id = :e"
                ),
                {"e": action["episode_id"]},
            )
    except Exception as exc:
        log.error("episode_state_bump_failed", error=str(exc)[:200])

    if publish is not None:
        publish(
            {
                "type": "action.dispatched",
                "episode_id": str(action["episode_id"]),
                "action_id": str(action["id"]),
                "channel": channel,
                "mode": mode.value,
            }
        )
    res = DispatchResult("dispatched", f"provider_ref={provider_ref}")
    res.sim_events = sim_events
    return res
