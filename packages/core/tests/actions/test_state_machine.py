"""The allowlist mirrors transitions.json exactly; anything else raises; terminal is final."""

from __future__ import annotations

import ast
import itertools
from pathlib import Path
from typing import get_args

import neurosphere_core.actions
import pytest
from neurosphere_contracts.actions.v1.action_state import ActionState
from neurosphere_contracts.actions.v1.transitions import ActionTransitionAllowlist
from neurosphere_core.actions import (
    ALLOWED_TRANSITIONS,
    INITIAL_STATE,
    TERMINAL_STATES,
    InvalidTransitionError,
    assert_transition,
    can_transition,
    is_terminal,
)
from neurosphere_core.actions.state_machine import ACTION_STATES, allowed_targets
from neurosphere_core.errors import InvalidSchemaError

from .action_helpers import MAKER, TARGET_VERSION, Harness, load_contract

PAIRS = list(itertools.product(ACTION_STATES, ACTION_STATES))


@pytest.fixture(scope="module")
def contract() -> ActionTransitionAllowlist:
    return ActionTransitionAllowlist.model_validate(load_contract("transitions.json"))


def test_table_equals_contract_file(contract: ActionTransitionAllowlist) -> None:
    pairs = {(t.from_.root, t.to.root) for t in contract.transitions}
    assert len(pairs) == len(contract.transitions)
    assert pairs == ALLOWED_TRANSITIONS
    assert contract.initial_state.root == INITIAL_STATE
    assert {s.root for s in contract.terminal_states} == TERMINAL_STATES


def test_states_equal_the_generated_enum() -> None:
    literal = ActionState.model_fields["root"].annotation
    assert ACTION_STATES == get_args(literal)
    assert set(load_contract("action-state.schema.json")["enum"]) == set(ACTION_STATES)


@pytest.mark.parametrize(("source", "target"), PAIRS, ids=[f"{a}->{b}" for a, b in PAIRS])
def test_full_matrix(source: str, target: str) -> None:
    allowed = (source, target) in ALLOWED_TRANSITIONS
    assert can_transition(source, target) is allowed
    if allowed:
        assert_transition(source, target)
        return
    with pytest.raises(InvalidTransitionError) as caught:
        assert_transition(source, target)
    assert isinstance(caught.value, InvalidSchemaError)
    assert caught.value.code == "invalid_schema"
    assert caught.value.reason == "invalid_transition"


@pytest.mark.parametrize("state", sorted(TERMINAL_STATES))
def test_terminal_states_are_final(state: str) -> None:
    assert is_terminal(state)
    assert allowed_targets(state) == ()


def test_unknown_states_are_rejected() -> None:
    with pytest.raises(InvalidTransitionError):
        assert_transition("drafted", "approved")
    with pytest.raises(InvalidTransitionError):
        assert_transition("pending", "validated")


def test_no_self_transitions() -> None:
    assert all(a != b for a, b in ALLOWED_TRANSITIONS)


async def test_service_refuses_out_of_order_moves() -> None:
    h = Harness()
    drafted = await h.drafted()
    writes = h.store.replace_calls
    with pytest.raises(InvalidTransitionError):
        await h.service.confirm(
            drafted.key,
            MAKER,
            confirmation_hash="sha256:" + "0" * 64,
            current_target_version=TARGET_VERSION,
            requires_approval=False,
            advisory=False,
        )
    with pytest.raises(InvalidTransitionError):
        await h.service.finish_execution(drafted, outcome="failed", reason="execution_failed")
    with pytest.raises(InvalidTransitionError):
        await h.service.begin_execution(drafted.key, worker_id="worker-1")
    assert h.store.replace_calls == writes
    assert (await h.current(drafted.key)).state == "drafted"


async def test_terminal_intent_cannot_move_again() -> None:
    h = Harness()
    presented = await h.awaiting_confirmation()
    declined = await h.service.decline(presented.key, MAKER)
    assert declined.state == "failed"
    assert declined.intent.status_reason == "declined_by_actor"
    with pytest.raises(InvalidTransitionError):
        await h.service.decline(presented.key, MAKER)
    with pytest.raises(InvalidTransitionError):
        await h.confirm(presented)
    with pytest.raises(InvalidTransitionError):
        await h.service.record_validation(presented.key, MAKER, [])
    assert await h.service.expire_due(now=h.clock.now.replace(year=2030)) == []
    assert (await h.current(presented.key)).state == "failed"


def test_actions_package_is_connector_agnostic() -> None:
    package = Path(neurosphere_core.actions.__file__).parent
    forbidden = {"neurosphere_connector", "neurosphere_api", "neurosphere_workers"}
    offenders: dict[str, list[str]] = {}
    for path in sorted(package.rglob("*.py")):
        roots: set[str] = set()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                roots.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                roots.add(node.module.split(".")[0])
        if roots & forbidden:
            offenders[path.name] = sorted(roots & forbidden)
    assert not offenders, offenders
