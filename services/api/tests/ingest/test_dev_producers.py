"""The compose dev producers file (infra/dev/ingest-producers.dev.json) yields a working edge."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from neurosphere_api.app import create_app
from neurosphere_api.ingest import IngestSettings
from neurosphere_api.ingest import bootstrap as bootstrap_module
from neurosphere_api.ingest.bootstrap import configure_ingest_from_settings
from neurosphere_api.ingest.publisher import InMemoryPublisher
from neurosphere_api.ingest.router import build_service
from neurosphere_core.cloud import Settings

from .conftest import span, traces_doc

DEV_FILE = Path(__file__).resolve().parents[4] / "infra" / "dev" / "ingest-producers.dev.json"
# Documented throwaway dev-only secret (docs/runbooks/ingest.md); the file holds only its digest.
DEV_SECRET = "ns-dev-only-ingest-secret"  # noqa: S105
URL = "/v1/ingest/otlp/traces"


def test_dev_file_holds_only_digests() -> None:
    text = DEV_FILE.read_text(encoding="utf-8")
    assert DEV_SECRET not in text
    doc = json.loads(text)
    for producer in doc["producers"]:
        assert set(producer) == {"producer_id", "secret_sha256", "customer_id", "cloud", "sources"}
        assert re.fullmatch(r"[0-9a-f]{64}", producer["secret_sha256"])


def test_dev_producer_posts_2xx_via_bootstrap(monkeypatch: pytest.MonkeyPatch) -> None:
    publisher = InMemoryPublisher()
    real_build = build_service

    def build(settings: Settings, conf: IngestSettings, _pub: Any, **kw: Any) -> Any:
        return real_build(settings, conf, publisher, **kw)

    class _Producer:
        async def close(self) -> None: ...

    def fake_create(settings: Settings, **kwargs: Any) -> _Producer:
        producer = _Producer()
        kwargs["lifetime"].register(producer)
        return producer

    monkeypatch.setattr(bootstrap_module, "create_eventhub_producer", fake_create)
    monkeypatch.setattr(bootstrap_module, "build_service", build)
    settings = Settings(env="local")
    app = create_app(settings)
    conf = IngestSettings(producers_file=DEV_FILE)
    assert configure_ingest_from_settings(app, settings, conf) is True

    resp = TestClient(app).post(
        URL,
        content=json.dumps(traces_doc([span()])),
        headers={
            "content-type": "application/json",
            "Authorization": f"Bearer dev-ingest.{DEV_SECRET}",
        },
    )
    assert resp.status_code == 202, resp.text
    assert resp.json()["accepted"] == 1


def test_unset_keeps_503_ingest_not_configured() -> None:
    app = create_app(Settings(env="local"))
    resp = TestClient(app).post(URL, content=b"{}", headers={"content-type": "application/json"})
    assert resp.status_code == 503
    assert "ingest_not_configured" in resp.text
