"""Episode & Action state machines (AppFlow §14).

Single source of truth for legal transitions. The DB triggers in the Alembic
baseline mirror this map as a safety net; all code must transition through
`EpisodeStateMachine.transition` / `ActionStateMachine.transition`.
"""

from __future__ import annotations

from reflex.core.enums import ActionStatus, EpisodeStatus

EPISODE_TRANSITIONS: dict[EpisodeStatus, frozenset[EpisodeStatus]] = {
    EpisodeStatus.WAITING_DIAGNOSIS: frozenset(
        {EpisodeStatus.DIAGNOSED, EpisodeStatus.HALTED, EpisodeStatus.EXPIRED}
    ),
    EpisodeStatus.DIAGNOSED: frozenset(
        {
            EpisodeStatus.WAITING_APPROVAL,
            EpisodeStatus.SCHEDULED,
            EpisodeStatus.DIAGNOSED,  # re-plan loop (OBSERVING → DIAGNOSED lands here too)
            EpisodeStatus.STOPPED_LOW_EV,
            EpisodeStatus.EXPIRED,
            EpisodeStatus.HALTED,
        }
    ),
    EpisodeStatus.WAITING_APPROVAL: frozenset(
        {
            EpisodeStatus.SCHEDULED,
            EpisodeStatus.STOPPED_APPROVAL_DECLINED,
            EpisodeStatus.EXPIRED,
            EpisodeStatus.HALTED,
        }
    ),
    EpisodeStatus.SCHEDULED: frozenset(
        {EpisodeStatus.ACTED, EpisodeStatus.HALTED, EpisodeStatus.EXPIRED}
    ),
    EpisodeStatus.ACTED: frozenset({EpisodeStatus.OBSERVING, EpisodeStatus.HALTED, EpisodeStatus.EXPIRED}),
    EpisodeStatus.OBSERVING: frozenset(
        {
            EpisodeStatus.RECOVERED,
            EpisodeStatus.DIAGNOSED,  # fail → re-plan (caps permitting)
            EpisodeStatus.STOPPED_CAP,
            EpisodeStatus.STOPPED_LOW_EV,
            EpisodeStatus.STOPPED_CUSTOMER,
            EpisodeStatus.ESCALATED,
            EpisodeStatus.EXPIRED,
            EpisodeStatus.HALTED,
        }
    ),
}

ACTION_TRANSITIONS: dict[ActionStatus, frozenset[ActionStatus]] = {
    ActionStatus.PROPOSED: frozenset(
        {
            ActionStatus.SHIELD_PASS,
            ActionStatus.BLOCKED,
            ActionStatus.WAITING_APPROVAL,
            ActionStatus.CANCELLED_HALT,
        }
    ),
    ActionStatus.SHIELD_PASS: frozenset(
        {
            ActionStatus.SCHEDULED,
            ActionStatus.WAITING_APPROVAL,
            ActionStatus.BLOCKED,
            ActionStatus.CANCELLED_HALT,
            ActionStatus.SUPERSEDED,
        }
    ),
    ActionStatus.WAITING_APPROVAL: frozenset(
        {
            ActionStatus.SCHEDULED,
            ActionStatus.BLOCKED,  # decline/timeout ⇒ branch closed (fail-closed)
            ActionStatus.CANCELLED_HALT,
            ActionStatus.SUPERSEDED,
        }
    ),
    ActionStatus.SCHEDULED: frozenset(
        {ActionStatus.DISPATCHED, ActionStatus.PARKED, ActionStatus.CANCELLED_HALT, ActionStatus.SUPERSEDED}
    ),
    ActionStatus.DISPATCHED: frozenset(
        {ActionStatus.DELIVERED_SIM, ActionStatus.PARKED, ActionStatus.FAILED}
    ),
    ActionStatus.DELIVERED_SIM: frozenset({ActionStatus.OBSERVED, ActionStatus.PARKED}),
    ActionStatus.OBSERVED: frozenset({ActionStatus.SUCCEEDED, ActionStatus.FAILED}),
    ActionStatus.PARKED: frozenset({ActionStatus.SCHEDULED, ActionStatus.CANCELLED_HALT}),
}

_TERMINAL_EPISODE = EpisodeStatus.terminal()
_TERMINAL_ACTION = ActionStatus.terminal()


class IllegalTransition(Exception):
    def __init__(self, kind: str, src: str, dst: str) -> None:
        super().__init__(f"{kind}: illegal transition {src} -> {dst}")
        self.kind = kind
        self.src = src
        self.dst = dst


def can_transition_episode(src: EpisodeStatus, dst: EpisodeStatus) -> bool:
    if src == dst:
        return src == EpisodeStatus.DIAGNOSED  # only diagnosed self-loops (re-plan)
    if src in _TERMINAL_EPISODE:
        return False
    return dst in EPISODE_TRANSITIONS.get(src, frozenset())


def can_transition_action(src: ActionStatus, dst: ActionStatus) -> bool:
    if src == dst:
        return False
    if src in _TERMINAL_ACTION:
        return False
    return dst in ACTION_TRANSITIONS.get(src, frozenset())


class StateMachineMixin:
    """Applies a transition to an ORM instance with `.status`, raising on illegal moves."""

    status: object

    def apply_episode_transition(self, dst: EpisodeStatus) -> None:
        src = EpisodeStatus(self.status)  # type: ignore[arg-type]
        if not can_transition_episode(src, dst):
            raise IllegalTransition("episode", src, dst)
        self.status = dst  # type: ignore[assignment]

    def apply_action_transition(self, dst: ActionStatus) -> None:
        src = ActionStatus(self.status)  # type: ignore[arg-type]
        if not can_transition_action(src, dst):
            raise IllegalTransition("action", src, dst)
        self.status = dst  # type: ignore[assignment]
