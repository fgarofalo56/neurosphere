"""PRP-29 item 4: deprecated aliases are marked in OpenAPI and answer with ``Deprecation``,
``Sunset`` and ``Link: <successor>; rel="successor-version"``; the ``/api/v1`` paths do not."""

from __future__ import annotations

import json
import re
from email.utils import parsedate_to_datetime
from typing import Any

import pytest
from authz.authz_helpers import (  # pyright: ignore[reportMissingImports]
    CAROL,
    FINANCE,
    harness,
    policy,
    role,
)
from fastapi import APIRouter, WebSocket
from fastapi.testclient import TestClient
from neurosphere_api.deprecation import (
    DEPRECATION_HEADER,
    SUNSET,
    SUNSET_AT,
    deprecated_alias,
    register_with_alias,
    successor_path,
)
from neurosphere_api.openapi_export import OPENAPI_PATH
from neurosphere_api.routers import RouterRegistry
from neurosphere_core.audit import AuditRepository, InMemoryAuditStore
from neurosphere_core.auth.scope import Role

from .alias_support import MOVED, MovedOperation, default_app, ingest_edge, traces_doc

_CONVERTER = re.compile(r"\{(\w+):\w+\}")
_ALIAS_HEADERS = ("deprecation", "sunset", "link")


def _openapi_path(template: str) -> str:
    return _CONVERTER.sub(r"{\1}", template)


def _assert_alias_headers(headers: Any, successor: str) -> None:
    assert headers["deprecation"] == "true"
    assert headers["sunset"] == "Fri, 30 Apr 2027 00:00:00 GMT"
    assert headers["link"] == f'<{successor}>; rel="successor-version"'


def _assert_no_alias_headers(headers: Any) -> None:
    assert not any(name in headers for name in _ALIAS_HEADERS)


# ------------------------------------------------------------------------------- constants


def test_sunset_is_one_imf_fixdate_constant() -> None:
    assert SUNSET == "Fri, 30 Apr 2027 00:00:00 GMT"
    assert parsedate_to_datetime(SUNSET) == SUNSET_AT
    assert DEPRECATION_HEADER == "true"


@pytest.mark.parametrize(
    ("request_path", "expected"),
    [
        ("/audit/chains/c.finance/records", "/api/v1/audit/chains/c.finance/records"),
        ("/audit", "/api/v1/audit"),
        ("/auditx/other", "/api/v1/audit"),
        ("/audit/a b<c>\r\nX: y", "/api/v1/audit/a%20b%3Cc%3E%0D%0AX:%20y"),
        ("/audit/commercial:contoso:x/y", "/api/v1/audit/commercial:contoso:x/y"),
    ],
    ids=["nested", "exact", "foreign", "injection", "canonical-id"],
)
def test_successor_path_rewrites_the_prefix_and_encodes_the_rest(
    request_path: str, expected: str
) -> None:
    assert (
        successor_path(request_path, alias_prefix="/audit", successor_prefix="/api/v1/audit")
        == expected
    )


def test_register_with_alias_registers_successor_then_alias() -> None:
    router = APIRouter()

    @router.get("/x")
    async def x() -> dict[str, str]:
        return {}

    registry = RouterRegistry()
    register_with_alias(registry, router, prefix="/api/v1/thing", alias_prefix="/thing")
    assert registry.prefixes == ("/api/v1/thing", "/thing")
    with pytest.raises(ValueError, match="already registered"):
        register_with_alias(registry, router, prefix="/api/v1/thing", alias_prefix="/other")


def test_alias_refuses_a_route_it_cannot_mark() -> None:
    router = APIRouter()

    @router.websocket("/ws")
    async def ws(websocket: WebSocket) -> None:
        await websocket.close()

    with pytest.raises(TypeError, match="non-API route"):
        deprecated_alias(router, alias_prefix="/old", successor_prefix="/api/v1/new")


# ------------------------------------------------------------------------------- OpenAPI


def _deprecated_flags(schema: dict[str, Any], op: MovedOperation) -> tuple[Any, Any]:
    method = op.method.lower()
    old = schema["paths"][_openapi_path(op.alias_template)][method]
    new = schema["paths"][_openapi_path(op.new_template)][method]
    return old.get("deprecated"), new.get("deprecated")


@pytest.fixture(scope="module")
def schema() -> dict[str, Any]:
    return default_app().openapi()


@pytest.mark.parametrize("op", MOVED, ids=[op.label for op in MOVED])
def test_openapi_marks_only_the_alias_deprecated(
    schema: dict[str, Any], op: MovedOperation
) -> None:
    assert _deprecated_flags(schema, op) == (True, None)


def test_committed_openapi_marks_every_alias_deprecated() -> None:
    committed = json.loads(OPENAPI_PATH.read_text(encoding="utf-8"))
    assert {_deprecated_flags(committed, op) for op in MOVED} == {(True, None)}


def test_operation_ids_stay_unique_with_both_forms(schema: dict[str, Any]) -> None:
    ids = [op["operationId"] for item in schema["paths"].values() for op in item.values()]
    assert len(ids) == len(set(ids))


# ------------------------------------------------------------------------------- responses


@pytest.fixture(scope="module")
def auditor_client() -> TestClient:
    h = harness(policy(CAROL, role(Role.SECURITY_AUDITOR, FINANCE)), routers={})
    h.app.state.audit_repository = AuditRepository(InMemoryAuditStore())
    h.client.headers.update(h.auth(CAROL))
    return h.client


def test_audit_alias_answers_with_deprecation_headers(auditor_client: TestClient) -> None:
    response = auditor_client.get("/audit/chains/contoso.finance/records")
    assert response.status_code == 200
    _assert_alias_headers(response.headers, "/api/v1/audit/chains/contoso.finance/records")


def test_audit_successor_answers_without_deprecation_headers(auditor_client: TestClient) -> None:
    response = auditor_client.get("/api/v1/audit/chains/contoso.finance/records")
    assert response.status_code == 200
    _assert_no_alias_headers(response.headers)


def test_ingest_alias_answers_with_deprecation_headers() -> None:
    edge = ingest_edge()
    client = TestClient(edge.app)
    headers = {"Content-Type": "application/json", **edge.auth}
    old = client.post("/v1/ingest/otlp/traces", json=traces_doc(), headers=headers)
    assert old.status_code == 202
    _assert_alias_headers(old.headers, "/api/v1/ingest/otlp/traces")
    new = client.post("/api/v1/ingest/otlp/traces", json=traces_doc(), headers=headers)
    assert new.status_code == 202
    _assert_no_alias_headers(new.headers)
