"""PRP-51: the Cosmos container step runs in the background; ``pending`` blocks ``/readyz``."""

from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass
from typing import Any

import pytest
from neurosphere_api.runtime import compose as compose_module
from neurosphere_api.runtime.status import ComponentRegistry
from neurosphere_core.cloud import Settings

from .runtime_helpers import FakeCosmosClient, FakeDatabase, authz_only, compose

PENDING = "composition.cosmos_containers.pending"


@dataclass
class HangingCosmosClient(FakeCosmosClient):
    """``create_database_if_not_exists`` blocks until ``release`` is set (a hung verify)."""

    release: threading.Event | None = None

    async def create_database_if_not_exists(self, id: str, **kw: Any) -> FakeDatabase:
        assert self.release is not None
        while not self.release.is_set():  # noqa: ASYNC110 - a thread Event, not awaitable
            await asyncio.sleep(0.01)
        return await super().create_database_if_not_exists(id, **kw)


def _patch(monkeypatch: pytest.MonkeyPatch, fake: FakeCosmosClient) -> None:
    monkeypatch.setattr(compose_module, "create_cosmos_client", lambda settings, **kw: fake)


def test_a_hung_verify_never_delays_startup_and_blocks_readiness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = threading.Event()
    _patch(monkeypatch, HangingCosmosClient(release=release))
    monkeypatch.setattr(compose_module, "STARTUP_GRACE_SECONDS", 0.05)
    composed = compose(builders=authz_only(), settings=Settings(env="local"))
    started = time.monotonic()
    with composed.client() as client:
        assert time.monotonic() - started < 5.0
        assert client.get("/healthz").status_code == 200
        response = client.get("/readyz")
        assert response.status_code == 503
        assert response.json()["dependencies"][PENDING] == "unavailable"
        assert composed.registry.get("cosmos_containers").state == "pending"
        release.set()
        deadline = time.monotonic() + 10
        deps: dict[str, str] = {PENDING: "unavailable"}
        while PENDING in deps and time.monotonic() < deadline:
            time.sleep(0.05)
            deps = client.get("/readyz").json()["dependencies"]
        assert PENDING not in deps
        assert composed.registry.get("cosmos_containers").state == "ok"


def test_a_fast_verify_settles_before_the_first_request(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeCosmosClient()
    _patch(monkeypatch, fake)
    composed = compose(builders=authz_only(), settings=Settings(env="local"))
    with composed.client() as client:
        deps = client.get("/readyz").json()["dependencies"]
    assert PENDING not in deps
    assert composed.registry.get("cosmos_containers").state == "ok"


def test_only_a_step_can_be_pending() -> None:
    registry = ComponentRegistry()
    registry.pending("cosmos_containers")
    assert registry.get("cosmos_containers").blocks_readiness
    assert registry.get("cosmos_containers").code == "pending"
    with pytest.raises(ValueError, match="only a startup step"):
        registry.pending("authz")


def test_api_settings_refuse_a_url_as_the_cosmos_account(monkeypatch: pytest.MonkeyPatch) -> None:
    from neurosphere_api.runtime.settings import StoreSettings
    from pydantic import ValidationError

    monkeypatch.setenv("NS_STORE_COSMOS_ACCOUNT", "https://x.documents.azure.com:443/")
    with pytest.raises(ValidationError) as refused:
        StoreSettings()
    assert "documents.azure.com" not in str(refused.value)
