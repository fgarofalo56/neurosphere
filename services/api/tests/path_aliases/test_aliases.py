"""PRP-29 item 4: every moved router is served at ``/api/v1/...`` and at its old prefix, by the
same handlers with the same permissions, and both forms answer identically."""

from __future__ import annotations

from typing import Any

import pytest
from authz.authz_helpers import (  # pyright: ignore[reportMissingImports]
    ALICE,
    BOB,
    CAROL,
    FINANCE,
    NOBODY,
    Harness,
    harness,
    policy,
    role,
)
from fastapi import FastAPI
from fastapi.testclient import TestClient
from neurosphere_api.authz import PRODUCER_AUTHENTICATED_PATHS, route_inventory, undeclared_routes
from neurosphere_api.ui_adapters import PREFIXES as UI_ADAPTER_PREFIXES
from neurosphere_core.audit import AuditRepository, InMemoryAuditStore
from neurosphere_core.auth.scope import Role

from .alias_support import (
    EXPECTED_OPERATION_COUNT,
    MODULE_MOVES,
    MOVED,
    MOVES,
    MovedOperation,
    default_app,
    ingest_edge,
    normalized,
    operations_by_path,
    traces_doc,
)

ADMIN = NOBODY
#: Callers with distinct permission sets: none, viewer, steward, auditor and admin of FINANCE.
CALLERS: tuple[str | None, ...] = (None, BOB, ALICE, CAROL, ADMIN)


@pytest.fixture(scope="module")
def authz_app() -> Harness:
    h = harness(
        policy(ALICE, role(Role.DOMAIN_STEWARD, FINANCE)),
        policy(BOB, role(Role.VIEWER, FINANCE)),
        policy(CAROL, role(Role.SECURITY_AUDITOR, FINANCE)),
        policy(ADMIN, role(Role.ADMIN, FINANCE)),
        routers={},
    )
    h.app.state.audit_repository = AuditRepository(InMemoryAuditStore())
    return h


def _call(h: Harness, method: str, path: str, who: str | None) -> tuple[int, Any]:
    headers = {"If-Match": '"0"'}
    if who is not None:
        headers.update(h.auth(who))
    kwargs: dict[str, Any] = {"headers": headers}
    if method in ("POST", "PUT"):
        kwargs["json"] = {}
    response = h.client.request(method, path, **kwargs)
    try:
        body: Any = response.json()
    except ValueError:
        body = response.text
    return response.status_code, normalized(body)


def test_module_prefixes_match_the_wire_contract() -> None:
    assert MODULE_MOVES == MOVES


def test_every_moved_operation_is_served_in_both_forms() -> None:
    assert len(MOVED) == EXPECTED_OPERATION_COUNT
    served = operations_by_path(default_app())
    for op in MOVED:
        assert (op.method, op.alias_template) in served
        assert (op.method, op.new_template) in served
    # and nothing under /api/v1/<moved> lacks its alias
    for method, path in sorted(served):
        if path.startswith(UI_ADAPTER_PREFIXES):
            continue  # PRP-31 adapters are new routes, not moved ones: no deprecated alias
        for alias, new in MOVES:
            if path.startswith(new + "/") or path == new:
                assert (method, alias + path[len(new) :]) in served, path


@pytest.fixture(scope="module")
def app() -> FastAPI:
    return default_app()


@pytest.mark.parametrize("op", MOVED, ids=[op.label for op in MOVED])
def test_alias_uses_the_same_handler_and_permissions(app: FastAPI, op: MovedOperation) -> None:
    served = operations_by_path(app)
    alias, new = served[(op.method, op.alias_template)], served[(op.method, op.new_template)]
    assert alias.original_route.endpoint is new.original_route.endpoint
    inventory = {(e.path, e.methods): e for e in route_inventory(app)}
    old_entry = inventory[(op.alias_template, (op.method,))]
    new_entry = inventory[(op.new_template, (op.method,))]
    assert old_entry.permissions == new_entry.permissions
    assert old_entry.producer_authenticated == new_entry.producer_authenticated
    assert old_entry.public is new_entry.public is False
    assert old_entry.compliant and new_entry.compliant


def test_route_inventory_stays_green_with_both_forms() -> None:
    app = default_app()
    assert undeclared_routes(app) == ()
    producer = {e.path for e in route_inventory(app) if e.producer_authenticated}
    assert producer == set(PRODUCER_AUTHENTICATED_PATHS)
    assert {p for p in producer if p.startswith("/api/v1/ingest/")} == {
        "/api" + p for p in producer if p.startswith("/v1/ingest/")
    }


@pytest.mark.parametrize("op", MOVED, ids=[op.label for op in MOVED])
def test_both_forms_answer_identically_for_every_caller(
    authz_app: Harness, op: MovedOperation
) -> None:
    outcomes = []
    for who in CALLERS:
        old = _call(authz_app, op.method, op.alias_path, who)
        new = _call(authz_app, op.method, op.new_path, who)
        assert old == new, (who, op.label)
        outcomes.append(old[0])
    if op.new_template.startswith("/api/v1/ingest/"):
        # Producer-authenticated, and this app has no ingest service: fail closed on both.
        assert set(outcomes) == {503}
    else:
        assert outcomes[0] == 401  # no token is refused on both forms


@pytest.mark.parametrize("prefix", ["/audit", "/api/v1/audit"])
def test_both_audit_forms_allow_the_auditor_and_deny_the_viewer(
    authz_app: Harness, prefix: str
) -> None:
    path = f"{prefix}/chains/contoso.finance/records"
    assert _call(authz_app, "GET", path, CAROL) == (200, {"items": [], "next_cursor": None})
    status, body = _call(authz_app, "GET", path, BOB)
    assert (status, body["reason"]) == (403, "target_out_of_scope")
    assert _call(authz_app, "GET", path, None)[0] == 401


@pytest.mark.parametrize("path", sorted(PRODUCER_AUTHENTICATED_PATHS))
def test_both_ingest_forms_return_401_without_a_credential(path: str) -> None:
    client = TestClient(ingest_edge().app)
    assert client.post(path, content=b"{}").status_code == 401
    bad = client.post(path, content=b"{}", headers={"Authorization": "Bearer nope.nope"})
    assert bad.status_code == 401


def test_both_ingest_forms_accept_the_same_producer_identically() -> None:
    edge = ingest_edge()
    client = TestClient(edge.app)
    headers = {"Content-Type": "application/json", **edge.auth}
    old = client.post("/v1/ingest/otlp/traces", json=traces_doc(), headers=headers)
    new = client.post("/api/v1/ingest/otlp/traces", json=traces_doc(), headers=headers)
    assert old.status_code == new.status_code == 202
    assert old.json() == new.json()
    assert len(edge.publisher.messages) == 2
