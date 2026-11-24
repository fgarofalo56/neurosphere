from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi.testclient import TestClient
from neurosphere_api.app import create_app
from neurosphere_api.ingest import (
    IngestSettings,
    InMemoryPublisher,
    ProducerRegistration,
    StaticProducerRegistry,
    build_service,
    configure_ingest,
    hash_secret,
)
from neurosphere_core.cloud import Settings

CUSTOMER = "cust-synthetic"
SOURCE = "src-synthetic"
PRODUCER = "prod-synthetic"
TRACE = "0af7651916cd43dd8448eb211c80319c"


@dataclass
class Harness:
    client: TestClient
    publisher: InMemoryPublisher
    secret: str

    @property
    def auth(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {PRODUCER}.{self.secret}"}


@pytest.fixture
def harness() -> Harness:
    secret = secrets.token_urlsafe(24)  # fake, generated per test
    settings = Settings(env="local")
    publisher = InMemoryPublisher()
    registration = ProducerRegistration(
        producer_id=PRODUCER,
        secret_sha256=hash_secret(secret),
        customer_id=CUSTOMER,
        cloud="commercial",
        sources={SOURCE: "application"},
    )
    service = build_service(
        settings, IngestSettings(), publisher, registry=StaticProducerRegistry([registration])
    )
    app = create_app(settings)
    configure_ingest(app, service)
    return Harness(TestClient(app), publisher, secret)


def attr(key: str, value: Any) -> dict[str, Any]:
    return {"key": key, "value": {"stringValue": value}}


def span(
    attrs: dict[str, Any], *, span_id: str = "b7ad6b7169203331", parent: str = ""
) -> dict[str, Any]:
    return {
        "traceId": TRACE,
        "spanId": span_id,
        "parentSpanId": parent,
        "name": "synthetic",
        "status": {"code": 1},
        "startTimeUnixNano": "1700000000000000000",
        "endTimeUnixNano": "1700000000250000000",
        "attributes": [attr(k, v) for k, v in attrs.items()],
    }


def traces_doc(
    spans: list[dict[str, Any]], resource_attrs: dict[str, Any] | None = None
) -> dict[str, Any]:
    return {
        "resourceSpans": [
            {
                "resource": {"attributes": [attr(k, v) for k, v in (resource_attrs or {}).items()]},
                "scopeSpans": [{"scope": {"name": "synthetic"}, "spans": spans}],
            }
        ]
    }
