"""PRP-45 item 3: refused settings are 422 and nothing is stored (references only, A7)."""

from __future__ import annotations

import copy
from typing import Any

import pytest
from neurosphere_api.admin.system.settings_router import ABSENT_ETAG
from neurosphere_core.admin import InMemoryAdminConfigRepository
from system_harness import (  # pyright: ignore[reportMissingImports]
    SystemWorld,
    configure_env,
    mcp_body,
    model_body,
    search_body,
)


@pytest.fixture(autouse=True)
def _auth(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_env(monkeypatch)


def _refused(world: SystemWorld, key: str, body: Any, reason: str | None) -> None:
    response = world.put(key, body, ABSENT_ETAG)
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "invalid_schema"
    assert response.json().get("reason") == reason
    assert world.repository._docs == {}  # pyright: ignore[reportPrivateUsage]


@pytest.mark.parametrize("name", ["api_key", "client_secret", "admin_password", "AccountKey"])
def test_a_credential_shaped_field_is_refused(name: str) -> None:
    body = copy.deepcopy(model_body())
    body["copilot"][name] = "value-never-stored"
    _refused(SystemWorld.build(), "copilot", body, "credential_in_setting")


def test_a_commercial_endpoint_in_a_government_deployment_is_refused() -> None:
    world = SystemWorld.build(repository=InMemoryAdminConfigRepository(cloud="government"))
    plane = world.composed.app.state.admin_system
    world.composed.app.state.admin_system = type(plane)(**{**plane.__dict__, "cloud": "government"})
    _refused(world, "judge", model_body("judge"), "cross_cloud")
    _refused(world, "copilot", model_body(), "cross_cloud")


def test_a_government_search_endpoint_in_commercial_is_refused() -> None:
    _refused(
        SystemWorld.build(),
        "search",
        search_body("https://ns-search.search.azure.us"),
        "cross_cloud",
    )


def test_a_key_vault_credential_for_a_model_endpoint_is_refused() -> None:
    kv = {"kind": "key_vault_secret", "secret_uri": "https://ns-kv.vault.azure.net/secrets/s1"}
    _refused(SystemWorld.build(), "copilot", model_body(credential=kv), "managed_identity_required")


def test_the_builder_settings_class_refuses_what_the_builder_would() -> None:
    _refused(
        SystemWorld.build(),
        "mcp_server",
        mcp_body("https://ns.example.com/not-mcp"),
        "mcp_server_settings_invalid",
    )


def test_schema_violations_are_refused() -> None:
    world = SystemWorld.build()
    _refused(world, "judge", model_body(), "setting_key_mismatch")
    bad = copy.deepcopy(model_body())
    bad["copilot"]["endpoint"] = "http://acct.openai.azure.com"
    _refused(world, "copilot", bad, "admin_body_invalid")
    _refused(world, "copilot", ["not", "an", "object"], None)  # request validation
