"""Shield — deterministic guardrails (PRD FR-007, Rules §3.4).

ISOLATION CONTRACT (TechSpec §6): this package imports ONLY stdlib + reflex.core.
No network access, no LLM dependency, no Brain import — enforced by
tests/security/test_shield_isolation.py and the import-lint rule.

Nothing dispatches without a Shield PASS. Fail-closed: any exception inside
evaluation surfaces as BLOCKED(reason="INTERNAL_ERROR"), never PASS.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from reflex.core.clock import in_quiet_hours
from reflex.core.enums import Channel, Intervention, Mode

# Hard bounds (PRD §15 / Rules §3.4) — non-overridable ceilings; merchant cfg may
# only TIGHTEN them (lower caps/budget), never exceed them.
HARD_MAX_ACTIONS_PER_EPISODE = 4
HARD_MAX_CONTACTS_PER_CUSTOMER_PER_DAY = 2
HARD_DAILY_BUDGET_PAISE = 500_000

PAUSE_CANCEL_CLASS: frozenset[Intervention] = frozenset(
    {
        # Any action that could alter mandate/subscription lifecycle always
        # requires human approval (Rules §3.4 "pause/cancel-class ⇒ approval").
        # MVP executors send messages/links only, but MANDATE_REREG_SIM touches
        # mandate state and stays gated by design.
        Intervention.MANDATE_REREG_SIM,
    }
)

CONTACT_CHANNELS: frozenset[Channel | None] = frozenset(
    {Channel.WA_SIM, Channel.SMS_SIM, Channel.EMAIL_SIM, Channel.VOICE_SIM}
)


def _clamp_int(value: Any, lo: int, hi: int, default: int) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(n, hi))


@dataclass(frozen=True)
class MerchantGuardrails:
    caps_per_episode: int = 4
    contacts_per_day: int = 2
    budget_paise_daily: int = HARD_DAILY_BUDGET_PAISE
    approval_threshold_paise: int = 5_000_000

    @staticmethod
    def from_merchant_cfg(cfg: dict[str, Any]) -> "MerchantGuardrails":
        """Merchant config may tighten but never exceed hard bounds."""
        return MerchantGuardrails(
            caps_per_episode=_clamp_int(cfg.get("caps_per_episode", 4), 1, HARD_MAX_ACTIONS_PER_EPISODE, 4),
            contacts_per_day=_clamp_int(
                cfg.get("contacts_per_day", 2), 1, HARD_MAX_CONTACTS_PER_CUSTOMER_PER_DAY, 2
            ),
            budget_paise_daily=min(
                _clamp_int(cfg.get("budget_paise_daily", HARD_DAILY_BUDGET_PAISE), 0, 10**12, HARD_DAILY_BUDGET_PAISE),
                HARD_DAILY_BUDGET_PAISE,
            ),
            approval_threshold_paise=_clamp_int(
                cfg.get("approval_threshold_paise", 5_000_000), 0, 10**12, 5_000_000
            ),
        )


@dataclass(frozen=True)
class ActionProposal:
    intervention: Intervention
    channel: Channel | None
    amount_paise: int
    cost_paise: int


@dataclass(frozen=True)
class EpisodeState:
    episode_id: str
    actions_used: int
    customer_id: str
    contacts_today: int
    suppressed: bool
    dnd_flag: bool


@dataclass(frozen=True)
class ShieldInput:
    proposal: ActionProposal
    episode: EpisodeState
    mode: Mode
    guardrails: MerchantGuardrails
    budget_spent_today_paise: int
    now_sim: datetime


@dataclass(frozen=True)
class ShieldDecision:
    outcome: str  # PASS | BLOCKED | APPROVAL
    reason: str
    checks: list[dict[str, Any]] = field(default_factory=list)
    _snapshot_ctx: dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.outcome == "PASS"

    @property
    def needs_approval(self) -> bool:
        return self.outcome == "APPROVAL"

    def snapshot(self) -> dict[str, Any]:
        """Frozen evidence of what Shield saw (persisted on actions.guardrail_snapshot)."""
        return dict(self._snapshot_ctx)


def evaluate(inp: ShieldInput) -> ShieldDecision:
    """Run all checks in fixed order (AppFlow §5 step 4); fail-closed."""
    checks: list[dict[str, Any]] = []
    ctx: dict[str, Any] = {
        "mode": inp.mode.value,
        "caps": f"{inp.episode.actions_used}/{inp.guardrails.caps_per_episode}",
        "contacts_today": f"{inp.episode.contacts_today}/{inp.guardrails.contacts_per_day}",
        "budget_spent_today_paise": inp.budget_spent_today_paise,
        "quiet_hours_clear": not in_quiet_hours(inp.now_sim),
        "now_sim": inp.now_sim.isoformat(),
        "suppressed": inp.episode.suppressed,
        "dnd": inp.episode.dnd_flag,
    }

    def record(name: str, ok: bool, detail: str) -> None:
        checks.append({"check": name, "ok": ok, "detail": detail})

    try:
        # Fixed order per AppFlow §5: kill switch → mode → cap → contacts/day →
        # quiet hours → budget → suppression → value/approval triggers.
        if inp.mode is Mode.HALTED:
            record("kill_switch", False, "system halted")
            ctx["outcome_reason"] = "HALTED"
            return ShieldDecision("BLOCKED", "HALTED", checks, ctx)

        # Terminal bookkeeping actions carry no contact and no cost.
        if inp.proposal.intervention in (Intervention.STOP_LOW_EV, Intervention.WAIT):
            if inp.proposal.channel in (None, Channel.NONE):
                record("non_contact_action", True, inp.proposal.intervention.value)
                return ShieldDecision("PASS", inp.proposal.intervention.value.lower(), checks, ctx)

        if inp.episode.actions_used >= inp.guardrails.caps_per_episode:
            record("episode_cap", False, ctx["caps"])
            ctx["outcome_reason"] = "EPISODE_CAP"
            return ShieldDecision("BLOCKED", "EPISODE_CAP", checks, ctx)
        record("episode_cap", True, ctx["caps"])

        if inp.episode.contacts_today >= inp.guardrails.contacts_per_day:
            record("contacts_per_day", False, ctx["contacts_today"])
            ctx["outcome_reason"] = "CONTACTS_PER_DAY"
            return ShieldDecision("BLOCKED", "CONTACTS_PER_DAY", checks, ctx)
        record("contacts_per_day", True, ctx["contacts_today"])

        is_contact = inp.proposal.channel in CONTACT_CHANNELS
        quiet = in_quiet_hours(inp.now_sim)
        if is_contact and quiet:
            record("quiet_hours", False, ctx["now_sim"])
            ctx["outcome_reason"] = "QUIET_HOURS"
            return ShieldDecision("BLOCKED", "QUIET_HOURS", checks, ctx)
        record("quiet_hours", True, "clear" if not quiet else "clear for non-contact action")

        projected = inp.budget_spent_today_paise + inp.proposal.cost_paise
        if projected > inp.guardrails.budget_paise_daily:
            record("daily_budget", False, f"{projected}>{inp.guardrails.budget_paise_daily}")
            ctx["outcome_reason"] = "BUDGET_EXHAUSTED"
            return ShieldDecision("BLOCKED", "BUDGET_EXHAUSTED", checks, ctx)
        record("daily_budget", True, f"{projected}<={inp.guardrails.budget_paise_daily}")

        if inp.episode.suppressed:
            record("suppression_list", False, "customer globally suppressed")
            ctx["outcome_reason"] = "SUPPRESSED"
            return ShieldDecision("BLOCKED", "SUPPRESSED", checks, ctx)
        record("suppression_list", True, "clear")

        if inp.episode.dnd_flag:
            record("dnd_flag", False, "customer DND pre-seeded")
            ctx["outcome_reason"] = "DND"
            return ShieldDecision("BLOCKED", "DND", checks, ctx)
        record("dnd_flag", True, "clear")

        # Value > threshold ⇒ approval gate; pause/cancel-class ⇒ approval ALWAYS.
        high_value = inp.proposal.amount_paise > inp.guardrails.approval_threshold_paise
        pause_class = inp.proposal.intervention in PAUSE_CANCEL_CLASS
        if high_value or pause_class:
            reason = "HIGH_VALUE" if high_value else "PAUSE_CANCEL_CLASS"
            record("approval_trigger", False, reason)
            ctx["outcome_reason"] = reason
            return ShieldDecision("APPROVAL", reason, checks, ctx)
        record("approval_trigger", True, "not required")

        ctx["outcome_reason"] = "PASS"
        return ShieldDecision("PASS", "all checks passed", checks, ctx)

    except Exception as exc:  # fail-closed: any internal error blocks, never passes
        record("internal_error", False, type(exc).__name__)
        ctx["outcome_reason"] = "INTERNAL_ERROR"
        return ShieldDecision("BLOCKED", "INTERNAL_ERROR", checks, ctx)
