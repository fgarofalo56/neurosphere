"""``configure_ingest_from_settings``: opt-in wiring, fail closed when unset. No real clients."""

from __future__ import annotations

import json
import secrets
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from neurosphere_api.app import create_app
from neurosphere_api.ingest import IngestService, IngestSettings, hash_secret
from neurosphere_api.ingest import bootstrap as bootstrap_module
from neurosphere_api.ingest.bootstrap import configure_ingest_from_settings
from neurosphere_core.cloud import Settings

EVENTS = "/v1/ingest/events"
CE = {"content-type": "application/cloudevents+json"}


class FakeProducer:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


@pytest.fixture
def fake_producer(monkeypatch: pytest.MonkeyPatch) -> FakeProducer:
    producer = FakeProducer()
    calls: list[dict[str, Any]] = []

    def fake_create(settings: Settings, **kwargs: Any) -> FakeProducer:
        calls.append(kwargs)
        kwargs["lifetime"].register(producer)
        return producer

    monkeypatch.setattr(bootstrap_module, "create_eventhub_producer", fake_create)
    producer.calls = calls  # type: ignore[attr-defined]
    return producer


def producers_file(tmp_path: Path) -> Path:
    path = tmp_path / "producers.json"
    doc = {
        "producers": [
            {
                "producer_id": "prod-boot",
                "secret_sha256": hash_secret(secrets.token_urlsafe(16)),
                "customer_id": "cust-boot",
                "cloud": "commercial",
                "sources": {"src-boot": "application"},
            }
        ]
    }
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def test_unset_does_nothing_and_routes_stay_503(fake_producer: FakeProducer) -> None:
    settings = Settings(env="local")
    app = create_app(settings)
    assert configure_ingest_from_settings(app, settings, IngestSettings()) is False
    assert not hasattr(app.state, "ingest_service")
    assert not fake_producer.calls  # type: ignore[attr-defined]
    response = TestClient(app).post(EVENTS, headers=CE, content=b"{}")
    assert response.status_code == 503


def test_set_configures_service_and_returns_true(
    tmp_path: Path, fake_producer: FakeProducer
) -> None:
    settings = Settings(env="local")
    app = create_app(settings)
    conf = IngestSettings(producers_file=producers_file(tmp_path))
    assert configure_ingest_from_settings(app, settings, conf) is True
    assert isinstance(app.state.ingest_service, IngestService)
    assert fake_producer.calls[0]["eventhub_name"] == "telemetry"  # type: ignore[attr-defined]
    # Configured: an unauthenticated request now fails authentication (401), not 503.
    assert TestClient(app).post(EVENTS, headers=CE, content=b"{}").status_code == 401


def test_publisher_is_closed_on_shutdown(tmp_path: Path, fake_producer: FakeProducer) -> None:
    settings = Settings(env="local")
    app: FastAPI = create_app(settings)
    configure_ingest_from_settings(
        app, settings, IngestSettings(producers_file=producers_file(tmp_path))
    )
    with TestClient(app):
        assert fake_producer.closed is False
    assert fake_producer.closed is True


def test_bad_producers_file_fails_fast(tmp_path: Path, fake_producer: FakeProducer) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{}", encoding="utf-8")
    settings = Settings(env="local")
    app = create_app(settings)
    with pytest.raises(KeyError):
        configure_ingest_from_settings(app, settings, IngestSettings(producers_file=bad))
    assert not hasattr(app.state, "ingest_service")
