"""PRP-45 item 4: the API builders read the stored-settings snapshot over env (A1, A2, A5)."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi import FastAPI
from neurosphere_api.admin.system.stored import (
    STORED_SETTINGS,
    load_from_settings,
    setting_source,
    snapshot_for_composition,
)
from neurosphere_api.app import create_app
from neurosphere_api.deploy.scan import configure_scan_from_settings
from neurosphere_api.runtime import CompositionOverrides
from neurosphere_api.runtime.builders import copilot as copilot_builder
from neurosphere_api.runtime.builders import mcp as mcp_builder
from neurosphere_api.runtime.builders import search as search_builder
from neurosphere_core.admin import InMemoryAdminConfigRepository
from neurosphere_core.admin.runtime import (
    StoredSettingsSnapshot,
    snapshot_from_documents,
)
from neurosphere_core.cloud import Settings
from neurosphere_core.errors import DependencyTransientError
from system_harness import (  # pyright: ignore[reportMissingImports]
    SystemWorld,
    configure_env,
    mcp_body,
    model_body,
    scan_body,
    search_body,
    seed,
)


@pytest.fixture(autouse=True)
def _auth(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_env(monkeypatch)


def _snapshot(**bodies: dict[str, Any]) -> StoredSettingsSnapshot:
    repository = InMemoryAdminConfigRepository(cloud="commercial")
    docs = [seed(repository, key, body) for key, body in bodies.items()]
    return snapshot_from_documents(docs, customer_id="contoso", cloud="commercial")


@dataclass
class _Ctx:
    """The slice of ``BuildContext`` the settings helpers read."""

    snapshot: StoredSettingsSnapshot | None
    settings: Settings

    def maybe_shared(self, key: Any) -> Any:
        assert key is STORED_SETTINGS
        return self.snapshot


def _ctx(snapshot: StoredSettingsSnapshot | None) -> Any:
    return _Ctx(snapshot, Settings(env="local"))


def test_stored_copilot_beats_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NS_COPILOT_MODE", "foundry_agent")
    monkeypatch.setenv("NS_COPILOT_ENDPOINT", "https://env.services.ai.azure.com")
    monkeypatch.setenv("NS_COPILOT_REGION", "eastus2")
    settings = copilot_builder._runtime_settings(_ctx(_snapshot(copilot=model_body())))  # pyright: ignore[reportPrivateUsage]
    assert settings.mode == "foundry_agent"  # an enabled stored value keeps the env mode
    assert settings.endpoint == "https://acct.openai.azure.com"
    assert settings.deployment == "gpt-4o" and settings.region == "eastus2"
    off = copy.deepcopy(model_body())
    off["enabled"] = False
    disabled = copilot_builder._runtime_settings(_ctx(_snapshot(copilot=off)))  # pyright: ignore[reportPrivateUsage]
    assert disabled.mode == "disabled"
    env_only = copilot_builder._runtime_settings(_ctx(None))  # pyright: ignore[reportPrivateUsage]
    assert env_only.endpoint == "https://env.services.ai.azure.com"


def test_stored_search_beats_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NS_SEARCH_PROVIDER", "fixture")
    monkeypatch.setenv("NS_SEARCH_REGION", "eastus2")
    settings = search_builder._search_settings(_ctx(_snapshot(search=search_body())))  # pyright: ignore[reportPrivateUsage]
    assert (settings.provider, settings.service, settings.index) == (
        "azure",
        "ns-search",
        "stored-index",
    )
    assert settings.region == "eastus2"
    assert search_builder._search_settings(_ctx(None)).provider == "fixture"  # pyright: ignore[reportPrivateUsage]


def test_stored_mcp_server_beats_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NS_MCP_RESOURCE_SERVER_URL", "https://env.example.com/mcp")
    applies, settings = mcp_builder._stored_settings(_ctx(_snapshot(mcp_server=mcp_body())))  # pyright: ignore[reportPrivateUsage]
    assert applies and settings is not None
    assert settings.resource_server_url == "https://ns.example.com/mcp"
    off = mcp_builder._stored_settings(_ctx(_snapshot(mcp_server=mcp_body(enabled=False))))  # pyright: ignore[reportPrivateUsage]
    assert off == (True, None)
    assert mcp_builder._stored_settings(_ctx(None)) == (False, None)  # pyright: ignore[reportPrivateUsage]


def test_composition_applies_stored_settings_and_reports_source_stored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NS_MCP_RESOURCE_SERVER_URL", "https://env.example.com/mcp")
    monkeypatch.setenv("NS_COPILOT_MODE", "approved_endpoint")
    repository = InMemoryAdminConfigRepository(cloud="commercial")
    off_copilot = copy.deepcopy(model_body())
    off_copilot["enabled"] = False
    seed(repository, "copilot", off_copilot)
    seed(repository, "mcp_server", mcp_body(enabled=False))
    world = SystemWorld.build(
        repository=repository, extra=(copilot_builder.BUILDER, mcp_builder.BUILDER)
    )
    registry = world.composed.registry
    assert registry.get("copilot").state == "disabled"  # env said approved_endpoint
    assert registry.get("mcp_server").state == "disabled"  # env named a resource URL
    items = {i["key"]: i for i in world.get("/settings").json()["items"]}
    assert items["copilot"]["source"] == items["mcp_server"]["source"] == "stored"


def test_unreachable_store_at_startup_falls_back_to_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NS_MCP_RESOURCE_SERVER_URL", "https://env.example.com/mcp")
    repository = InMemoryAdminConfigRepository(cloud="commercial")
    seed(repository, "mcp_server", mcp_body(enabled=False))
    repository.fail_with(DependencyTransientError("down", reason="admin_config_unavailable"))
    world = SystemWorld.build(repository=repository, extra=(mcp_builder.BUILDER,))
    # env applies: the server is configured from NS_MCP_* (it then fails on the missing tenant
    # wiring of this stub composition, which is not "disabled").
    assert world.composed.registry.get("mcp_server").state != "disabled"
    snapshot = world.composed.app.state.admin_system.applied
    assert snapshot.status == "unavailable"
    assert setting_source("mcp_server", snapshot) == "env"


def test_no_stored_settings_changes_nothing() -> None:
    world = SystemWorld.build(extra=(copilot_builder.BUILDER, mcp_builder.BUILDER))
    assert world.composed.registry.get("copilot").state == "disabled"
    assert world.composed.registry.get("mcp_server").state == "disabled"


def test_scan_bootstrap_reads_the_stored_scan_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NS_SCAN_ENABLED", "true")
    app = FastAPI()
    settings = Settings(env="local")
    off = _snapshot(scan=scan_body(enabled=False))
    assert configure_scan_from_settings(app, settings, stored=off) is False
    empty = StoredSettingsSnapshot.empty("loaded")
    assert configure_scan_from_settings(app, settings, stored=empty) is True


def test_production_read_without_cosmos_configuration_is_unconfigured() -> None:
    snapshot = load_from_settings(Settings(env="local"))  # NS_COSMOS_KEY is cleared
    assert snapshot.status == "unconfigured"
    assert snapshot.reason == "stored_settings_unconfigured"
    dev = load_from_settings(Settings(env="dev", cloud="commercial"))  # type: ignore[arg-type]  # no account
    assert dev.status == "unconfigured"


def test_composition_overrides_never_reach_a_real_store() -> None:
    settings = Settings(env="local")
    assert snapshot_for_composition(settings, CompositionOverrides()).status == "unconfigured"
    prebuilt = StoredSettingsSnapshot.empty("loaded")
    overrides = CompositionOverrides(backends={"stored_settings": prebuilt})
    assert snapshot_for_composition(settings, overrides) is prebuilt


def test_create_app_alone_has_no_admin_system_state() -> None:
    app = create_app(Settings(env="local"))
    assert getattr(app.state, "admin_system", None) is None
