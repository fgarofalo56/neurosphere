"""foundry_discovery is part of ``all``, idles when unconfigured and refuses half-configuration."""

from __future__ import annotations

import logging

import pytest
from neurosphere_core.clients import ClientLifetime
from neurosphere_core.cloud import Settings
from neurosphere_workers.runtime import RoleConfigError, parse_roles
from neurosphere_workers.runtime.adapters import WorkerRole
from neurosphere_workers.runtime.factories import BUILDERS, RuntimeConfig, build_foundry_discovery
from neurosphere_workers.runtime.settings import AuthSettings, StoreSettings, WorkerSettings

_ENV = (
    "NS_FOUNDRY_DISCOVERY_PROJECTS",
    "NS_FOUNDRY_DISCOVERY_DOMAIN_ID",
    "NS_FOUNDRY_DISCOVERY_INTERVAL_SECONDS",
)


def _config() -> RuntimeConfig:
    return RuntimeConfig(Settings(env="local"), WorkerSettings(), StoreSettings(), AuthSettings())


def _clear(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _ENV:
        monkeypatch.delenv(name, raising=False)


def test_role_is_in_all_and_registered() -> None:
    assert "foundry_discovery" in parse_roles("all")
    assert BUILDERS["foundry_discovery"] is build_foundry_discovery


async def test_unconfigured_role_idles_with_one_info_log(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _clear(monkeypatch)
    with caplog.at_level(logging.INFO):
        async with ClientLifetime() as lifetime:
            role = await build_foundry_discovery(_config(), lifetime)
    assert isinstance(role, WorkerRole)
    events = [getattr(r, "event", None) for r in caplog.records]
    assert events.count("worker.foundry_discovery_unconfigured") == 1


async def test_projects_without_domain_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("NS_FOUNDRY_DISCOVERY_PROJECTS", "res1/proj1")
    async with ClientLifetime() as lifetime:
        with pytest.raises(RoleConfigError) as caught:
            await build_foundry_discovery(_config(), lifetime)
    assert caught.value.reason == "foundry_discovery_domain_id_missing"


async def test_domain_without_projects_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("NS_FOUNDRY_DISCOVERY_DOMAIN_ID", "d1")
    async with ClientLifetime() as lifetime:
        with pytest.raises(RoleConfigError) as caught:
            await build_foundry_discovery(_config(), lifetime)
    assert caught.value.reason == "foundry_discovery_projects_missing"


async def test_non_canonical_domain_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("NS_FOUNDRY_DISCOVERY_PROJECTS", "res1/proj1")
    monkeypatch.setenv("NS_FOUNDRY_DISCOVERY_DOMAIN_ID", "d1")
    async with ClientLifetime() as lifetime:
        with pytest.raises(RoleConfigError) as caught:
            await build_foundry_discovery(_config(), lifetime)
    assert caught.value.reason == "foundry_discovery_domain_id_invalid"


async def test_malformed_project_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("NS_FOUNDRY_DISCOVERY_PROJECTS", "noslash")
    monkeypatch.setenv("NS_FOUNDRY_DISCOVERY_DOMAIN_ID", "commercial:synthco:neurosphere:domain:d1")
    async with ClientLifetime() as lifetime:
        with pytest.raises(RoleConfigError) as caught:
            await build_foundry_discovery(_config(), lifetime)
    assert caught.value.reason == "foundry_discovery_projects_invalid"
