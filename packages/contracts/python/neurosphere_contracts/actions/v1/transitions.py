# GENERATED - do not edit.
# Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
# Regenerate: python packages/contracts/scripts/generate.py
# Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
# pyright: reportAssignmentType=false, reportInvalidTypeForm=false

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictStr

from . import action_state


class Transition(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    from_: Annotated[action_state.ActionState, Field(alias="from")]
    to: action_state.ActionState
    guard: Annotated[StrictStr, Field(max_length=512, min_length=1)]
    """
    Human-readable condition under which the executor may take this transition.
    """


class ActionTransitionAllowlist(BaseModel):
    """
    Shape of ./transitions.json: the allowlist of legal ActionState (from, to) pairs (Clarification 11). Any pair not listed is forbidden, including self-transitions and every move out of a terminal state; there is no deny list. PRP-17 enforces from this data. Rules JSON Schema cannot express are checked by `validate_transition_allowlist` in tests/contracts/test_action_transitions.py: (from, to) pairs are unique, no pair has from == to, no pair starts at a terminal state, initial_state is not terminal, and every non-terminal state is reachable from initial_state and can reach a terminal state.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    schema_version: Annotated[StrictStr, Field(pattern="^1\\.[0-9]+\\.[0-9]+$")]
    state_machine: Literal["action_intent"]
    """
    Which state machine this allowlist governs.
    """
    initial_state: action_state.ActionState
    terminal_states: Annotated[list[action_state.ActionState], Field(min_length=1)]
    transitions: Annotated[list[Transition], Field(min_length=1)]
