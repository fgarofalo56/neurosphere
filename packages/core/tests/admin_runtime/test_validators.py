"""PRP-45 item 1: per-key validation of stored runtime settings and the init-argument mapping."""

from __future__ import annotations

import copy
from typing import Any

import pytest
from neurosphere_core.admin.runtime import (
    SETTING_KEYS,
    copilot_init_args,
    document_id,
    judge_init_args,
    key_of_document,
    mcp_server_init_args,
    scan_init_args,
    search_init_args,
    validate_setting,
)
from neurosphere_core.errors import InvalidSchemaError

from .setting_bodies import (
    BODIES,
    CUSTOMER,
    GOV_MODEL,
    model_body,
    scan_body,
    search_body,
)


def _validate(key: str, body: dict[str, Any], cloud: Any = "commercial") -> Any:
    return validate_setting(key, body, customer_id=CUSTOMER, cloud=cloud)


def _reason(key: str, body: dict[str, Any], cloud: Any = "commercial") -> str | None:
    with pytest.raises(InvalidSchemaError) as caught:
        _validate(key, body, cloud)
    return caught.value.reason


def test_six_keys_in_display_order() -> None:
    assert SETTING_KEYS == ("copilot", "judge", "search", "scan", "mcp_server", "write_targets")


@pytest.mark.parametrize("key", SETTING_KEYS)
def test_each_key_round_trips(key: str) -> None:
    body = BODIES[key]
    model = _validate(key, body)
    again = _validate(key, model.model_dump(mode="json"))
    assert again == model


def test_document_ids_round_trip() -> None:
    for key in SETTING_KEYS:
        kind = "apim" if key == "write_targets" else None
        assert key_of_document(document_id(key, kind)) == key  # type: ignore[arg-type]
    assert key_of_document("system.write_target.other") is None
    assert key_of_document("system.write_targets") is None
    assert key_of_document("budget.x") is None
    with pytest.raises(ValueError):
        document_id("write_targets")
    with pytest.raises(ValueError):
        document_id("copilot", "apim")


@pytest.mark.parametrize("name", ["api_key", "client_secret", "adminPassword", "KEY"])
def test_credential_shaped_field_names_are_refused(name: str) -> None:
    body = copy.deepcopy(BODIES["copilot"])
    body["copilot"][name] = "x"
    assert _reason("copilot", body) == "credential_in_setting"
    top = copy.deepcopy(BODIES["search"])
    top[name] = "x"
    assert _reason("search", top) == "credential_in_setting"


def test_a_secret_uri_reference_outside_credential_is_refused() -> None:
    body = copy.deepcopy(BODIES["copilot"])
    body["copilot"]["secret_uri"] = "https://kv.vault.azure.net/secrets/x"  # noqa: S105
    assert _reason("copilot", body) == "credential_in_setting"


def test_key_vault_reference_is_a_valid_reference_but_model_endpoints_need_mi() -> None:
    kv = {"kind": "key_vault_secret", "secret_uri": "https://ns-kv.vault.azure.net/secrets/s1"}
    assert _reason("copilot", model_body(credential=kv)) == "managed_identity_required"
    target = copy.deepcopy(BODIES["write_targets"])
    target["write_target"]["credential"] = kv
    assert _validate("write_targets", target).write_target is not None


def test_a_government_vault_in_commercial_is_refused() -> None:
    target = copy.deepcopy(BODIES["write_targets"])
    gov_kv = {
        "kind": "key_vault_secret",
        "secret_uri": "https://ns-kv.vault.usgovcloudapi.net/secrets/s",
    }
    target["write_target"]["credential"] = gov_kv
    assert _reason("write_targets", target) == "admin_body_invalid"


@pytest.mark.parametrize("key", ["copilot", "judge"])
def test_commercial_model_endpoint_in_government_is_refused(key: str) -> None:
    assert _reason(key, model_body(key), cloud="government") == "cross_cloud"
    assert _reason(key, model_body(key, GOV_MODEL), cloud="commercial") == "cross_cloud"
    assert _validate(key, model_body(key, GOV_MODEL), cloud="government").setting_key == key


def test_unapproved_model_host_is_refused() -> None:
    body = model_body(endpoint="https://models.example.com")
    assert _reason("copilot", body) == "endpoint_not_approved"


def test_search_endpoint_must_be_on_the_deployment_cloud() -> None:
    gov = search_body("https://ns-search.search.azure.us")
    assert _reason("search", gov) == "cross_cloud"
    assert _reason("search", search_body("https://ns.example.com")) == "search_endpoint_invalid"
    assert _validate("search", gov, cloud="government").search is not None


def test_key_and_member_must_agree() -> None:
    assert _reason("judge", BODIES["copilot"]) == "setting_key_mismatch"
    assert _reason("nope", BODIES["copilot"]) == "unknown_setting_key"
    two = copy.deepcopy(BODIES["copilot"])
    two["judge"] = two["copilot"]
    assert _reason("copilot", two) == "admin_body_invalid"


def test_init_args_map_onto_the_runtime_settings_fields() -> None:
    copilot = _validate("copilot", BODIES["copilot"])
    assert copilot_init_args(copilot, env_mode="disabled") == {
        "mode": "approved_endpoint",
        "endpoint": "https://acct.openai.azure.com",
        "deployment": "gpt-4o",
        "api_version": "2024-10-21",
    }
    assert copilot_init_args(copilot, env_mode="foundry_agent")["mode"] == "foundry_agent"
    off = copilot.model_copy(update={"enabled": False})
    assert copilot_init_args(off, env_mode="approved_endpoint") == {"mode": "disabled"}

    judge = _validate("judge", BODIES["judge"])
    assert judge_init_args(judge)["judge"] == "endpoint"
    assert judge_init_args(judge.model_copy(update={"enabled": False})) == {"judge": "fixture"}

    search = _validate("search", BODIES["search"])
    assert search_init_args(search, cloud="commercial") == {
        "provider": "azure",
        "service": "ns-search",
        "index": "neurosphere-catalog",
    }
    mcp = _validate("mcp_server", BODIES["mcp_server"])
    assert mcp_server_init_args(mcp) == {"resource_server_url": "https://ns.example.com/mcp"}
    assert mcp_server_init_args(mcp.model_copy(update={"enabled": False})) is None
    assert scan_init_args(_validate("scan", scan_body(enabled=False))) == {"enabled": False}
