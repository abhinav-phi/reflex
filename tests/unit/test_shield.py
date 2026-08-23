"""Shield adversarial suite (Rules §11.3): table-driven, at-limit boundaries."""

from datetime import datetime, timezone

import pytest

from reflex.core.enums import Channel, Intervention, Mode
from reflex.shield.guardrails import (
    ActionProposal,
    EpisodeState,
    MerchantGuardrails,
    ShieldInput,
    evaluate,
)


def now(h: int, m: int = 0, s: int = 0) -> datetime:
    # 2026-08-28 is a Friday; hour in IST via +05:30 offset — use plain IST clock
    from datetime import timedelta

    utc = datetime(2026, 8, 28, h, m, s, tzinfo=timezone.utc)
    return utc - timedelta(hours=5, minutes=30)  # convert IST wall-clock to UTC


def make(**kw) -> ShieldInput:
    defaults = dict(
        proposal=ActionProposal(Intervention.UPI_LINK_PUSH, Channel.WA_SIM, 29_900, 80),
        episode=EpisodeState("e1", actions_used=0, customer_id="c1", contacts_today=0,
                             suppressed=False, dnd_flag=False),
        mode=Mode.AUTONOMOUS,
        guardrails=MerchantGuardrails(),
        budget_spent_today_paise=0,
        now_sim=now(14),
    )
    defaults.update(kw)
    return ShieldInput(**defaults)


def contact(channel=Channel.WA_SIM, intervention=Intervention.UPI_LINK_PUSH):
    return ActionProposal(intervention, channel, 29_900, 80)


def test_pass_happy_path():
    d = evaluate(make())
    assert d.passed and not d.needs_approval


def test_kill_switch_blocks_everything():
    for prop in (contact(), ActionProposal(Intervention.WAIT, None, 29_900, 0)):
        d = evaluate(make(proposal=prop, mode=Mode.HALTED))
        assert not d.passed and d.reason == "HALTED"


def test_cap_exactly_at_limit_blocked():
    d = evaluate(make(episode=EpisodeState("e1", 4, "c1", 0, False, False)))
    assert d.outcome == "BLOCKED" and d.reason == "EPISODE_CAP"
    ok = evaluate(make(episode=EpisodeState("e1", 3, "c1", 0, False, False)))
    assert ok.passed


def test_contacts_exactly_at_limit_blocked():
    d = evaluate(make(episode=EpisodeState("e1", 0, "c1", 2, False, False)))
    assert d.outcome == "BLOCKED" and d.reason == "CONTACTS_PER_DAY"
    ok = evaluate(make(episode=EpisodeState("e1", 0, "c1", 1, False, False)))
    assert ok.passed


@pytest.mark.parametrize(
    "h,m,s,expect_quiet",
    [(21, 0, 0, True), (20, 59, 59, False), (8, 59, 59, True), (9, 0, 0, False), (3, 15, 0, True)],
)
def test_quiet_hours_boundaries(h, m, s, expect_quiet):
    d = evaluate(make(now_sim=now(h, m, s)))
    if expect_quiet:
        assert d.outcome == "BLOCKED" and d.reason == "QUIET_HOURS"
    else:
        assert d.passed


def test_non_contact_action_allowed_in_quiet_hours():
    d = evaluate(make(proposal=ActionProposal(Intervention.WAIT, None, 29_900, 0),
                      now_sim=now(23)))
    assert d.passed


def test_budget_exact_boundary():
    # spend 499,920 + cost 80 = exactly 500,000 ⇒ allowed; one more paise blocked
    d = evaluate(make(budget_spent_today_paise=499_920))
    assert d.passed
    d2 = evaluate(make(budget_spent_today_paise=499_921))
    assert d2.outcome == "BLOCKED" and d2.reason == "BUDGET_EXHAUSTED"


def test_suppressed_and_dnd_block():
    d = evaluate(make(episode=EpisodeState("e1", 0, "c1", 0, True, False)))
    assert d.reason == "SUPPRESSED"
    d2 = evaluate(make(episode=EpisodeState("e1", 0, "c1", 0, False, True)))
    assert d2.reason == "DND"


def test_high_value_routes_to_approval():
    d = evaluate(make(proposal=ActionProposal(
        Intervention.PAYMENT_LINK_PUSH, Channel.WA_SIM, 5_000_001, 80)))
    assert d.needs_approval and d.reason == "HIGH_VALUE"


def test_pause_cancel_class_always_approval():
    d = evaluate(make(proposal=ActionProposal(
        Intervention.MANDATE_REREG_SIM, Channel.WA_SIM, 29_900, 80)))
    assert d.needs_approval and d.reason == "PAUSE_CANCEL_CLASS"


def test_merchant_cfg_cannot_loosen_hard_bounds():
    g = MerchantGuardrails.from_merchant_cfg({
        "caps_per_episode": 99, "contacts_per_day": 50,
        "budget_paise_daily": 10**9, "approval_threshold_paise": 100,
    })
    assert g.caps_per_episode <= 4 and g.contacts_per_day <= 2
    assert g.budget_paise_daily <= 500_000


def test_internal_error_fails_closed():
    bad = make()
    object.__setattr__(bad, "guardrails", None)  # type: ignore[arg-type]
    d = evaluate(bad)
    assert d.outcome == "BLOCKED" and d.reason == "INTERNAL_ERROR"


def test_snapshot_freezes_context():
    d = evaluate(make())
    snap = d.snapshot()
    assert snap["mode"] == "autonomous" and "now_sim" in snap and "caps" in snap
