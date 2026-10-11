"""Action state machine, confirmation hash and maker-checker rules (PRP-01 item 3 / 7).

The allowlist in actions/v1/transitions.json is the only source of legal moves. The full
9x9 matrix is enumerated: listed pairs are allowed, every other pair (self-loops, moves out
of terminal states, skips such as drafted -> executing) is rejected by
``validate_state_transition``.
"""

from __future__ import annotations

import copy
import itertools
from typing import Any

import pytest
from contract_support import SCHEMA_ROOT, jcs, load_json, load_schema, schema_errors, valid_cases
from validators import (
    ACTION_STATES,
    allowed_transitions,
    confirmation_hash,
    validate_confirmation_hash,
    validate_intent_timestamps,
    validate_maker_checker_separation,
    validate_state_transition,
    validate_transition_allowlist,
)

TRANSITIONS_SCHEMA = "actions/v1/transitions.schema.json"
INTENT = "actions/v1/action-intent.schema.json"
REVIEW_STATES = (
    "pending",
    "assigned",
    "approved",
    "rejected",
    "expired",
    "escalated",
    "executed",
    "failed",
)

EXPECTED_PAIRS = {
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


def test_state_enum_is_the_prp_list() -> None:
    assert tuple(load_schema("actions/v1/action-state.schema.json")["enum"]) == ACTION_STATES


def test_review_item_states_are_separate_ns04_enum() -> None:
    review = load_schema("actions/v1/review-item-state.schema.json")["enum"]
    assert tuple(review) == REVIEW_STATES
    assert set(review) != set(ACTION_STATES)


def test_transitions_file_matches_its_schema(transitions: dict[str, Any]) -> None:
    assert schema_errors(TRANSITIONS_SCHEMA, transitions) == []


def test_transitions_file_is_a_sound_allowlist(transitions: dict[str, Any]) -> None:
    assert validate_transition_allowlist(transitions) == []
    assert transitions["initial_state"] == "drafted"
    assert set(transitions["terminal_states"]) == {"succeeded", "failed", "rolled_back", "expired"}


def test_allowlist_is_exactly_the_reviewed_pairs(transitions: dict[str, Any]) -> None:
    assert allowed_transitions(transitions) == EXPECTED_PAIRS


MATRIX = list(itertools.product(ACTION_STATES, repeat=2))


@pytest.mark.parametrize(("source", "target"), MATRIX, ids=[f"{a}->{b}" for a, b in MATRIX])
def test_full_matrix(source: str, target: str, transitions: dict[str, Any]) -> None:
    problems = validate_state_transition(source, target, transitions)
    if (source, target) in EXPECTED_PAIRS:
        assert problems == []
    else:
        assert problems, f"{source} -> {target} must be rejected"


def test_matrix_size_and_named_rejections(transitions: dict[str, Any]) -> None:
    assert len(MATRIX) == 81
    rejected = [(a, b) for a, b in MATRIX if validate_state_transition(a, b, transitions)]
    assert len(rejected) == 81 - len(EXPECTED_PAIRS)
    for pair in [
        ("drafted", "executing"),
        ("succeeded", "executing"),
        ("expired", "awaiting_approval"),
    ]:
        assert pair in rejected
    assert validate_state_transition("drafted", "cancelled", transitions)


@pytest.mark.parametrize(
    ("mutation", "fragment"),
    [
        (lambda t: t["transitions"].append(copy.deepcopy(t["transitions"][0])), "duplicate"),
        (
            lambda t: t["transitions"].append({"from": "drafted", "to": "drafted", "guard": "x"}),
            "self-transition",
        ),
        (
            lambda t: t["transitions"].append(
                {"from": "succeeded", "to": "executing", "guard": "x"}
            ),
            "terminal",
        ),
        (lambda t: t.update(initial_state="expired"), "initial_state"),
        (
            lambda t: t.update(
                transitions=[x for x in t["transitions"] if x["to"] != "awaiting_approval"]
            ),
            "unreachable",
        ),
        (
            lambda t: t.update(
                transitions=[x for x in t["transitions"] if x["from"] != "executing"]
            ),
            "cannot reach a terminal",
        ),
    ],
    ids=[
        "duplicate",
        "self-loop",
        "out-of-terminal",
        "terminal-initial",
        "unreachable",
        "dead-end",
    ],
)
def test_validate_transition_allowlist_rejects(
    mutation: Any, fragment: str, transitions: dict[str, Any]
) -> None:
    broken = copy.deepcopy(transitions)
    mutation(broken)
    assert any(fragment in p for p in validate_transition_allowlist(broken)), (
        validate_transition_allowlist(broken)
    )


# --------------------------------------------------------------------------- confirmation hash


def test_confirmation_hash_test_vector(confirmation_hash_definition: dict[str, Any]) -> None:
    definition = confirmation_hash_definition
    vector = definition["test_vector"]
    assert definition["hashed_fields"] == [
        "target",
        "target_version",
        "proposed_diff",
        "confirmation_expires_at",
        "actor",
    ]
    assert jcs(vector["input"]) == vector["canonical_json"]
    assert (
        confirmation_hash(vector["input"], definition["hashed_fields"]) == vector["expected_hash"]
    )


def test_confirmation_hash_is_described_by_the_schema(
    confirmation_hash_definition: dict[str, Any],
) -> None:
    description = load_schema(INTENT)["properties"]["confirmation_hash"]["description"]
    for field in confirmation_hash_definition["hashed_fields"]:
        assert field in description
    applies_to = confirmation_hash_definition["applies_to"]
    assert applies_to == load_schema(INTENT)["$id"] + "#/properties/confirmation_hash"


INTENTS = [c for c in valid_cases() if c.schema == INTENT]


@pytest.mark.parametrize("case", INTENTS, ids=[c.case_id for c in INTENTS])
def test_validate_confirmation_hash_on_examples(
    case: Any, confirmation_hash_definition: dict[str, Any]
) -> None:
    assert validate_confirmation_hash(case.load(), confirmation_hash_definition) == []


def test_confirmation_hash_is_channel_independent(
    confirmation_hash_definition: dict[str, Any],
) -> None:
    intent = load_json(
        SCHEMA_ROOT / "actions/v1/examples/valid/action-intent.awaiting-approval.json"
    )
    fields = confirmation_hash_definition["hashed_fields"]
    for change in (
        {"channel": "mcp"},
        {"idempotency_key": "another-key-0000000001"},
        {"state": "executing"},
        {"evidence": []},
    ):
        assert confirmation_hash({**intent, **change}, fields) == intent["confirmation_hash"], (
            change
        )
    for change in (
        {"target_version": "etag-other"},
        {"confirmation_expires_at": "2026-10-10T17:16:00Z"},
        {"actor": {**intent["actor"], "principal_pseudonym": "p-other"}},
    ):
        tampered = {**intent, **change}
        assert validate_confirmation_hash(tampered, confirmation_hash_definition), change


def test_validate_intent_timestamps() -> None:
    intent = load_json(
        SCHEMA_ROOT / "actions/v1/examples/valid/action-intent.awaiting-approval.json"
    )
    assert validate_intent_timestamps(intent) == []
    assert validate_intent_timestamps({**intent, "state_changed_at": "2000-01-01T00:00:00Z"})
    assert validate_intent_timestamps({**intent, "confirmation_expires_at": intent["created_at"]})
    drafted = load_json(
        SCHEMA_ROOT / "actions/v1/examples/valid/action-intent.drafted-mcp-agent.json"
    )
    assert validate_intent_timestamps(drafted) == []


def test_validate_maker_checker_separation() -> None:
    decision = load_json(
        SCHEMA_ROOT / "actions/v1/examples/valid/approval-decision.maker-checker-approved.json"
    )
    assert validate_maker_checker_separation(decision) == []
    self_approved = copy.deepcopy(decision)
    self_approved["reviewer"]["principal_pseudonym"] = decision["maker"]["principal_pseudonym"]
    assert validate_maker_checker_separation(self_approved)
    proxy = copy.deepcopy(decision)
    proxy["maker"]["on_behalf_of"] = decision["reviewer"]["principal_pseudonym"]
    assert validate_maker_checker_separation(proxy)
    assert validate_maker_checker_separation({**self_approved, "self_approval_allowed": True}) == []
    insight = load_json(
        SCHEMA_ROOT / "actions/v1/examples/valid/approval-decision.insight-review-rejected.json"
    )
    assert validate_maker_checker_separation(insight) == []


def test_intent_requires_idempotency_key() -> None:
    assert "idempotency_key" in load_schema(INTENT)["required"]
