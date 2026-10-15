from __future__ import annotations

import secrets
from collections.abc import Callable
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
from neurosphere_api.ingest.limits import TokenBucketLimiter
from neurosphere_api.ingest.service import IngestService
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
    service: IngestService

    @property
    def auth(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {PRODUCER}.{self.secret}"}


def registration(secret: str, **overrides: Any) -> ProducerRegistration:
    fields: dict[str, Any] = {
        "producer_id": PRODUCER,
        "secret_sha256": hash_secret(secret),
        "customer_id": CUSTOMER,
        "cloud": "commercial",
        "sources": {SOURCE: "application"},
    }
    fields.update(overrides)
    return ProducerRegistration(**fields)


@pytest.fixture
def make_harness() -> Callable[..., Harness]:
    def build(
        *,
        reg: dict[str, Any] | None = None,
        edge_env: Settings | None = None,
        ingest: IngestSettings | None = None,
        limiter: TokenBucketLimiter | None = None,
    ) -> Harness:
        secret = secrets.token_urlsafe(24)  # fake, generated per test
        settings = edge_env or Settings(env="local")
        ingest_settings = ingest or IngestSettings()
        publisher = InMemoryPublisher()
        service = build_service(
            settings,
            ingest_settings,
            publisher,
            registry=StaticProducerRegistry([registration(secret, **(reg or {}))]),
        )
        if limiter is not None:
            service._limiter = limiter
        app = create_app(settings)
        configure_ingest(app, service)
        return Harness(TestClient(app), publisher, secret, service)

    return build


@pytest.fixture
def harness(make_harness: Callable[..., Harness]) -> Harness:
    return make_harness()


def span(
    *,
    span_id: str = "b7ad6b7169203331",
    parent: str = "",
    attrs: dict[str, Any] | None = None,
    status: int = 1,
    start: str | None = "1700000000000000000",
    end: str | None = "1700000000250000000",
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "traceId": TRACE,
        "spanId": span_id,
        "parentSpanId": parent,
        "name": "chat synthetic",
        "status": {"code": status},
        "attributes": [attr(k, v) for k, v in (attrs or {}).items()],
    }
    if start is not None:
        out["startTimeUnixNano"] = start
    if end is not None:
        out["endTimeUnixNano"] = end
    return out


def attr(key: str, value: Any) -> dict[str, Any]:
    if isinstance(value, bool):
        return {"key": key, "value": {"boolValue": value}}
    if isinstance(value, int):
        return {"key": key, "value": {"intValue": str(value)}}
    return {"key": key, "value": {"stringValue": value}}


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
