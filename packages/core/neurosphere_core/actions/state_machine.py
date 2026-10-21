"""The ActionIntent state machine: an explicit allowlist, never coerced.

Source of truth: ``packages/contracts/schemas/actions/v1/transitions.json`` (PRP-01). The JSON
files are not shipped with the runtime package, so the table is mirrored here verbatim and
``packages/core/tests/actions/test_state_machine.py`` asserts it equals the contract file pair for
pair (plus the initial and terminal states). Any pair not listed is forbidden, including
self-transitions and every move out of a terminal state.
"""

from __future__ import annotations

from typing import Final, Literal, get_args

from neurosphere_core.actions.errors import InvalidTransitionError

__all__ = [
    "ACTION_STATES",
    "ALLOWED_TRANSITIONS",
    "CONFIRMATION_BOUND_STATES",
    "INITIAL_STATE",
    "TERMINAL_STATES",
    "ActionStateName",
    "TerminalStateName",
    "allowed_targets",
    "assert_transition",
    "can_transition",
    "is_terminal",
]

ActionStateName = Literal[
    "drafted",
    "validated",
    "awaiting_confirmation",
    "awaiting_approval",
    "executing",
    "succeeded",
    "failed",
    "rolled_back",
    "expired",
]
TerminalStateName = Literal["succeeded", "failed", "rolled_back", "expired"]

ACTION_STATES: Final[tuple[str, ...]] = get_args(ActionStateName)
INITIAL_STATE: Final = "drafted"
TERMINAL_STATES: Final[frozenset[str]] = frozenset(get_args(TerminalStateName))

ALLOWED_TRANSITIONS: Final[frozenset[tuple[str, str]]] = frozenset(
    {
        ("drafted", "validated"),
        ("drafted", "failed"),
        ("drafted", "expired"),
        ("validated", "awaiting_confirmation"),
        ("validated", "failed"),
        ("validated", "expired"),
        ("awaiting_confirmation", "awaiting_approval"),
        ("awaiting_confirmation", "executing"),
        ("awaiting_confirmation", "failed"),
        ("awaiting_confirmation", "expired"),
        ("awaiting_approval", "executing"),
        ("awaiting_approval", "failed"),
        ("awaiting_approval", "expired"),
        ("executing", "succeeded"),
        ("executing", "failed"),
        ("executing", "rolled_back"),
    }
)

#: States in which ``confirmation_hash`` and ``confirmation_expires_at`` must be set (contract
#: allOf branch 1). ``failed`` and ``expired`` can be reached before confirmation.
CONFIRMATION_BOUND_STATES: Final[frozenset[str]] = frozenset(
    {"awaiting_confirmation", "awaiting_approval", "executing", "succeeded", "rolled_back"}
)


def is_terminal(state: str) -> bool:
    return state in TERMINAL_STATES


def can_transition(from_state: str, to_state: str) -> bool:
    return (from_state, to_state) in ALLOWED_TRANSITIONS


def assert_transition(from_state: str, to_state: str) -> None:
    """Raise :class:`InvalidTransitionError` (reason ``invalid_transition``) unless allowlisted."""
    if not can_transition(from_state, to_state):
        raise InvalidTransitionError(from_state, to_state)


def allowed_targets(from_state: str) -> tuple[str, ...]:
    """Legal next states from ``from_state`` in contract enum order (empty for terminal states)."""
    return tuple(s for s in ACTION_STATES if (from_state, s) in ALLOWED_TRANSITIONS)
