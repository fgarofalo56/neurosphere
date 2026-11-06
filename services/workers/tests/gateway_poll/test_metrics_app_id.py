"""NS_GATEWAY_POLL_METRICS_APP_ID: parse, validation, factory wiring and the Government skip."""

from __future__ import annotations

import logging
from typing import Any, ClassVar

import pytest
from neurosphere_core.clients import ClientLifetime
from neurosphere_core.cloud import Settings
from neurosphere_core.cloud.profile import CloudName
from neurosphere_workers.ingestion.gateway_poll import GatewayPollSettings
from neurosphere_workers.runtime import factories
from neurosphere_workers.runtime.factories import RuntimeConfig, build_gateway_poll
from neurosphere_workers.runtime.settings import AuthSettings, StoreSettings, WorkerSettings
from pydantic import ValidationError

_APP_ID = "0f8fad5b-d9cb-469f-a165-70867728950e"
_VAR = "NS_GATEWAY_POLL_METRICS_APP_ID"


class _Capture:
    kwargs: ClassVar[dict[str, Any]] = {}

    def __init__(self, **kwargs: Any) -> None:
        type(self).kwargs = kwargs

    async def tick(self) -> None:
        return None


class _Store:
    @staticmethod
    def from_client(*_: Any, **__: Any) -> object:
        return object()


def _config(cloud: CloudName | None = None) -> RuntimeConfig:
    return RuntimeConfig(
        Settings(env="local", cloud=cloud), WorkerSettings(), StoreSettings(), AuthSettings()
    )


def _wire(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _cosmos(*_: Any) -> object:
        return object()

    async def _create(*_: Any) -> None:
        return None

    monkeypatch.setenv("NS_GATEWAY_POLL_DOMAIN_IDS", "d1")
    monkeypatch.setenv("NS_GATEWAY_POLL_PRODUCER_SECRET", "x")
    monkeypatch.setenv("NS_API_BASE_URL", "http://api.test")
    monkeypatch.setattr(factories, "_cosmos", _cosmos)
    monkeypatch.setattr(factories, "_database", lambda *_: object())
    monkeypatch.setattr(factories, "create_gateway_container", _create)
    monkeypatch.setattr(factories, "CosmosGatewayStore", _Store)
    monkeypatch.setattr(factories, "GatewayPoller", _Capture)


def test_settings_parse_app_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_VAR, f"  {_APP_ID} ")
    assert GatewayPollSettings().metrics_app_id == _APP_ID


def test_settings_unset_and_blank_are_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(_VAR, raising=False)
    assert GatewayPollSettings().metrics_app_id is None
    monkeypatch.setenv(_VAR, "  ")
    assert GatewayPollSettings().metrics_app_id is None


def test_settings_reject_non_guid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_VAR, "not-a-guid")
    with pytest.raises(ValidationError):
        GatewayPollSettings()


async def test_factory_passes_app_id_through(monkeypatch: pytest.MonkeyPatch) -> None:
    _wire(monkeypatch)
    monkeypatch.setenv(_VAR, _APP_ID)
    async with ClientLifetime() as lifetime:
        await build_gateway_poll(_config(), lifetime)
    assert _Capture.kwargs["metrics_app_id"] == _APP_ID


async def test_factory_unset_leaves_none(monkeypatch: pytest.MonkeyPatch) -> None:
    _wire(monkeypatch)
    monkeypatch.delenv(_VAR, raising=False)
    async with ClientLifetime() as lifetime:
        await build_gateway_poll(_config(), lifetime)
    assert _Capture.kwargs["metrics_app_id"] is None


async def test_government_skips_metrics_poll_with_one_warning(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _wire(monkeypatch)
    monkeypatch.setenv(_VAR, _APP_ID)
    with caplog.at_level(logging.WARNING):
        async with ClientLifetime() as lifetime:
            await build_gateway_poll(_config(CloudName.GOVERNMENT), lifetime)
    assert _Capture.kwargs["metrics_app_id"] is None
    events = [getattr(r, "event", None) for r in caplog.records]
    assert events.count("worker.gateway_poll_metrics_government_skipped") == 1
