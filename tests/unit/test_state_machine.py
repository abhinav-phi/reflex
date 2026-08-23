"""State machines: legal transitions, illegal raise, terminal frozen (AppFlow §14)."""

import pytest

from reflex.core.enums import ActionStatus, EpisodeStatus
from reflex.core.state_machine import (
    can_transition_action,
    can_transition_episode,
    IllegalTransition,
    StateMachineMixin,
)


def test_episode_happy_path():
    assert can_transition_episode(EpisodeStatus.WAITING_DIAGNOSIS, EpisodeStatus.DIAGNOSED)
    assert can_transition_episode(EpisodeStatus.DIAGNOSED, EpisodeStatus.SCHEDULED)
    assert can_transition_episode(EpisodeStatus.DIAGNOSED, EpisodeStatus.WAITING_APPROVAL)
    assert can_transition_episode(EpisodeStatus.SCHEDULED, EpisodeStatus.ACTED)
    assert can_transition_episode(EpisodeStatus.ACTED, EpisodeStatus.OBSERVING)
    assert can_transition_episode(EpisodeStatus.OBSERVING, EpisodeStatus.RECOVERED)


def test_observing_replan_loop():
    assert can_transition_episode(EpisodeStatus.OBSERVING, EpisodeStatus.DIAGNOSED)
    assert can_transition_episode(EpisodeStatus.DIAGNOSED, EpisodeStatus.DIAGNOSED)


def test_organic_capture_before_diagnosis():
    assert can_transition_episode(EpisodeStatus.WAITING_DIAGNOSIS, EpisodeStatus.RECOVERED)


def test_complaint_from_any_active_state():
    for st in (
        EpisodeStatus.WAITING_DIAGNOSIS, EpisodeStatus.DIAGNOSED,
        EpisodeStatus.WAITING_APPROVAL, EpisodeStatus.SCHEDULED,
        EpisodeStatus.ACTED, EpisodeStatus.OBSERVING,
    ):
        assert can_transition_episode(st, EpisodeStatus.STOPPED_CUSTOMER), st


def test_terminals_never_reopen():
    for t in EpisodeStatus.terminal():
        assert not can_transition_episode(t, EpisodeStatus.DIAGNOSED)
        assert not can_transition_episode(t, EpisodeStatus.RECOVERED)


def test_illegal_jumps_raise():
    assert not can_transition_episode(EpisodeStatus.WAITING_DIAGNOSIS, EpisodeStatus.OBSERVING)
    assert not can_transition_action(ActionStatus.PROPOSED, ActionStatus.DISPATCHED)
    assert not can_transition_action(ActionStatus.PROPOSED, ActionStatus.SUCCEEDED)

    class M(StateMachineMixin):
        pass

    m2 = M()
    m2.status = ActionStatus.PROPOSED  # type: ignore[attr-defined]
    with pytest.raises(IllegalTransition):
        m2.apply_action_transition(ActionStatus.DISPATCHED)

    m3 = M()
    m3.status = EpisodeStatus.RECOVERED  # type: ignore[attr-defined]
    with pytest.raises(IllegalTransition):
        m3.apply_episode_transition(EpisodeStatus.DIAGNOSED)


def test_blocked_is_terminal_no_retry():
    assert not can_transition_action(ActionStatus.BLOCKED, ActionStatus.SCHEDULED)
