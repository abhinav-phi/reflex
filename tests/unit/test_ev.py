"""EV math + propensity sanity (FR-006 four-term breakdown)."""

from reflex.brain.ev import (
    EpisodeFeatures,
    channel_cost,
    compute_ev,
    p_optout,
    propensity,
)
from reflex.core.enums import CanonicalCode, Channel, Intervention, LtvBand, Rail


def feats(**kw):
    base = dict(
        canonical_code=CanonicalCode.INSUFFICIENT_FUNDS, amount_paise=29_900,
        rail=Rail.UPI, contact_count=0, hour_ist=16, day_of_month=28,
        ltv_band=LtvBand.MID, prior_recovered=False, channel=Channel.WA_SIM,
    )
    base.update(kw)
    return EpisodeFeatures(**base)


def test_ev_four_terms_and_negative_stop():
    ev = compute_ev(p_recover=0.34, amount_paise=299_00, cost_paise=80,
                    contact_count=0, ltv_band=LtvBand.MID)
    assert ev.expected_gain_paise == round(0.34 * 29900)
    assert ev.cost_paise == 80
    assert ev.annoyance_paise > 0
    assert ev.ev_paise == ev.expected_gain_paise - 80 - ev.annoyance_paise

    tiny = compute_ev(p_recover=0.001, amount_paise=5_000, cost_paise=400,
                      contact_count=3, ltv_band=LtvBand.HIGH)
    assert tiny.ev_paise < 0  # negative EV ⇒ STOP by design


def test_propensity_bounds_and_fatigue():
    p0 = propensity(feats(), Intervention.UPI_LINK_PUSH, salary_day=4)
    assert 0.0 < p0 < 1.0
    p_more = propensity(feats(contact_count=2), Intervention.UPI_LINK_PUSH, salary_day=4)
    assert p_more < p0  # contact decay reduces propensity
    assert p_optout(3) > p_optout(0)


def test_customer_initiated_is_never_actionable():
    # STOP candidate exists; propensity for real interventions is rock-bottom
    p = propensity(feats(canonical_code=CanonicalCode.CUSTOMER_INITIATED),
                   Intervention.PAYMENT_LINK_PUSH)
    assert p < 0.02


def test_channel_costs_documented():
    assert channel_cost(Channel.WA_SIM) == 80
    assert channel_cost(Channel.SMS_SIM) == 18
    assert channel_cost(None) == 0
