"""confirmation_hash is exactly confirmation-hash.json: JCS + SHA-256 over five fields (D1)."""

from __future__ import annotations

import copy
from typing import Any

import pytest
from neurosphere_contracts.actions.v1.action_intent import ActionIntent, ProposedDiff
from neurosphere_core.actions import (
    HASHED_FIELDS,
    ActionValidationError,
    compute_confirmation_hash,
    confirmation_hash_input,
    confirmation_hashes_equal,
    intent_to_wire,
    validate_proposed_diff,
)
from neurosphere_core.audit.canonical import canonical_json

from .action_helpers import CONTRACTS, MAKER, Harness, caller, load_contract, request

EXAMPLE = "examples/valid/action-intent.awaiting-approval.json"


@pytest.fixture(scope="module")
def definition() -> dict[str, Any]:
    return load_contract("confirmation-hash.json")


@pytest.fixture
def example() -> dict[str, Any]:
    return load_contract(EXAMPLE)


def test_hashed_fields_match_the_contract(definition: dict[str, Any]) -> None:
    assert tuple(definition["hashed_fields"]) == HASHED_FIELDS
    assert definition["canonicalization"] == "rfc8785_jcs"
    assert definition["prefix"] == "sha256:"


def test_reproduces_the_contract_test_vector(definition: dict[str, Any]) -> None:
    vector = definition["test_vector"]
    assert canonical_json(vector["input"]) == vector["canonical_json"]
    assert compute_confirmation_hash(vector["input"]) == vector["expected_hash"]


def test_model_and_wire_forms_agree_with_the_example(example: dict[str, Any]) -> None:
    intent = ActionIntent.model_validate(example)
    assert compute_confirmation_hash(intent) == example["confirmation_hash"]
    assert compute_confirmation_hash(example) == example["confirmation_hash"]
    assert intent_to_wire(intent) == example


def test_every_valid_intent_example_rehashes() -> None:
    checked = 0
    for path in sorted((CONTRACTS / "examples" / "valid").glob("action-intent.*.json")):
        doc = load_contract(str(path.relative_to(CONTRACTS)))
        intent = ActionIntent.model_validate(doc)
        assert intent_to_wire(intent) == doc, path.name
        if doc["confirmation_hash"] is not None:
            assert compute_confirmation_hash(intent) == doc["confirmation_hash"], path.name
            checked += 1
    assert checked >= 1


EXCLUDED_CHANGES: dict[str, Any] = {
    "channel": "mcp",
    "idempotency_key": "another-idempotency-key-0002",
    "state": "executing",
    "status_reason": "something_else",
    "evidence": [],
    "prerequisite_results": [],
    "correlation_id": "corr-other",
    "dry_run": True,
    "intent_id": "11111111-2222-4333-8444-555555555555",
    "created_at": "2026-10-10T16:00:00Z",
    "state_changed_at": "2026-10-10T17:05:00Z",
}


@pytest.mark.parametrize("field", sorted(EXCLUDED_CHANGES))
def test_excluded_fields_do_not_change_the_hash(example: dict[str, Any], field: str) -> None:
    changed = copy.deepcopy(example)
    changed[field] = EXCLUDED_CHANGES[field]
    assert compute_confirmation_hash(changed) == example["confirmation_hash"]
    intent = ActionIntent.model_validate(changed)
    assert compute_confirmation_hash(intent) == example["confirmation_hash"]


INCLUDED_CHANGES: dict[str, Any] = {
    "target": {
        "canonical_id": "commercial:contoso:foundry:model_deployment:eastus2/chat-canary",
        "entity_type": "model_deployment",
    },
    "target_version": "etag-0x8dce1f2a3b4c5d7",
    "proposed_diff": {
        "format": "json_patch",
        "operations": [{"op": "replace", "path": "/model/version", "value": "2026-07-01"}],
    },
    "confirmation_expires_at": "2026-10-10T17:15:01Z",
    "actor": {"principal_pseudonym": "p-other", "principal_kind": "user", "on_behalf_of": None},
}


@pytest.mark.parametrize("field", sorted(INCLUDED_CHANGES))
def test_hashed_fields_change_the_hash(example: dict[str, Any], field: str) -> None:
    changed = copy.deepcopy(example)
    changed[field] = INCLUDED_CHANGES[field]
    assert compute_confirmation_hash(changed) != example["confirmation_hash"]
    assert (
        compute_confirmation_hash(ActionIntent.model_validate(changed))
        != example["confirmation_hash"]
    )


def test_on_behalf_of_is_part_of_the_actor(example: dict[str, Any]) -> None:
    changed = copy.deepcopy(example)
    changed["actor"]["on_behalf_of"] = "p-user01"
    assert compute_confirmation_hash(changed) != example["confirmation_hash"]


def test_missing_member_is_refused(example: dict[str, Any]) -> None:
    incomplete = {k: v for k, v in example.items() if k != "target_version"}
    with pytest.raises(ActionValidationError) as caught:
        confirmation_hash_input(incomplete)
    assert caught.value.reason == "invalid_hash_input"


def test_patch_op_wire_form_is_schema_valid() -> None:
    diff = ProposedDiff.model_validate(
        {
            "format": "json_patch",
            "operations": [
                {"op": "remove", "path": "/a"},
                {"op": "move", "from": "/b", "path": "/c"},
                {"op": "add", "path": "/d", "value": None},
            ],
        }
    )
    validate_proposed_diff(diff)
    example = load_contract(EXAMPLE)
    example["proposed_diff"] = diff.model_dump(mode="json", by_alias=True)
    wire = intent_to_wire(ActionIntent.model_validate(example))
    assert wire["proposed_diff"]["operations"] == [
        {"op": "remove", "path": "/a"},
        {"op": "move", "path": "/c", "from": "/b"},
        {"op": "add", "path": "/d", "value": None},
    ]
    # A naive dump (``from``/``value`` as null everywhere) would hash differently.
    assert compute_confirmation_hash(wire) != compute_confirmation_hash(example)


@pytest.mark.parametrize(
    "operation",
    [
        {"op": "replace", "path": "/a"},
        {"op": "add", "path": "/a", "value": 1, "from": "/b"},
        {"op": "move", "path": "/a"},
        {"op": "copy", "path": "/a", "from": "/b", "value": 1},
        {"op": "remove", "path": "/a", "value": 1},
    ],
)
def test_invalid_patch_members_are_rejected(operation: dict[str, Any]) -> None:
    diff = ProposedDiff.model_validate({"format": "json_patch", "operations": [operation]})
    with pytest.raises(ActionValidationError) as caught:
        validate_proposed_diff(diff)
    assert caught.value.reason == "invalid_diff"


def test_hash_comparison_is_strict() -> None:
    value = "sha256:" + "a" * 64
    assert confirmation_hashes_equal(value, value)
    assert not confirmation_hashes_equal(value, "sha256:" + "b" * 64)
    assert not confirmation_hashes_equal(None, None)
    assert not confirmation_hashes_equal(value, None)


async def test_same_intent_hashes_identically_on_every_channel() -> None:
    h = Harness()
    hashes: set[str] = set()
    for index, channel in enumerate(("button", "chat", "rest", "mcp")):
        who = caller(channel=channel, correlation_id=f"corr-{channel}")
        req = request(f"idem-2026-10-20-channel-{index:04d}", channel=channel)
        outcome = await h.service.draft(
            who, req, customer_id="contoso", domain_id="commercial:contoso:catalog:domain:retail"
        )
        await h.service.record_validation(outcome.stored.key, who, [])
        presented = await h.service.present_confirmation(outcome.stored.key, who)
        assert presented.intent.channel == channel
        bound = presented.intent.confirmation_hash
        assert bound is not None
        assert bound.root == compute_confirmation_hash(presented.intent)
        hashes.add(bound.root)
    assert len(hashes) == 1


async def test_presented_hash_binds_the_exact_expiry() -> None:
    h = Harness()
    first = await h.awaiting_confirmation()
    second = await h.awaiting_confirmation(request("idem-2026-10-20-chat-prod-0002"))
    assert first.intent.confirmation_hash == second.intent.confirmation_hash
    h.clock.now = h.clock.now.replace(second=h.clock.now.second + 2)
    third = await h.awaiting_confirmation(request("idem-2026-10-20-chat-prod-0003"))
    assert third.intent.confirmation_expires_at != first.intent.confirmation_expires_at
    assert third.intent.confirmation_hash != first.intent.confirmation_hash
    assert MAKER.actor == third.intent.actor
