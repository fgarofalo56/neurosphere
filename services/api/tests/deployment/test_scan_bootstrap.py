"""``configure_scan_from_settings``: opt-in wiring, fail closed when unset. No network."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import pytest
from authz.authz_helpers import Harness  # pyright: ignore[reportMissingImports]
from fastapi.testclient import TestClient
from neurosphere_api import main
from neurosphere_api.app import create_app
from neurosphere_api.deploy.scan import (
    ScanSettings,
    build_router,
    configure_scan_from_settings,
)
from neurosphere_api.deploy.scan import bootstrap as bootstrap_module
from neurosphere_core.cloud import CloudName, Settings

from .conftest import ADMIN, FakeCredential


class ClosableCredential(FakeCredential):
    def __init__(self) -> None:
        super().__init__()
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class CredentialSpy:
    def __init__(self) -> None:
        self.kwargs: list[dict[str, Any]] = []
        self.made: list[ClosableCredential] = []

    def __call__(self, **kwargs: Any) -> ClosableCredential:
        self.kwargs.append(kwargs)
        cred = ClosableCredential()
        self.made.append(cred)
        return cred


@pytest.fixture
def spy(monkeypatch: pytest.MonkeyPatch) -> CredentialSpy:
    """Replace ``DefaultAzureCredential`` in the bootstrap module; records constructor kwargs."""
    fake = CredentialSpy()
    monkeypatch.setattr(bootstrap_module, "DefaultAzureCredential", fake)
    return fake


def _reader(app: Any) -> Any:
    return app.state.scan_service._reader  # pyright: ignore[reportPrivateUsage]


def test_disabled_by_default_returns_false_and_route_is_503(
    mount: Callable[[dict[str, Any]], Harness], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("NS_SCAN_ENABLED", raising=False)
    h = mount({"/v1/deploy/scan": build_router()})
    assert configure_scan_from_settings(h.app, Settings(env="local")) is False
    assert not hasattr(h.app.state, "scan_service")
    sub = "11111111-1111-1111-1111-111111111111"
    consent = {"consent_id": "c-1", "consented_by": "o@example.com"}
    body = {"consent": {**consent, "consented_subscriptions": [sub]}, "subscription_ids": [sub]}
    resp = h.client.post("/v1/deploy/scan", json=body, headers=h.auth(ADMIN))
    assert resp.status_code == 503
    assert resp.json()["reason"] == "scan_not_configured"


def test_main_create_leaves_scan_unconfigured_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NS_ENV", "local")
    monkeypatch.delenv("NS_SCAN_ENABLED", raising=False)
    monkeypatch.delenv("NS_INGEST_PRODUCERS_FILE", raising=False)
    assert not hasattr(main.create().state, "scan_service")


def test_main_create_wires_scan_when_enabled(
    monkeypatch: pytest.MonkeyPatch, spy: CredentialSpy
) -> None:
    monkeypatch.setenv("NS_ENV", "local")
    monkeypatch.setenv("NS_SCAN_ENABLED", "true")
    monkeypatch.delenv("NS_INGEST_PRODUCERS_FILE", raising=False)
    assert hasattr(main.create().state, "scan_service")
    assert len(spy.made) == 1


@pytest.mark.parametrize(
    ("cloud", "host"),
    [
        (CloudName.COMMERCIAL, "management.azure.com"),
        (CloudName.GOVERNMENT, "management.usgovcloudapi.net"),
    ],
)
def test_enabled_targets_profile_management_host(
    cloud: CloudName, host: str, spy: CredentialSpy
) -> None:
    settings = Settings(env="test", cloud=cloud)
    app = create_app(settings)
    assert configure_scan_from_settings(app, settings, ScanSettings(enabled=True)) is True
    base = _reader(app)._base  # pyright: ignore[reportPrivateUsage]
    assert base == f"https://{host}/"
    if cloud is CloudName.GOVERNMENT:
        assert ".com" not in base
    assert spy.kwargs[0]["authority"] == settings.cloud_profile.login_host
    # Outside local the secret-bearing environment credential is excluded.
    assert spy.kwargs[0]["exclude_environment_credential"] is True


def test_local_keeps_developer_chain(spy: CredentialSpy) -> None:
    settings = Settings(env="local")
    app = create_app(settings)
    assert configure_scan_from_settings(app, settings, ScanSettings(enabled=True)) is True
    assert spy.kwargs[0]["exclude_environment_credential"] is False


def test_shutdown_closes_client_and_credential(spy: CredentialSpy) -> None:
    settings = Settings(env="test", cloud=CloudName.COMMERCIAL)
    app = create_app(settings)
    configure_scan_from_settings(app, settings, ScanSettings(enabled=True))
    client: httpx.AsyncClient = _reader(app)._client  # pyright: ignore[reportPrivateUsage]
    assert not client.is_closed
    assert not spy.made[0].closed
    with TestClient(app):
        pass
    assert client.is_closed
    assert spy.made[0].closed


def test_no_secret_bearing_setting_exists() -> None:
    """The scan path is keyless: there is no secret-bearing setting to refuse outside local."""
    words = ("secret", "key", "password", "token", "connection")
    assert not [n for n in ScanSettings.model_fields if any(w in n for w in words)]
