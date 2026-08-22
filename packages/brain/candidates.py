"""Candidate intervention enumeration per diagnosis (horizon-1 planner, ADR-002).

The Brain proposes; Shield disposes. Candidates are pure data — execution
decisions happen only after Shield PASS.
"""

from __future__ import annotations

from dataclasses import dataclass

from reflex.core.enums import CanonicalCode, Channel, Intervention, Rail


@dataclass(frozen=True)
class CandidateSpec:
    intervention: Intervention
    channel: Channel | None


# Plausible intervention set per canonical root cause. CUSTOMER_INITIATED maps
# only to STOP: a customer who cancelled their mandate is never re-contacted
# (product rule; also the ethically-mandated losing cohort driver).
_CANDIDATES: dict[CanonicalCode, tuple[CandidateSpec, ...]] = {
    CanonicalCode.INSUFFICIENT_FUNDS: (
        CandidateSpec(Intervention.WAIT, None),  # time-shifted re-attempt at optimal hour
        CandidateSpec(Intervention.UPI_LINK_PUSH, Channel.WA_SIM),
        CandidateSpec(Intervention.UPI_LINK_PUSH, Channel.SMS_SIM),
        CandidateSpec(Intervention.RETRY_SAME_RAIL, Channel.RAZORPAY_TM),
        CandidateSpec(Intervention.PAYMENT_LINK_PUSH, Channel.WA_SIM),
    ),
    CanonicalCode.ISSUER_DOWNTIME: (
        CandidateSpec(Intervention.WAIT, None),
        CandidateSpec(Intervention.RETRY_SAME_RAIL, Channel.RAZORPAY_TM),
        CandidateSpec(Intervention.RETRY_ALT_RAIL, Channel.RAZORPAY_TM),
    ),
    CanonicalCode.EXPIRED_CARD: (
        CandidateSpec(Intervention.PAYMENT_LINK_PUSH, Channel.WA_SIM),
        CandidateSpec(Intervention.PAYMENT_LINK_PUSH, Channel.SMS_SIM),
        CandidateSpec(Intervention.PAYMENT_LINK_PUSH, Channel.EMAIL_SIM),
        CandidateSpec(Intervention.MANDATE_REREG_SIM, Channel.WA_SIM),
    ),
    CanonicalCode.AUTH_DECLINED_SOFT: (
        CandidateSpec(Intervention.RETRY_SAME_RAIL, Channel.RAZORPAY_TM),
        CandidateSpec(Intervention.RETRY_ALT_RAIL, Channel.RAZORPAY_TM),
        CandidateSpec(Intervention.PAYMENT_LINK_PUSH, Channel.WA_SIM),
    ),
    CanonicalCode.AUTH_DECLINED_HARD: (
        CandidateSpec(Intervention.PAYMENT_LINK_PUSH, Channel.WA_SIM),
        CandidateSpec(Intervention.RETRY_ALT_RAIL, Channel.RAZORPAY_TM),
    ),
    CanonicalCode.RISK_HELD: (
        CandidateSpec(Intervention.WAIT, None),
        CandidateSpec(Intervention.PAYMENT_LINK_PUSH, Channel.WA_SIM),
    ),
    CanonicalCode.MANDATE_REVOKED: (
        CandidateSpec(Intervention.MANDATE_REREG_SIM, Channel.WA_SIM),
        CandidateSpec(Intervention.MANDATE_REREG_SIM, Channel.EMAIL_SIM),
        CandidateSpec(Intervention.PAYMENT_LINK_PUSH, Channel.WA_SIM),
        CandidateSpec(Intervention.VOICE_CALL_SIM, Channel.VOICE_SIM),
    ),
    CanonicalCode.MANDATE_LIMIT_BREACH: (
        CandidateSpec(Intervention.PAYMENT_LINK_PUSH, Channel.WA_SIM),
        CandidateSpec(Intervention.PAYMENT_LINK_PUSH, Channel.SMS_SIM),
    ),
    CanonicalCode.INVALID_VPA: (
        CandidateSpec(Intervention.MANDATE_REREG_SIM, Channel.WA_SIM),
        CandidateSpec(Intervention.PAYMENT_LINK_PUSH, Channel.SMS_SIM),
    ),
    CanonicalCode.CUSTOMER_INITIATED: (
        CandidateSpec(Intervention.STOP_LOW_EV, None),
    ),
    CanonicalCode.UNKNOWN_AMBIGUOUS: (
        CandidateSpec(Intervention.WAIT, None),
        CandidateSpec(Intervention.PAYMENT_LINK_PUSH, Channel.SMS_SIM),
    ),
}

# Rail-aware alternates for RETRY_ALT_RAIL.
_ALT_RAIL: dict[Rail, Rail] = {
    Rail.UPI: Rail.CARD,
    Rail.CARD: Rail.UPI,
    Rail.NETBANKING: Rail.UPI,
    Rail.WALLET: Rail.UPI,
    Rail.NACH_EMANDATE: Rail.CARD,
}


def enumerate_candidates(code: CanonicalCode) -> tuple[CandidateSpec, ...]:
    return _CANDIDATES.get(code, _CANDIDATES[CanonicalCode.UNKNOWN_AMBIGUOUS])


def alt_rail(rail: Rail) -> Rail:
    return _ALT_RAIL.get(rail, Rail.UPI)


def intervention_label(intervention: Intervention, scheduled_hour_ist: int | None, rail: Rail) -> str:
    """Human label used in the UI stream/drawers (AppFlow §5 examples)."""
    base = intervention.value
    if intervention is Intervention.WAIT:
        return f"WAIT_TO_{(scheduled_hour_ist or 16):02d}:00_THEN_REATTEMPT"
    if intervention is Intervention.UPI_LINK_PUSH:
        return "UPI_LINK_PUSH"
    if intervention is Intervention.RETRY_ALT_RAIL:
        return f"RETRY_ALT_{alt_rail(rail).value.upper()}"
    return base
