"""Core tables pinned to the PRP-99 contract, the capability table, and the id helpers."""

from __future__ import annotations

import re
from typing import get_args

import pytest
from neurosphere_contracts.policy.v1.enforcement_binding import EnforcementPoint
from neurosphere_contracts.policy.v1.policy_definition import PolicyRuleKind
from neurosphere_core.admin import ADMIN_KIND_MODELS, validate_kind
from neurosphere_core.errors import InvalidSchemaError
from neurosphere_core.governance.policy import (
    DETECTIVE_EVALUATION_CAN_BLOCK,
    ENFORCEMENT_POINT_CAPABILITIES,
    EVALUATED_KINDS,
    PARAMS_MODEL_BY_KIND,
    POINTS_BY_RULE_KIND,
    RULE_KINDS,
    binding_id_for,
    dedup_key,
    exception_canonical_id,
    governance_policy_canonical_id,
    governance_policy_chain_id,
    policy_entity_canonical_id,
    violation_canonical_id,
    violation_id_for,
)
from neurosphere_core.governance.policy.models import (
    EnforcementBinding,
    EnforcementPointName,
    RuleKindName,
)

from .builders import ASSET, SUBJECT

CONTRACT_KINDS = get_args(PolicyRuleKind.model_fields["root"].annotation)
CONTRACT_POINTS = get_args(EnforcementPoint.model_fields["root"].annotation)


def test_rule_kinds_are_the_contract_list_in_order() -> None:
    assert RULE_KINDS == CONTRACT_KINDS
    assert get_args(RuleKindName) == CONTRACT_KINDS


def test_evaluated_kinds_are_the_seven_of_clarification_2() -> None:
    assert EVALUATED_KINDS == {
        "model_allow_list",
        "data_sensitivity_access",
        "residency",
        "required_owner",
        "required_approval",
        "registration_required",
        "content_rule",
    }
    assert set(RULE_KINDS) - EVALUATED_KINDS == {"budget", "required_attestation"}


def test_every_kind_has_one_params_model_and_a_point_list() -> None:
    assert set(PARAMS_MODEL_BY_KIND) == set(RULE_KINDS)
    assert set(POINTS_BY_RULE_KIND) == set(RULE_KINDS)
    for points in POINTS_BY_RULE_KIND.values():
        assert set(points) <= set(CONTRACT_POINTS)
    assert POINTS_BY_RULE_KIND["content_rule"] == ()  # detective only


def test_capability_table_covers_every_point_exactly() -> None:
    assert set(ENFORCEMENT_POINT_CAPABILITIES) == set(CONTRACT_POINTS)
    assert get_args(EnforcementPointName) == CONTRACT_POINTS
    owners = {p: c.owning_prp for p, c in ENFORCEMENT_POINT_CAPABILITIES.items()}
    assert owners == {
        "gateway": "PRP-112",
        "tool_call": "PRP-113",
        "mcp_server": "PRP-113",
        "mcp_client": "PRP-113",
        "sdk": "PRP-114",
        "budget": "PRP-115",
        "registration": "PRP-108",
    }
    assert not ENFORCEMENT_POINT_CAPABILITIES["sdk"].can_block
    assert not ENFORCEMENT_POINT_CAPABILITIES["budget"].can_block
    assert "Commercial only" in ENFORCEMENT_POINT_CAPABILITIES["gateway"].what_it_blocks
    assert DETECTIVE_EVALUATION_CAN_BLOCK is False


def test_enforcement_binding_is_a_registered_admin_kind() -> None:
    assert validate_kind("enforcement_binding") == "enforcement_binding"
    assert ADMIN_KIND_MODELS["enforcement_binding"] is EnforcementBinding


def test_dedup_key_is_deterministic_and_part_sensitive() -> None:
    key = dedup_key("support-governance", "pii-access", SUBJECT, "reads_sensitive")
    assert re.fullmatch(r"sha256:[a-f0-9]{64}", key)
    assert key == dedup_key("support-governance", "pii-access", SUBJECT, "reads_sensitive")
    others = {
        dedup_key("other-policy", "pii-access", SUBJECT, "reads_sensitive"),
        dedup_key("support-governance", "owner-needed", SUBJECT, "reads_sensitive"),
        dedup_key("support-governance", "pii-access", ASSET, "reads_sensitive"),
        dedup_key("support-governance", "pii-access", SUBJECT, "writes_sensitive"),
    }
    assert key not in others
    assert len(others) == 4


@pytest.mark.parametrize(
    "parts",
    [
        ("Not A Slug", "r", SUBJECT, "c"),
        ("p", "r", "not-canonical", "c"),
        ("p", "r", SUBJECT, "Bad Class"),
    ],
)
def test_dedup_key_refuses_free_text(parts: tuple[str, str, str, str]) -> None:
    with pytest.raises(InvalidSchemaError) as info:
        dedup_key(*parts)
    assert info.value.reason == "invalid_policy_id"


def test_violation_ids_are_uuid5_per_generation() -> None:
    key = dedup_key("support-governance", "pii-access", SUBJECT, "reads_sensitive")
    first, second = violation_id_for(key, 1), violation_id_for(key, 2)
    assert first == violation_id_for(key, 1)
    assert first != second
    assert re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-5[0-9a-f]{3}-[0-9a-f]{4}-[0-9a-f]{12}", first)
    with pytest.raises(InvalidSchemaError):
        violation_id_for(key, 0)


def test_canonical_ids_follow_the_catalog_grammar() -> None:
    vid = "00000003-0000-4000-8000-000000000003"
    assert (
        violation_canonical_id("commercial", "acme", vid)
        == "commercial:acme:neurosphere:policy_violation:" + vid
    )
    assert (
        exception_canonical_id("government", "agency-a", vid)
        == "government:agency-a:neurosphere:policy_exception:" + vid
    )
    assert (
        policy_entity_canonical_id("commercial", "acme", "support-governance")
        == "commercial:acme:neurosphere:policy:support-governance"
    )
    assert (
        governance_policy_canonical_id("commercial", "acme", "support-governance")
        == "commercial:acme:neurosphere:governance_policy:support-governance"
    )
    with pytest.raises(InvalidSchemaError):
        violation_canonical_id("azure", "acme", vid)
    with pytest.raises(InvalidSchemaError):
        policy_entity_canonical_id("commercial", "Acme Corp", "p")


def test_chain_id() -> None:
    assert governance_policy_chain_id("acme") == "acme.governance-policy"
    with pytest.raises(InvalidSchemaError) as info:
        governance_policy_chain_id("acme:corp")
    assert info.value.reason == "invalid_chain_id"


def test_binding_ids_are_deterministic_slugs() -> None:
    one = binding_id_for("acme", "support-governance", "gateway", None)
    assert one == binding_id_for("acme", "support-governance", "gateway", None)
    assert re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", one)
    assert one != binding_id_for("acme", "support-governance", "sdk", None)
    assert one != binding_id_for("acme", "support-governance", "gateway", SUBJECT)
    assert one != binding_id_for("globex", "support-governance", "gateway", None)
