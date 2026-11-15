"""PRP-41 item 4: edge builder composition, startup refresh and the bootstrap switch."""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient
from neurosphere_api.app import create_app
from neurosphere_api.ingest import IngestService, IngestSettings
from neurosphere_api.ingest import bootstrap as bootstrap_module
from neurosphere_api.ingest.auth import ProducerRegistration, StaticProducerRegistry, hash_secret
from neurosphere_api.ingest.bootstrap import configure_ingest_from_settings
from neurosphere_api.ingest.producer_store import ProducerStoreSettings, StoreProducerRegistry
from neurosphere_api.runtime.status import OPTIONAL_COMPONENTS
from neurosphere_core.cloud import Settings
from neurosphere_core.errors import DependencyTransientError
from producer_harness import (  # pyright: ignore[reportMissingImports]
    BASE,
    CUSTOMER_ADMIN,
    EVENTS,
    ProducerWorld,
    configure_env,
    telemetry_event,
)

CE = {"content-type": "application/cloudevents+json"}
CREATE: dict[str, Any] = {
    "producer_id": "poller-1",
    "cloud": "commercial",
    "sources": {"src-app": "application"},
}


@pytest.fixture(autouse=True)
def _auth(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_env(monkeypatch)


def post_event(c: TestClient, producer: str, secret: str) -> int:
    return c.post(
        EVENTS,
        content=json.dumps(telemetry_event("src-app")),
        headers={**CE, "Authorization": f"Bearer {producer}.{secret}"},
    ).status_code


def test_component_is_optional() -> None:
    assert "admin_producers" in OPTIONAL_COMPONENTS


def test_switch_off_disables_component_and_routes_fail_closed() -> None:
    world = ProducerWorld.build(with_store=False)
    assert world.composed.registry.get("admin_producers").state == "disabled"
    assert world.composed.registry.get("ingest").state == "ok"  # ingest itself is unaffected
    response = world.composed.client().get(BASE, headers=world.auth(CUSTOMER_ADMIN))
    assert response.status_code == 503
    assert "admin_producers_unconfigured" in response.text


def test_new_replica_picks_up_existing_producers_at_startup() -> None:
    first = ProducerWorld.build()
    created = first.composed.client().post(BASE, json=CREATE, headers=first.auth(CUSTOMER_ADMIN))
    secret = created.json()["secret"]
    second = ProducerWorld.build(repository=first.repository)
    with TestClient(second.composed.app) as c:  # lifespan runs the startup refresh
        assert post_event(c, "poller-1", secret) == 202


def test_store_outage_at_startup_keeps_app_up_and_file_producers_working() -> None:
    file_secret = hash_secret("fixture-b")[:32]  # computed, not a literal
    fallback = StaticProducerRegistry(
        [
            ProducerRegistration(
                producer_id="file-p",
                secret_sha256=hash_secret(file_secret),
                customer_id="contoso",
                cloud="commercial",
                sources={"src-app": "application"},
            )
        ]
    )
    world = ProducerWorld.build(fallback=fallback)
    world.repository.fail_with(DependencyTransientError("down", reason="admin_config_unavailable"))
    with TestClient(world.composed.app) as c:
        assert post_event(c, "file-p", file_secret) == 202
        assert post_event(c, "store-only", "whatever-secret") == 401
    assert world.store.last_reason == "producer_store_unavailable"


class _FakeEventHubProducer:
    async def close(self) -> None:
        return None


@pytest.fixture
def fake_hub(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_create(settings: Settings, **kwargs: Any) -> _FakeEventHubProducer:
        producer = _FakeEventHubProducer()
        kwargs["lifetime"].register(producer)
        return producer

    monkeypatch.setattr(bootstrap_module, "create_eventhub_producer", fake_create)


def test_bootstrap_store_switch_without_file(fake_hub: None) -> None:
    settings = Settings(env="local")
    app = create_app(settings)
    on = ProducerStoreSettings(store=True)
    assert configure_ingest_from_settings(app, settings, IngestSettings(), on) is True
    assert isinstance(app.state.ingest_service, IngestService)
    assert isinstance(app.state.ingest_producer_store, StoreProducerRegistry)


def test_bootstrap_neither_set_stays_503(fake_hub: None) -> None:
    settings = Settings(env="local")
    app = create_app(settings)
    assert configure_ingest_from_settings(app, settings, IngestSettings()) is False
    assert not hasattr(app.state, "ingest_producer_store")
    assert TestClient(app).post(EVENTS, headers=CE, content=b"{}").status_code == 503
