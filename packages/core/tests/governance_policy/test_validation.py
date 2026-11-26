"""Draft validation (PRP-105 item 1, acceptance criterion 1): closed kinds, per-kind params,
bounds, unique rule ids and no executable field; every failure is 422 ``invalid_schema``."""

from __future__ import annotations

import copy
from typing import Any

import pytest
from neurosphere_core.errors import InvalidSchemaError
from neurosphere_core.governance.policy import (
    PolicyValidationError,
    rules_digest,
    validate_draft,
    validate_policy,
)
from neurosphere_core.governance.policy.models import (
    PolicyDefinition,
    PolicyRule,
    ResidencyParams,
)
from neurosphere_core.governance.policy.validation import MAX_LIST_ITEMS, MAX_RULES

from .builders import AUTHOR, draft, example


def _refused(document: Any, reason: str, **kwargs: Any) -> PolicyValidationError:
    with pytest.raises(PolicyValidationError) as info:
        validate_draft(document, **kwargs)
    error = info.value
    assert isinstance(error, InvalidSchemaError)
    assert error.code == "invalid_schema"
    assert error.http_status == 422
    assert error.reason == reason, (
        error.reason,
        [(i.pointer, i.detail) for i in error.errors or ()],
    )
    return error


def test_a_valid_draft_with_every_kind_passes_and_gets_a_server_digest() -> None:
    policy = validate_draft(draft())
    assert isinstance(policy, PolicyDefinition)
    assert policy.status == "draft"
    assert policy.content_sha256 == rules_digest(policy.rules)
    assert len(policy.rules) == 9


def test_params_are_pinned_to_the_rule_kind() -> None:
    policy = validate_draft(draft())
    by_kind = {rule.kind.root: type(rule.params).__name__ for rule in policy.rules}
    assert by_kind["residency"] == "ResidencyParams"
    assert by_kind["required_owner"] == "RequiredOwnerParams"
    assert by_kind["model_allow_list"] == "ModelAllowListParams"


def test_digest_is_stable_and_depends_on_rules() -> None:
    first = validate_draft(draft()).content_sha256
    assert validate_draft(draft()).content_sha256 == first
    changed = draft()
    changed["rules"][0]["params"]["allowed_models"][0]["model_name"] = "gpt-4.1"
    assert validate_draft(changed).content_sha256 != first


def test_unknown_rule_kind_is_refused() -> None:
    document = draft()
    document["rules"][0]["kind"] = "custom_expression"
    error = _refused(document, "unknown_rule_kind")
    assert [i.pointer for i in error.errors or ()] == ["/rules/0/kind"]


def test_identity_entitlement_is_not_in_the_closed_list_yet() -> None:
    document = draft()
    document["rules"][0]["kind"] = "identity_entitlement"
    _refused(document, "unknown_rule_kind")


def test_params_of_another_kind_are_refused() -> None:
    document = draft()
    # residency parameters under a model_allow_list rule: the generated union would accept them.
    document["rules"][0]["params"] = {"allowed_geographies": ["eu_eea"], "allowed_regions": []}
    error = _refused(document, "invalid_policy")
    assert all(i.pointer.startswith("/rules/0/params") for i in error.errors or ())


def test_params_missing_a_required_field_are_refused() -> None:
    document = draft()
    del document["rules"][1]["params"]["access"]
    _refused(document, "invalid_policy")


@pytest.mark.parametrize(
    ("where", "key"),
    [
        ("rule", "expression"),
        ("rule", "condition"),
        ("params", "query"),
        ("params", "template"),
        ("applies_to", "script"),
        ("top", "rule_text"),
    ],
)
def test_no_executable_free_text_field_is_accepted(where: str, key: str) -> None:
    document = draft()
    payload = "1 == 1"
    if where == "rule":
        document["rules"][0][key] = payload
    elif where == "params":
        document["rules"][0]["params"][key] = payload
    elif where == "applies_to":
        document["rules"][0]["applies_to"][key] = payload
    else:
        document[key] = payload
    _refused(document, "invalid_policy")


def test_duplicate_rule_ids_are_refused() -> None:
    document = draft()
    document["rules"][1]["rule_id"] = document["rules"][0]["rule_id"]
    error = _refused(document, "duplicate_rule_id")
    assert [i.pointer for i in error.errors or ()] == ["/rules/1/rule_id"]


def test_rule_count_is_bounded() -> None:
    document = draft(kinds=("required_owner",))
    base = document["rules"][0]
    document["rules"] = [
        {**copy.deepcopy(base), "rule_id": f"owner-{i}"} for i in range(MAX_RULES + 1)
    ]
    _refused(document, "too_many_rules")
    document["rules"] = document["rules"][:MAX_RULES]
    assert len(validate_draft(document).rules) == MAX_RULES


def test_empty_rules_are_refused() -> None:
    document = draft()
    document["rules"] = []
    _refused(document, "invalid_policy")


def test_the_contract_33_rule_example_is_refused() -> None:
    document = example("invalid", "policy-definition.33-rules.json")
    document["status"] = "draft"
    for field in ("published_at", "published_intent_id", "published_audit_id"):
        document.pop(field, None)
    with pytest.raises(PolicyValidationError):
        validate_draft(document)


def test_parameter_lists_are_bounded_at_200_items() -> None:
    document = draft()
    document["rules"][0]["params"]["allowed_models"] = [
        {"model_name": f"m{i}", "model_version": None} for i in range(MAX_LIST_ITEMS + 1)
    ]
    error = _refused(document, "list_too_long")
    assert error.errors is not None
    assert error.errors[0].pointer == "/rules/0/params/allowed_models"


def test_contract_list_bounds_below_200_still_apply() -> None:
    document = draft()
    document["rules"][0]["params"]["allowed_models"] = [
        {"model_name": f"m{i}", "model_version": None} for i in range(65)
    ]
    _refused(document, "invalid_policy")


def test_ids_of_another_customer_or_cloud_are_refused() -> None:
    document = draft()
    document["rules"][0]["applies_to"]["entity_ids"] = [
        "commercial:globex:neurosphere:agent:support-bot"
    ]
    _refused(document, "cross_customer")
    document = draft()
    document["rules"][0]["params"]["allowed_deployment_ids"] = [
        "government:acme:neurosphere:model_deployment:gpt"
    ]
    _refused(document, "cross_cloud")
    document = draft()
    document["domain_id"] = "commercial:globex:neurosphere:domain:support"
    _refused(document, "cross_customer")
    document = draft()
    document["created_by"] = "commercial:globex:entra:person:p-" + "3" * 64
    _refused(document, "cross_customer")


def test_only_drafts_pass_draft_validation() -> None:
    document = draft()
    document["status"] = "published"
    _refused(document, "not_a_draft")
    document = draft()
    document["published_intent_id"] = "00000001-0000-4000-8000-000000000001"
    _refused(document, "draft_has_publish_evidence")


def test_published_needs_publish_evidence() -> None:
    document = draft()
    document["status"] = "published"
    with pytest.raises(PolicyValidationError) as info:
        validate_policy(document, stamp_digest=True)
    assert info.value.reason == "publish_evidence_missing"


def test_the_contract_published_example_revalidates_only_with_its_true_digest() -> None:
    document = example("valid", "policy-definition.all-kinds.json")
    with pytest.raises(PolicyValidationError) as info:
        validate_policy(document)
    assert info.value.reason == "content_digest_mismatch"
    stamped = validate_policy(document, stamp_digest=True)
    assert validate_policy(stamped.model_dump(mode="json")) == stamped


def test_a_model_instance_with_defaulted_params_validates_by_its_kind() -> None:
    # {} matches several parameter models; the instance path must still pin by kind.
    raw = draft(kinds=("residency",))
    raw["rules"][0]["params"] = {}
    policy = validate_draft(raw)
    assert isinstance(policy.rules[0].params, ResidencyParams)
    again = validate_draft(PolicyDefinition.model_validate(policy.model_dump(mode="json")))
    assert isinstance(again.rules[0].params, ResidencyParams)


def test_a_document_that_is_not_an_object_is_refused() -> None:
    not_an_object: Any = ["not", "a", "policy"]
    _refused(not_an_object, "invalid_policy")


def test_rule_that_is_not_an_object_is_refused() -> None:
    document = draft()
    document["rules"][0] = "model_allow_list: gpt-4o"
    _refused(document, "invalid_policy")


def test_errors_never_echo_values() -> None:
    document = draft()
    planted = "SELECT * FROM c WHERE 1=1"
    document["rules"][0]["params"]["query"] = planted
    error = _refused(document, "invalid_policy")
    for issue in error.errors or ():
        assert planted not in issue.detail
    assert planted not in str(error)


def test_rule_model_round_trip_keeps_the_author() -> None:
    policy = validate_draft(draft())
    assert policy.created_by.root == AUTHOR
    assert all(isinstance(r, PolicyRule) for r in policy.rules)
