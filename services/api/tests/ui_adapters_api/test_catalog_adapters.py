"""PRP-31 item 2: domain-path catalog list, search and export, the route inventory and route
ordering beside the PRP-29 ``/api/v1/catalog`` routes."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

import pytest
from authz.authz_helpers import FINANCE, OPERATIONS  # pyright: ignore[reportMissingImports]
from fastapi.routing import iter_route_contexts
from neurosphere_api.authz import route_inventory, undeclared_routes
from neurosphere_api.openapi_export import default_app
from neurosphere_api.ui_adapters import PREFIXES

from .adapter_support import (
    STEWARD,
    VIEWER,
    World,
    agent_doc,
    agent_id,
    make_world,
)

BASE = "/api/v1/catalog/domains"
BUDGET = {"timeout_ms": 1000, "limit": 10, "max_depth": 0}


@pytest.fixture
def world() -> World:
    w = make_world()
    w.seed(
        agent_doc("fin-bot", FINANCE),
        agent_doc("fin-helper", FINANCE, lifecycle_status="deprecated"),
        agent_doc("ops-bot", OPERATIONS),
    )
    return w


def _ids(body: dict[str, Any], key: str = "items") -> set[str]:
    return {item["id"] for item in body[key]}


# --------------------------------------------------------------------------- list


def test_list_returns_only_the_path_domain(world: World) -> None:
    response = world.get(VIEWER, f"{BASE}/{FINANCE}/entities")
    assert response.status_code == 200, response.text
    assert _ids(response.json()) == {agent_id("fin-bot"), agent_id("fin-helper")}


def test_list_filters_by_type_and_lifecycle(world: World) -> None:
    response = world.get(
        VIEWER,
        f"{BASE}/{FINANCE}/entities",
        params={"entity_type": "agent", "lifecycle": "deprecated"},
    )
    assert response.status_code == 200, response.text
    assert _ids(response.json()) == {agent_id("fin-helper")}


def test_list_ignores_a_smuggled_domain_query_key(world: World) -> None:
    response = world.get(VIEWER, f"{BASE}/{FINANCE}/entities", params={"domain_id": OPERATIONS})
    assert response.status_code == 200, response.text
    assert agent_id("ops-bot") not in _ids(response.json())


def test_list_pages_with_a_cursor(world: World) -> None:
    first = world.get(VIEWER, f"{BASE}/{FINANCE}/entities", params={"page_size": 1})
    assert first.status_code == 200, first.text
    cursor = first.json()["next_cursor"]
    assert len(first.json()["items"]) == 1
    assert cursor
    second = world.get(
        VIEWER, f"{BASE}/{FINANCE}/entities", params={"page_size": 1, "cursor": cursor}
    )
    assert second.status_code == 200, second.text
    assert _ids(first.json()) | _ids(second.json()) == {
        agent_id("fin-bot"),
        agent_id("fin-helper"),
    }


@pytest.mark.parametrize(
    ("who", "domain", "status"),
    [
        (None, FINANCE, 401),
        (VIEWER, OPERATIONS, 403),  # data.read in FINANCE only
        (VIEWER, "commercial:fabrikam:catalog:domain:finance", 403),
    ],
)
def test_list_denies_outside_the_scope(
    world: World, who: str | None, domain: str, status: int
) -> None:
    assert world.get(who, f"{BASE}/{domain}/entities").status_code == status


# --------------------------------------------------------------------------- search


def test_search_is_confined_to_the_path_domain(world: World) -> None:
    body = {"term": "bot", "budget": BUDGET}
    response = world.post(VIEWER, f"{BASE}/{FINANCE}/search", body)
    assert response.status_code == 200, response.text
    found = _ids(response.json(), "nodes")
    assert agent_id("fin-bot") in found
    assert all(n["domain_id"] == FINANCE for n in response.json()["nodes"])


@pytest.mark.parametrize(
    "extra",
    [
        {"filters": {"domain_ids": [OPERATIONS]}},
        {"domain_id": OPERATIONS},
        {"customer_id": "contoso"},
    ],
    ids=["filters", "domain_id", "customer_id"],
)
def test_search_refuses_extra_fields(world: World, extra: dict[str, Any]) -> None:
    body = {"term": "bot", "budget": BUDGET, **extra}
    response = world.post(VIEWER, f"{BASE}/{FINANCE}/search", body)
    assert response.status_code == 422


def test_search_denies_another_domain(world: World) -> None:
    body = {"term": "bot", "budget": BUDGET}
    response = world.post(VIEWER, f"{BASE}/{OPERATIONS}/search", body)
    assert response.status_code == 403


# --------------------------------------------------------------------------- export


def test_export_needs_data_export_on_the_domain(world: World) -> None:
    assert world.get(VIEWER, f"{BASE}/{FINANCE}/export").status_code == 403
    response = world.get(STEWARD, f"{BASE}/{FINANCE}/export")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["domains"] == [FINANCE]
    assert _ids(body) == {agent_id("fin-bot"), agent_id("fin-helper")}


def test_export_denies_another_domain(world: World) -> None:
    assert world.get(STEWARD, f"{BASE}/{OPERATIONS}/export").status_code == 403


# --------------------------------------------------------------------------- inventory and order

EXPECTED_PERMISSIONS = {
    ("GET", "/api/v1/catalog/domains/{domain}/entities"): ("data.read",),
    ("POST", "/api/v1/catalog/domains/{domain}/search"): ("data.read",),
    ("GET", "/api/v1/catalog/domains/{domain}/export"): ("data.export",),
    ("GET", "/api/v1/catalog/domains/{domain}/curation/edges/{edge_id:path}"): ("data.read",),
    (
        "POST",
        "/api/v1/catalog/domains/{domain}/curation/edges/{edge_id:path}/decisions",
    ): ("catalog.curate",),
    ("GET", "/api/v1/audit/domains"): ("audit.read",),
    ("GET", "/api/v1/audit/domains/{domain}/records"): ("audit.read",),
    ("GET", "/api/v1/audit/domains/{domain}/verify"): ("audit.read",),
    ("GET", "/api/v1/capabilities"): ("data.read",),
}


def test_every_adapter_route_declares_its_permission() -> None:
    app = default_app()
    assert undeclared_routes(app) == ()
    found = {
        (method, e.path): e.permissions
        for e in route_inventory(app)
        if e.path.startswith(PREFIXES)
        for method in e.methods
    }
    assert found == EXPECTED_PERMISSIONS


EDGE = "commercial:contoso:neurosphere:invokes:a/b-1"
SAMPLES = [
    ("GET", f"{BASE}/{FINANCE}/entities"),
    ("POST", f"{BASE}/{FINANCE}/search"),
    ("GET", f"{BASE}/{FINANCE}/export"),
    ("POST", f"{BASE}/{FINANCE}/curation/edges/{EDGE}/decisions"),
    ("GET", f"{BASE}/{FINANCE}/curation/edges/{EDGE}"),
    ("GET", "/api/v1/audit/domains"),
    ("GET", f"/api/v1/audit/domains/{FINANCE}/records"),
    ("GET", f"/api/v1/audit/domains/{FINANCE}/verify"),
    ("GET", "/api/v1/capabilities"),
]


@pytest.mark.parametrize(("method", "path"), SAMPLES)
def test_no_earlier_route_shadows_an_adapter(method: str, path: str) -> None:
    """The FIRST route that matches (Starlette's order) is the adapter, never a PRP-29 route."""
    app = default_app()
    first = None
    for context in iter_route_contexts(app.routes):
        regex = getattr(context, "path_regex", None)
        methods = getattr(context, "methods", None) or ()
        if isinstance(regex, re.Pattern) and regex.match(path) and method in methods:
            first = context
            break
    assert first is not None, path
    assert first.endpoint.__module__.startswith("neurosphere_api.ui_adapters."), (
        first.path,
        first.endpoint.__module__,
    )


def test_edge_ids_with_colons_and_slashes_reach_the_decision_route(world: World) -> None:
    """Percent-encoded or raw, an edge id with ``/`` resolves to the adapter (404 = not stored)."""
    for edge in (EDGE, quote(EDGE, safe="")):
        path = f"{BASE}/{FINANCE}/curation/edges/{edge}/decisions"
        body = {
            "decision": "accept",
            "reason": "ok",
            "expected_edge_version": 1,
            "expected_edge_etag": "x",
        }
        response = world.post(STEWARD, path, body)
        assert response.status_code == 404
