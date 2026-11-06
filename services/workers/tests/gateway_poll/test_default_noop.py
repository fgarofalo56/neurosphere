"""gateway_poll is part of ``all`` and is a safe no-op when no gateway polling is configured."""

from __future__ import annotations

import logging

import pytest
from neurosphere_core.clients import ClientLifetime
from neurosphere_core.cloud import Settings
from neurosphere_workers.runtime import RoleConfigError, parse_roles
from neurosphere_workers.runtime.adapters import WorkerRole
from neurosphere_workers.runtime.factories import RuntimeConfig, build_gateway_poll
from neurosphere_workers.runtime.settings import AuthSettings, StoreSettings, WorkerSettings

_POLL_ENV = (
    "NS_GATEWAY_POLL_DOMAIN_IDS",
    "NS_GATEWAY_POLL_PRODUCER_SECRET",
    "NS_GATEWAY_POLL_API_BASE_URL",
    "NS_API_BASE_URL",
)


def _config() -> RuntimeConfig:
    return RuntimeConfig(Settings(env="local"), WorkerSettings(), StoreSettings(), AuthSettings())


def _clear(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _POLL_ENV:
        monkeypatch.delenv(name, raising=False)


def test_all_includes_gateway_poll() -> None:
    assert "gateway_poll" in parse_roles("all")


async def test_unconfigured_role_builds_a_noop_without_raising(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _clear(monkeypatch)
    with caplog.at_level(logging.INFO):
        async with ClientLifetime() as lifetime:
            role = await build_gateway_poll(_config(), lifetime)
    assert isinstance(role, WorkerRole)
    events = [getattr(r, "event", None) for r in caplog.records]
    assert events.count("worker.gateway_poll_unconfigured") == 1


async def test_partial_config_is_still_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("NS_GATEWAY_POLL_DOMAIN_IDS", "d1")
    async with ClientLifetime() as lifetime:
        with pytest.raises(RoleConfigError) as caught:
            await build_gateway_poll(_config(), lifetime)
    assert caught.value.reason == "gateway_poll_api_base_url_missing"
