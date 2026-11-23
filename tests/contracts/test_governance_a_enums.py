"""Catalog approval, query field, manifest actions, admin and scope enums (PRP-99 item 5).

Every change is additive: new enum members, one optional property, appended ``allOf`` members
that constrain only new values. The if/then rules the generated Pydantic model drops are pinned
here against the JSON Schema itself. Nothing here diffs against the v1 baseline snapshot.
"""

from __future__ import annotations

import copy
from typing import Any, get_args
from urllib.parse import urlsplit

import pytest
import validators as v
from contract_support import SCHEMA_ROOT, load_json, load_schema, model_for, schema_errors
from neurosphere_connector.manifest import WriteAction

AGENT_VERSION = "catalog/v1/agent_version.schema.json"
CATALOG_COMMON = "catalog/v1/common.schema.json"
QUERY = "query/v1/structured-query.schema.json"
MANIFEST = "connectors/v1/connector-manifest.schema.json"
ADMIN_COMMON = "admin/v1/common.schema.json"
CONNECTOR_CONFIG = "admin/v1/connector-config.schema.json"
REVIEW = "admin/v1/review-policy-document.schema.json"
SETTING = "admin/v1/system-setting.schema.json"
DOCUMENT = "admin/v1/admin-config-document.schema.json"
ROLE_CHANGE = "admin/v1/role-assignment-change.schema.json"
ACCESS_SUMMARY = "admin/v1/principal-access-summary.schema.json"
IDENTITY_SCOPE = "scope/v1/identity-scope.schema.json"

OPEN_ENDED = "open-ended: readers must tolerate unknown values"
ADMIN_EXAMPLES = SCHEMA_ROOT / "admin" / "v1" / "examples" / "valid"


def _load(rel: str) -> dict[str, Any]:
    return copy.deepcopy(load_json(SCHEMA_ROOT / rel))


def _admin(name: str) -> dict[str, Any]:
    return load_json(ADMIN_EXAMPLES / f"{name}.json")


def _agent_version() -> dict[str, Any]:
    return _load("catalog/v1/examples/valid/agent_version.approved.json")


def _is_open_ended(description: str) -> bool:
    return OPEN_ENDED in description.lower()


# ------------------------------------------------------------------ catalog and query


def test_agent_version_with_approval_validates() -> None:
    doc = _agent_version()
    assert doc["approval"]["state"] == "approved"
    assert schema_errors(AGENT_VERSION, doc) == []
    model_for(AGENT_VERSION).model_validate(doc)


def test_agent_version_without_approval_validates_unchanged() -> None:
    doc = _agent_version()
    del doc["approval"]
    assert schema_errors(AGENT_VERSION, doc) == []
    parsed = model_for(AGENT_VERSION).model_validate(doc)
    assert parsed.approval is None
    assert schema_errors(AGENT_VERSION, {**doc, "approval": None}) == []


def test_unknown_approval_state_is_rejected() -> None:
    doc = _agent_version()
    doc["approval"]["state"] = "maybe"
    assert schema_errors(AGENT_VERSION, doc)
    with pytest.raises(ValueError):
        model_for(AGENT_VERSION).model_validate(doc)


@pytest.mark.parametrize("state", ["not_required", "pending", "approved", "rejected", "suspended"])
def test_every_approval_state_is_accepted(state: str) -> None:
    doc = _agent_version()
    doc["approval"] = {"state": state}
    assert schema_errors(AGENT_VERSION, doc) == []


def test_approval_rejects_unknown_member() -> None:
    doc = _agent_version()
    doc["approval"]["comment"] = "free text"
    assert schema_errors(AGENT_VERSION, doc)


def test_approval_state_enum_says_open_ended() -> None:
    defs = load_schema(CATALOG_COMMON)["$defs"]
    assert defs["approval_state"]["title"] == "AgentVersionApprovalState"
    assert defs["agent_version_approval"]["title"] == "AgentVersionApproval"
    assert _is_open_ended(defs["approval_state"]["description"])


def _query(entity: str) -> dict[str, Any]:
    query = _load("query/v1/examples/valid/structured-query.list-agents.json")
    query["entity"] = entity
    query["filters"] = [{"field": "approval_state", "op": "eq", "value": "approved"}]
    return query


def test_approval_state_is_a_query_field_applicable_to_agent_version_only() -> None:
    assert "approval_state" in load_schema(QUERY)["$defs"]["keyword_field"]["enum"]
    accepted = _query("agent_version")
    assert schema_errors(QUERY, accepted) == []
    assert v.check_structured_query_field_applicability(accepted) == []
    for entity in sorted(set(v.FIELD_APPLICABILITY) - {"agent_version"}):
        assert "approval_state" not in v.FIELD_APPLICABILITY[entity], entity
        assert v.check_structured_query_field_applicability(_query(entity)), entity


# ------------------------------------------------------------------ connectors


NEW_ACTIONS = [
    "agent_version_approve",
    "agent_version_suspend",
    "capture_policy_change",
    "governance_policy_publish",
    "enforcement_mode_change",
    "gateway_policy_apply",
]


def test_manifest_actions_add_the_six_governance_kinds() -> None:
    schema = load_schema(MANIFEST)
    actions = schema["$defs"]["write_support"]["properties"]["actions"]
    assert set(NEW_ACTIONS) <= set(actions["items"]["enum"])
    assert _is_open_ended(actions["description"])
    assert set(NEW_ACTIONS) <= set(get_args(WriteAction))
    assert list(get_args(WriteAction)) == actions["items"]["enum"]


# ------------------------------------------------------------------ admin enums


def test_admin_kind_adds_the_three_kinds_and_says_open_ended() -> None:
    kind = load_schema(ADMIN_COMMON)["$defs"]["admin_kind"]
    assert {"notification_channel", "notification_subscription", "enforcement_binding"} <= set(
        kind["enum"]
    )
    assert _is_open_ended(kind["description"])


def test_connector_kind_adds_the_eleven_values() -> None:
    node = load_schema(CONNECTOR_CONFIG)["properties"]["connector_kind"]
    new = {
        "generic",
        "entra_identity",
        "purview",
        "unity_catalog",
        "m365_copilot",
        "github_copilot",
        "cursor",
        "openai_enterprise",
        "anthropic_claude",
        "entra_shadow_ai",
        "github_issues",
    }
    assert new <= set(node["enum"])
    assert _is_open_ended(node["description"])
    config = _admin("connector-config.gateway-poll")
    for value in sorted(new):
        assert schema_errors(CONNECTOR_CONFIG, {**config, "connector_kind": value}) == [], value
    assert schema_errors(CONNECTOR_CONFIG, {**config, "connector_kind": "telepathy"})


def test_role_enum_adds_investigator_everywhere_it_is_declared() -> None:
    role = load_schema(ADMIN_COMMON)["$defs"]["role"]
    assert "interaction_investigator" in role["enum"]
    assert _is_open_ended(role["description"])
    scope_role = load_schema(IDENTITY_SCOPE)["$defs"]["role_assignment"]["properties"]["role"]
    assert "interaction_investigator" in scope_role["enum"]
    assert _is_open_ended(scope_role["description"])
    assert role["enum"] == scope_role["enum"]


def test_approver_permission_adds_config_and_govpolicy_manage() -> None:
    node = load_schema(REVIEW)["$defs"]["policy"]["properties"]["approver_permission"]
    assert {"config.manage", "govpolicy.manage"} <= set(node["enum"])
    assert _is_open_ended(node["description"])
    document = _admin("review-policy-document.defaults-with-override")
    document["kind_defaults"][0]["policy"]["approver_permission"] = "govpolicy.manage"
    assert schema_errors(REVIEW, document) == []
    document["kind_defaults"][0]["policy"]["approver_permission"] = "root.everything"
    assert schema_errors(REVIEW, document)


def test_setting_key_adds_three_keys_and_says_open_ended() -> None:
    node = load_schema(SETTING)["properties"]["setting_key"]
    assert {"interaction_capture", "notifications", "enforcement"} <= set(node["enum"])
    assert _is_open_ended(node["description"])


def test_kek_provider_and_failure_mode_say_open_ended() -> None:
    defs = load_schema(SETTING)["$defs"]
    assert _is_open_ended(defs["interaction_capture"]["properties"]["kek_provider"]["description"])
    assert _is_open_ended(defs["enforcement"]["properties"]["sdk_failure_mode"]["description"])


# ------------------------------------------------------------------ investigator is privileged


def _role_change(role: str) -> dict[str, Any]:
    change = _admin("role-assignment-change.assign-interaction-investigator")
    change["role"] = role
    return change


def test_role_change_requires_expiry_for_investigator() -> None:
    change = _role_change("interaction_investigator")
    assert schema_errors(ROLE_CHANGE, change) == []
    del change["expires_at"]
    assert any(e.validator == "required" for e in schema_errors(ROLE_CHANGE, change))
    assert schema_errors(ROLE_CHANGE, {**change, "op": "remove"}) == []


def test_role_change_viewer_still_needs_no_expiry() -> None:
    change = _role_change("viewer")
    del change["expires_at"]
    assert schema_errors(ROLE_CHANGE, change) == []


def _scope_with(role_entry: dict[str, Any]) -> dict[str, Any]:
    scope = _load("scope/v1/examples/valid/identity-scope.viewer.json")
    scope["roles"] = [role_entry]
    return scope


def test_identity_scope_requires_expiry_for_investigator() -> None:
    domain = _load("scope/v1/examples/valid/identity-scope.viewer.json")["roles"][0]["domain_ids"]
    entry = {"role": "interaction_investigator", "domain_ids": domain}
    errors = schema_errors(IDENTITY_SCOPE, _scope_with(entry))
    assert any(e.validator == "required" and "expires_at" in e.message for e in errors)
    timed = {**entry, "expires_at": "2027-02-14T00:00:00Z"}
    assert schema_errors(IDENTITY_SCOPE, _scope_with(timed)) == []


def test_access_summary_requires_expiry_for_investigator() -> None:
    summary = _admin("principal-access-summary.typical")
    assignment = summary["assignments"][0]
    assignment["role"] = "interaction_investigator"
    assignment["expires_at"] = None
    assert schema_errors(ACCESS_SUMMARY, summary)
    assignment["expires_at"] = "2027-02-14T00:00:00Z"
    assert schema_errors(ACCESS_SUMMARY, summary) == []


# ------------------------------------------------------------------ admin_kind body pins


KIND_BODIES = {
    "notification_channel": "notifications/v1/examples/valid/notification-channel.teams.json",
    "notification_subscription": (
        "notifications/v1/examples/valid/notification-subscription.by-role.json"
    ),
    "enforcement_binding": "policy/v1/examples/valid/enforcement-binding.gateway.json",
}


def _envelope(kind: str, body: dict[str, Any]) -> dict[str, Any]:
    envelope = _admin("admin-config-document.domain")
    return {**envelope, "kind": kind, "body": body}


@pytest.mark.parametrize("kind", sorted(KIND_BODIES))
def test_new_admin_kind_accepts_its_body_and_rejects_another(kind: str) -> None:
    assert schema_errors(DOCUMENT, _envelope(kind, _load(KIND_BODIES[kind]))) == []
    for other, rel in KIND_BODIES.items():
        if other != kind:
            assert schema_errors(DOCUMENT, _envelope(kind, _load(rel))), (kind, other)
    domain_body = _admin("admin-config-document.domain")["body"]
    assert schema_errors(DOCUMENT, _envelope(kind, domain_body))


def test_existing_kinds_reject_the_new_bodies() -> None:
    for rel in KIND_BODIES.values():
        assert schema_errors(DOCUMENT, _envelope("domain", _load(rel)))
        assert schema_errors(DOCUMENT, _envelope("system_setting", _load(rel)))


def test_new_kind_documents_validate_through_the_generated_model() -> None:
    for kind, rel in KIND_BODIES.items():
        model_for(DOCUMENT).model_validate(_envelope(kind, _load(rel)))


# ------------------------------------------------------------------ system-setting members


def _capture() -> dict[str, Any]:
    return _admin("system-setting.interaction-capture")


def _kek(setting: dict[str, Any], value: Any) -> dict[str, Any]:
    setting["interaction_capture"]["kek_uri"] = value
    return setting


@pytest.mark.parametrize("suffix", ["azure.net", "usgovcloudapi.net"])
@pytest.mark.parametrize("version", ["", "/" + "0123456789abcdef" * 2])
def test_kek_uri_accepts_key_vault_key_identifiers(suffix: str, version: str) -> None:
    uri = f"https://kv-ns-contoso.vault.{suffix}/keys/interaction-kek{version}"
    assert schema_errors(SETTING, _kek(_capture(), uri)) == []


def _bad_kek_uris() -> list[str]:
    version = "/" + "0123456789abcdef" * 2
    return [
        "https://kv-ns-contoso.vault.azure.net/secrets/interaction-kek",
        "https://kv-ns-contoso.vault.azure.net/keys/interaction-kek/short",
        "https://kv-ns-contoso.vault.azure.net/keys/interaction-kek" + version + "/extra",
        "https://example.com/keys/interaction-kek",
        "https://kv-ns-contoso.vault.azure.net.example.com/keys/interaction-kek",
        "http://kv-ns-contoso.vault.azure.net/keys/interaction-kek",
        "https://user:pw@kv-ns-contoso.vault.azure.net/keys/interaction-kek",
        "https://kv-ns-contoso.vault.azure.net/keys/interaction-kek?sig=1",
    ]


@pytest.mark.parametrize("uri", _bad_kek_uris())
def test_kek_uri_rejects_non_key_identifiers(uri: str) -> None:
    assert schema_errors(SETTING, _kek(_capture(), uri))


def test_kek_uri_vault_suffix_must_match_the_cloud() -> None:
    commercial = "https://kv-ns-contoso.vault.azure.net/keys/interaction-kek"
    government = "https://kv-ns-contoso.vault.usgovcloudapi.net/keys/interaction-kek"
    assert v.check_kek_uri_cloud(commercial, "commercial") == []
    assert v.check_kek_uri_cloud(government, "government") == []
    assert v.check_kek_uri_cloud(commercial, "government")
    assert v.check_kek_uri_cloud(government, "commercial")
    host = urlsplit(government).hostname or ""
    assert host.split(".")[-3:] == ["vault", "usgovcloudapi", "net"]


def test_setting_validator_matches_kek_vault_to_the_credential_cloud() -> None:
    setting = _capture()
    setting["interaction_capture"]["credential"] = {
        "kind": "key_vault_secret",
        "secret_uri": "https://kv-ns-contoso.vault.azure.net/secrets/capture/"
        + "0123456789abcdef" * 2,
    }
    assert v.check_system_setting_cloud(setting) == []
    gov = "https://kv-ns-contoso.vault.usgovcloudapi.net/keys/interaction-kek"
    assert v.check_system_setting_cloud(_kek(copy.deepcopy(setting), gov))
    assert v.check_system_setting_cloud(_capture()) == []
    assert v.check_system_setting_cloud(_admin("system-setting.notifications")) == []


def test_kek_uri_null_only_without_key_vault_key() -> None:
    setting = _kek(_capture(), None)
    errors = schema_errors(SETTING, setting)
    assert any(e.validator in {"type", "anyOf"} for e in errors)
    setting["interaction_capture"]["kek_provider"] = "local_development"
    assert schema_errors(SETTING, setting) == []
    del setting["interaction_capture"]["kek_uri"]
    assert schema_errors(SETTING, setting)


def test_kek_provider_key_vault_key_requires_the_uri() -> None:
    setting = _capture()
    del setting["interaction_capture"]["kek_uri"]
    assert schema_errors(SETTING, setting)


def test_interaction_capture_member_pins() -> None:
    assert schema_errors(SETTING, _capture()) == []
    member = load_schema(SETTING)["$defs"]["interaction_capture"]
    assert member["title"] == "InteractionCaptureSetting"
    props = member["properties"]
    assert props["max_content_chars_per_interaction"]["default"] == 65536
    assert props["max_content_chars_per_interaction"]["maximum"] == 163840
    assert props["shed_capture_at_queue_percent"]["default"] == 80
    assert props["credential"] == {"$ref": "credential-reference.schema.json"}
    bad_container = _capture()
    bad_container["interaction_capture"]["content_container"] = "Bad_Container"
    assert schema_errors(SETTING, bad_container)
    inline = _capture()
    inline["interaction_capture"]["credential"] = {"kind": "managed_identity", "value": "x"}
    assert schema_errors(SETTING, inline)


def test_notifications_and_enforcement_member_pins() -> None:
    defs = load_schema(SETTING)["$defs"]
    assert defs["notifications"]["title"] == "NotificationsSetting"
    assert defs["enforcement"]["title"] == "EnforcementSetting"
    notifications = defs["notifications"]["properties"]
    assert (notifications["max_attempts"]["default"], notifications["max_attempts"]["maximum"]) == (
        8,
        20,
    )
    assert notifications["retry_base_seconds"]["default"] == 30
    assert notifications["dedup_window_seconds"]["default"] == 900
    enforcement = defs["enforcement"]["properties"]
    assert enforcement["sdk_failure_mode"]["default"] == "fail_open"
    assert enforcement["decision_cache_ttl_seconds"]["default"] == 60
    assert enforcement["decide_rate_limit_per_minute"]["default"] == 600
    assert schema_errors(SETTING, _admin("system-setting.notifications")) == []
    assert schema_errors(SETTING, _admin("system-setting.enforcement")) == []


@pytest.mark.parametrize("key", ["interaction_capture", "notifications", "enforcement"])
def test_each_new_setting_key_requires_its_own_member_and_no_other(key: str) -> None:
    setting = _admin(f"system-setting.{key.replace('_', '-')}")
    assert schema_errors(SETTING, setting) == []
    missing = {k: val for k, val in setting.items() if k != key}
    assert any(e.validator == "required" for e in schema_errors(SETTING, missing))
    others = {
        "interaction_capture": _capture()["interaction_capture"],
        "notifications": _admin("system-setting.notifications")["notifications"],
        "enforcement": _admin("system-setting.enforcement")["enforcement"],
    }
    for other, member in others.items():
        if other != key:
            assert schema_errors(SETTING, {**setting, other: member}), (key, other)


def test_notifications_setting_rejects_urls_and_empty_host_list() -> None:
    setting = _admin("system-setting.notifications")
    setting["notifications"]["egress_allowed_hosts"] = ["https://hooks.example.test/path"]
    assert schema_errors(SETTING, setting)
    setting["notifications"]["egress_allowed_hosts"] = []
    assert schema_errors(SETTING, setting)
    setting["notifications"]["egress_allowed_hosts"] = ["a.example.test", "a.example.test"]
    assert schema_errors(SETTING, setting)
