"""AI-2 EV policy — v1 prior-frozen logistic propensity + deterministic EV math.

v1 coefficients are literature-calibrated priors (data/calibration_sources.md);
v2 is trained on replay outcomes (trainer.py) and loaded via policy_store.
The EV ARITHMETIC is deterministic product code (PRD §14: AI never does EV math).

EV = p_recover × amount − channel_cost − annoyance_penalty
annoyance_penalty = p_optout × LTV_band_value × contact_count_factor
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from reflex.brain.constants import CHANNEL_COST_PAISE, LTV_BAND_VALUE_PAISE
from reflex.core.enums import CanonicalCode, Channel, Intervention, LtvBand, Rail

POLICY_V1 = "v1"

# ---- feature vocabulary -------------------------------------------------------
AMOUNT_BANDS = ("u250", "250_500", "500_1000", "1000_5000", "g5000")
HOUR_BUCKETS = ("night", "morning", "midday", "evening")


def amount_band(amount_paise: int) -> str:
    r = amount_paise / 100
    if r < 250:
        return "u250"
    if r < 500:
        return "250_500"
    if r < 1000:
        return "500_1000"
    if r < 5000:
        return "1000_5000"
    return "g5000"


def hour_bucket(hour_ist: int) -> str:
    if hour_ist < 9:
        return "night"
    if hour_ist < 13:
        return "morning"
    if hour_ist < 18:
        return "midday"
    return "evening"


@dataclass(frozen=True)
class EpisodeFeatures:
    canonical_code: CanonicalCode
    amount_paise: int
    rail: Rail
    contact_count: int
    hour_ist: int
    day_of_month: int
    ltv_band: LtvBand
    prior_recovered: bool
    channel: Channel | None


# ---- v1 prior coefficients (frozen; explainable in the EV drawer) --------------
# Intercept per canonical code: baseline log-odds that an intervention of the
# right kind recovers this failure. Grounded in calibration_sources.md §4.
_CODE_INTERCEPT: dict[CanonicalCode, float] = {
    CanonicalCode.INSUFFICIENT_FUNDS: -1.20,
    CanonicalCode.ISSUER_DOWNTIME: -0.65,
    CanonicalCode.EXPIRED_CARD: -1.60,
    CanonicalCode.AUTH_DECLINED_SOFT: -0.80,
    CanonicalCode.AUTH_DECLINED_HARD: -2.40,
    CanonicalCode.RISK_HELD: -1.80,
    CanonicalCode.MANDATE_REVOKED: -1.50,
    CanonicalCode.MANDATE_LIMIT_BREACH: -1.10,
    CanonicalCode.INVALID_VPA: -1.70,
    CanonicalCode.CUSTOMER_INITIATED: -4.50,
    CanonicalCode.UNKNOWN_AMBIGUOUS: -1.70,
}

# Intervention/channel fit multipliers (log-odds deltas).
_INTERVENTION_FIT: dict[tuple[CanonicalCode, Intervention], float] = {
    (CanonicalCode.INSUFFICIENT_FUNDS, Intervention.WAIT): 0.55,
    (CanonicalCode.INSUFFICIENT_FUNDS, Intervention.UPI_LINK_PUSH): 0.30,
    (CanonicalCode.INSUFFICIENT_FUNDS, Intervention.RETRY_SAME_RAIL): -0.40,
    (CanonicalCode.ISSUER_DOWNTIME, Intervention.RETRY_SAME_RAIL): 0.45,
    (CanonicalCode.ISSUER_DOWNTIME, Intervention.WAIT): 0.35,
    (CanonicalCode.EXPIRED_CARD, Intervention.PAYMENT_LINK_PUSH): 0.40,
    (CanonicalCode.AUTH_DECLINED_SOFT, Intervention.RETRY_SAME_RAIL): 0.35,
    (CanonicalCode.AUTH_DECLINED_SOFT, Intervention.RETRY_ALT_RAIL): 0.25,
    (CanonicalCode.AUTH_DECLINED_HARD, Intervention.PAYMENT_LINK_PUSH): -0.20,
    (CanonicalCode.RISK_HELD, Intervention.WAIT): 0.20,
    (CanonicalCode.MANDATE_REVOKED, Intervention.MANDATE_REREG_SIM): 0.45,
    (CanonicalCode.MANDATE_REVOKED, Intervention.PAYMENT_LINK_PUSH): 0.25,
    (CanonicalCode.MANDATE_LIMIT_BREACH, Intervention.PAYMENT_LINK_PUSH): 0.40,
    (CanonicalCode.INVALID_VPA, Intervention.MANDATE_REREG_SIM): 0.35,
    (CanonicalCode.CUSTOMER_INITIATED, Intervention.STOP_LOW_EV): 0.0,
    (CanonicalCode.UNKNOWN_AMBIGUOUS, Intervention.PAYMENT_LINK_PUSH): 0.0,
}

_RAIL_FIT: dict[tuple[Rail, Intervention], float] = {
    (Rail.UPI, Intervention.UPI_LINK_PUSH): 0.25,
    (Rail.UPI, Intervention.RETRY_SAME_RAIL): 0.05,
    (Rail.NACH_EMANDATE, Intervention.RETRY_SAME_RAIL): -0.15,
    (Rail.CARD, Intervention.PAYMENT_LINK_PUSH): 0.15,
    (Rail.CARD, Intervention.RETRY_ALT_RAIL): 0.10,
}

_CHANNEL_FIT: dict[Channel | None, float] = {
    Channel.WA_SIM: 0.20,
    Channel.SMS_SIM: 0.05,
    Channel.EMAIL_SIM: -0.25,
    Channel.VOICE_SIM: 0.15,
    Channel.RAZORPAY_TM: 0.0,
    Channel.NONE: 0.0,
    None: 0.0,
}

# Contact fatigue: each prior contact within the episode reduces log-odds.
CONTACT_DECAY = -0.45
# Salary-cycle proximity bonus (INSUFFICIENT_FUNDS recovers near salary credit).
SALARY_PROXIMITY_BONUS = 0.45
PRIOR_RECOVERY_BONUS = 0.25
# p_optout base per contact (calibration §3) × fatigue factor 1.5^n.
# The EV penalty applies a risk coefficient to keep annoyance in ₹-realistic range.
P_OPTOUT_BASE = 0.012
OPTOUT_FATIGUE = 1.5
ANNOYANCE_RISK_COEFF = 0.35


def _sigmoid(z: float) -> float:
    if z < -30:
        return 0.0
    if z > 30:
        return 1.0
    return 1.0 / (1.0 + math.exp(-z))


def salary_proximity(day_of_month: int, customer_salary_day: int | None = None) -> float:
    """0..1 — closeness to a salary-credit window (days 1–7 or customer's day)."""
    target = customer_salary_day if customer_salary_day is not None else 4
    # distance to the NEXT occurrence of target day
    d = (target - day_of_month) % 30
    d = min(d, 30 - d)
    return max(0.0, 1.0 - d / 7.0)


def p_optout(contact_count: int) -> float:
    return min(0.9, P_OPTOUT_BASE * (OPTOUT_FATIGUE ** max(contact_count, 0)))


def propensity(
    feats: EpisodeFeatures,
    intervention: Intervention,
    salary_day: int | None = None,
    params: dict | None = None,
) -> float:
    """p_recover via logistic model. `params` (v2) may override coefficients."""
    z = _CODE_INTERCEPT.get(feats.canonical_code, -1.0)
    z += _INTERVENTION_FIT.get((feats.canonical_code, intervention), 0.0)
    z += _RAIL_FIT.get((feats.rail, intervention), 0.0)
    z += _CHANNEL_FIT.get(feats.channel, 0.0)
    z += CONTACT_DECAY * feats.contact_count
    if feats.canonical_code is CanonicalCode.INSUFFICIENT_FUNDS:
        z += SALARY_PROXIMITY_BONUS * salary_proximity(feats.day_of_month, salary_day)
    if feats.prior_recovered:
        z += PRIOR_RECOVERY_BONUS
    if params:
        z += float(params.get("bias_adjust", 0.0))
        for key, delta in (params.get("code_adjust") or {}).items():
            if key == feats.canonical_code.value:
                z += float(delta)
    return round(_sigmoid(z), 4)


@dataclass(frozen=True)
class EVBreakdown:
    p_recover: float
    p_optout: float
    expected_gain_paise: int
    cost_paise: int
    annoyance_paise: int
    ev_paise: int

    def as_dict(self) -> dict[str, int | float]:
        return {
            "p_recover": self.p_recover,
            "p_optout": self.p_optout,
            "expected_gain_paise": self.expected_gain_paise,
            "cost_paise": self.cost_paise,
            "annoyance_paise": self.annoyance_paise,
            "ev_paise": self.ev_paise,
        }


def compute_ev(
    *,
    p_recover: float,
    amount_paise: int,
    cost_paise: int,
    contact_count: int,
    ltv_band: LtvBand,
) -> EVBreakdown:
    """Deterministic EV arithmetic (PRD FR-006: all four terms persisted).

    EV = p_recover × amount − cost − annoyance
    annoyance = coeff × p_optout × LTV_band_value × fatigue(1 + 0.5·contacts)
    """
    expected_gain = int(round(p_recover * amount_paise))
    po = p_optout(contact_count)
    penalty = int(
        round(
            ANNOYANCE_RISK_COEFF
            * po
            * LTV_BAND_VALUE_PAISE[ltv_band]
            * (1 + 0.5 * contact_count)
        )
    )
    ev = expected_gain - cost_paise - penalty
    return EVBreakdown(
        p_recover=p_recover,
        p_optout=round(po, 4),
        expected_gain_paise=expected_gain,
        cost_paise=cost_paise,
        annoyance_paise=penalty,
        ev_paise=ev,
    )


def channel_cost(channel: Channel | None) -> int:
    return CHANNEL_COST_PAISE.get(channel, 0)
