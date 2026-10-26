"""Shared table and helpers for the PRP-29 item 4 path-alias tests.

The moved operations are read from the real factory app (``create_app``), so a route added to a
moved router later is covered without editing this module.
"""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from typing import Any, Final

from fastapi import FastAPI
from fastapi.routing import iter_route_contexts
from neurosphere_api.app import create_app
from neurosphere_api.audit.router import ALIAS_PREFIX as AUDIT_ALIAS
from neurosphere_api.audit.router import ROUTE_PREFIX as AUDIT_PREFIX
from neurosphere_api.catalog.curation.router import ALIAS_PREFIX as CURATION_ALIAS
from neurosphere_api.catalog.curation.router import PREFIX as CURATION_PREFIX
from neurosphere_api.catalog.router import ALIAS_PREFIX as CATALOG_ALIAS
from neurosphere_api.catalog.router import PREFIX as CATALOG_PREFIX
from neurosphere_api.deploy.plan.router import ALIAS_PREFIX as PLAN_ALIAS
from neurosphere_api.deploy.plan.router import ROUTE_PREFIX as PLAN_PREFIX
from neurosphere_api.deploy.scan.router import ALIAS_PREFIX as SCAN_ALIAS
from neurosphere_api.deploy.scan.router import ROUTE_PREFIX as SCAN_PREFIX
from neurosphere_api.ingest import (
    IngestSettings,
    InMemoryPublisher,
    ProducerRegistration,
    StaticProducerRegistry,
    build_service,
    configure_ingest,
    hash_secret,
)
from neurosphere_api.ingest.router import ALIAS_PREFIX as INGEST_ALIAS
from neurosphere_api.ingest.router import ROUTE_PREFIX as INGEST_PREFIX
from neurosphere_core.cloud import Settings

#: (deprecated alias prefix, successor prefix), as fixed by the PRP-29 wire contract.
MOVES: Final = (
    ("/catalog", "/api/v1/catalog"),
    ("/catalog/curation", "/api/v1/catalog/curation"),
    ("/audit", "/api/v1/audit"),
    ("/v1/ingest", "/api/v1/ingest"),
    ("/v1/deploy/scan", "/api/v1/deploy/scan"),
    ("/v1/deploy/plan", "/api/v1/deploy/plan"),
)
MODULE_MOVES: Final = (
    (CATALOG_ALIAS, CATALOG_PREFIX),
    (CURATION_ALIAS, CURATION_PREFIX),
    (AUDIT_ALIAS, AUDIT_PREFIX),
    (INGEST_ALIAS, INGEST_PREFIX),
    (SCAN_ALIAS, SCAN_PREFIX),
    (PLAN_ALIAS, PLAN_PREFIX),
)

#: Moved operations (method + path): 14 catalog, 4 curation, 2 audit, 3 ingest, 1 scan, 1 plan;
#: 25 over 23 distinct paths (``/entities`` and ``/entities/{id}`` carry two methods each).
EXPECTED_OPERATION_COUNT: Final = 25

#: Sample values for path parameters, so both forms hit the same concrete resource.
_PARAMS: Final = {
    "entity_id": "commercial:contoso:foundry:agent:support-bot",
    "edge_id": "commercial:contoso:neurosphere:invokes:e-0001",
    "chain_id": "contoso.finance",
}
_PARAM_RE: Final = re.compile(r"\{(\w+)(?::\w+)?\}")

INGEST_CUSTOMER: Final = "cust-synthetic"
INGEST_SOURCE: Final = "src-synthetic"
INGEST_PRODUCER: Final = "prod-synthetic"


@dataclass(frozen=True, slots=True)
class MovedOperation:
    method: str
    alias_template: str
    new_template: str

    @property
    def alias_path(self) -> str:
        return concrete(self.alias_template)

    @property
    def new_path(self) -> str:
        return concrete(self.new_template)

    @property
    def label(self) -> str:
        return f"{self.method} {self.new_template}"


def concrete(template: str) -> str:
    return _PARAM_RE.sub(lambda m: _PARAMS[m.group(1)], template)


def _alias_for(path: str) -> tuple[str, str] | None:
    """The (alias, successor) pair whose alias prefix is the longest prefix of ``path``."""
    best: tuple[str, str] | None = None
    for alias, new in MOVES:
        if (path == alias or path.startswith(alias + "/")) and (
            best is None or len(alias) > len(best[0])
        ):
            best = (alias, new)
    return best


def operations_by_path(app: FastAPI) -> dict[tuple[str, str], Any]:
    """``(method, full path template) -> route context`` for every API operation of ``app``."""
    found: dict[tuple[str, str], Any] = {}
    for context in iter_route_contexts(app.routes):
        path = getattr(context, "path", "")
        for method in sorted(getattr(context.original_route, "methods", None) or ()):
            found[(method, path)] = context
    return found


def moved_operations(app: FastAPI) -> list[MovedOperation]:
    out: list[MovedOperation] = []
    for method, path in sorted(operations_by_path(app)):
        pair = _alias_for(path)
        if pair is None:
            continue
        alias, new = pair
        out.append(MovedOperation(method, path, new + path[len(alias) :]))
    return out


def default_app() -> FastAPI:
    return create_app(Settings(env="local"))


MOVED: Final = tuple(moved_operations(default_app()))


@dataclass
class IngestEdge:
    app: FastAPI
    publisher: InMemoryPublisher
    secret: str

    @property
    def auth(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {INGEST_PRODUCER}.{self.secret}"}


def ingest_edge() -> IngestEdge:
    """The factory app with a configured ingest service and one synthetic producer."""
    secret = secrets.token_urlsafe(24)  # fake, generated per test
    settings = Settings(env="local")
    publisher = InMemoryPublisher()
    registration = ProducerRegistration(
        producer_id=INGEST_PRODUCER,
        secret_sha256=hash_secret(secret),
        customer_id=INGEST_CUSTOMER,
        cloud="commercial",
        sources={INGEST_SOURCE: "application"},
    )
    service = build_service(
        settings,
        IngestSettings(),
        publisher,
        registry=StaticProducerRegistry([registration]),
    )
    app = create_app(settings)
    configure_ingest(app, service)
    return IngestEdge(app=app, publisher=publisher, secret=secret)


def traces_doc() -> dict[str, Any]:
    """One synthetic OTLP/JSON span; the producer registration supplies customer and source."""
    span = {
        "traceId": "0af7651916cd43dd8448eb211c80319c",
        "spanId": "b7ad6b7169203331",
        "parentSpanId": "",
        "name": "chat synthetic",
        "status": {"code": 1},
        "startTimeUnixNano": "1700000000000000000",
        "endTimeUnixNano": "1700000000250000000",
        "attributes": [],
    }
    return {
        "resourceSpans": [
            {
                "resource": {"attributes": []},
                "scopeSpans": [{"scope": {"name": "synthetic"}, "spans": [span]}],
            }
        ]
    }


def normalized(body: Any) -> Any:
    """A response body without the per-request fields (problem ``instance``, correlation id)."""
    if isinstance(body, dict):
        return {k: v for k, v in body.items() if k not in ("instance", "correlation_id")}
    return body
