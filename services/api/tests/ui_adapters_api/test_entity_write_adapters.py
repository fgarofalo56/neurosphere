"""PRP-31 item 13: domain-path entity create and update stamp cloud, customer, domain and id on
the server, refuse every server-owned key with 422, enforce 403/404/409 without leaking existence
across domains or customers, and audit ``channel=button``."""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import quote

import pytest
from authz.authz_helpers import FINANCE, OPERATIONS  # pyright: ignore[reportMissingImports]
from fastapi.routing import iter_route_contexts
from neurosphere_api.authz import route_inventory, undeclared_routes
from neurosphere_api.openapi_export import default_app
from neurosphere_api.ui_adapters.entities import ID_SOURCE
from neurosphere_api.ui_adapters.models import (
    MAX_ENTITY_BYTES,
    SERVER_OWNED_ENTITY_KEYS,
    UPDATE_SERVER_OWNED_ENTITY_KEYS,
)
from neurosphere_contracts.catalog.v1.canonical_id import CanonicalId

from .adapter_support import (
    OTHER_CUSTOMER_FINANCE,
    STEWARD,
    STEWARD_BOTH,
    VIEWER,
    World,
    agent_doc,
    agent_id,
    example,
    make_world,
)

BASE = "/api/v1/catalog/domains"
_ID = re.compile(r"^commercial:contoso:manual:(?P<type>[a-z_]+):[0-9a-f]{32}$")


@pytest.fixture
def world() -> World:
    w = make_world()
    w.seed(agent_doc("fin-a", FINANCE), agent_doc("ops-a", OPERATIONS))
    return w


def _strip(doc: dict[str, Any], keys: frozenset[str]) -> dict[str, Any]:
    return {k: v for k, v in doc.items() if k not in keys}


def _agent_body(name: str = "new-bot", **patch: Any) -> dict[str, Any]:
    body = _strip(agent_doc(name), SERVER_OWNED_ENTITY_KEYS)
    body["lifecycle_status"] = "draft"
    body.update(patch)
    return body


def _create_path(domain: str = FINANCE) -> str:
    return f"{BASE}/{domain}/entities"


def _put_path(entity_id: str, domain: str = FINANCE) -> str:
    return f"{BASE}/{domain}/entities/{quote(entity_id, safe=':')}"


def _put(world: World, who: str, path: str, body: Any, etag: str | None) -> Any:
    headers = {**world.headers(who), **({"If-Match": etag} if etag is not None else {})}
    return world.h.client.put(path, json=body, headers=headers)


def _update_body(stored: dict[str, Any], **patch: Any) -> dict[str, Any]:
    body = _strip(stored, UPDATE_SERVER_OWNED_ENTITY_KEYS)
    body.update(patch)
    return body


def _get(world: World, who: str, entity_id: str) -> Any:
    return world.get(who, f"/api/v1/catalog/entities/{quote(entity_id, safe=':')}")


def _create(world: World, **patch: Any) -> dict[str, Any]:
    response = world.post(STEWARD, _create_path(), _agent_body(**patch))
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()
    return created


# --------------------------------------------------------------------------- create


def test_create_stamps_scope_and_round_trips_through_get(world: World) -> None:
    response = world.post(STEWARD, _create_path(), _agent_body())
    assert response.status_code == 201, response.text
    created = response.json()
    assert created["cloud"] == "commercial"
    assert created["customer_id"] == "contoso"
    assert created["domain_id"] == FINANCE
    assert created["version"] == 1
    assert created["lifecycle_status"] == "draft"
    match = _ID.fullmatch(created["id"])
    assert match is not None, created["id"]
    assert match["type"] == "agent"
    assert CanonicalId.model_validate(created["id"]).root == created["id"]
    assert response.headers["etag"] == f'"{created["etag"].strip(chr(34))}"'

    got = _get(world, VIEWER, created["id"])
    assert got.status_code == 200, got.text
    assert got.json() == created
    assert got.headers["etag"] == response.headers["etag"]


def test_minted_ids_are_unique_and_use_the_manual_source(world: World) -> None:
    first = _create(world, display_name="One")
    second = _create(world, display_name="Two")
    assert first["id"] != second["id"]
    assert ID_SOURCE == "manual"
    assert first["id"].split(":")[2] == "manual"


@pytest.mark.parametrize(
    ("example_name", "entity_type"),
    [
        ("agent.minimal-and-typical.json", "agent"),
        ("tool.minimal-and-typical.json", "tool"),
        ("model_deployment.minimal-and-typical.json", "model_deployment"),
        ("mcp_server.entra-streamable-http.json", "mcp_server"),
    ],
)
def test_form_entity_types_are_created(world: World, example_name: str, entity_type: str) -> None:
    body = _strip(example(example_name), SERVER_OWNED_ENTITY_KEYS)
    response = world.post(STEWARD, _create_path(), body)
    assert response.status_code == 201, response.text
    created = response.json()
    assert created["entity_type"] == entity_type
    assert created["domain_id"] == FINANCE
    match = _ID.fullmatch(created["id"])
    assert match is not None and match["type"] == entity_type


def test_create_audit_records_carry_the_button_channel(world: World) -> None:
    created = _create(world)
    records = [r for r in world.records() if r.operation == "catalog.entity_create"]
    assert [r.kind for r in records] == ["before", "after"]
    assert {r.channel for r in records} == {"button"}
    last = records[-1].subject
    assert last is not None
    assert last.target.canonical_id == created["id"]


@pytest.mark.parametrize("key", sorted(SERVER_OWNED_ENTITY_KEYS))
def test_create_refuses_every_server_owned_key(world: World, key: str) -> None:
    stored = example("agent.minimal-and-typical.json")
    body = _agent_body(**{key: stored.get(key, "2026-10-01T08:00:00Z")})
    response = world.post(STEWARD, _create_path(), body)
    assert response.status_code == 422, response.text
    assert key in response.text
    assert [r for r in world.records() if r.operation == "catalog.entity_create"] == []


@pytest.mark.parametrize(
    "patch",
    [
        {"entity_type": "domain"},
        {"entity_type": "not_a_type"},
        {"entity_type": None},
        {"attributes": {"blob": "x" * MAX_ENTITY_BYTES}},
        {f"extra_{i}": i for i in range(64)},
        {"lifecycle_status": "deprecated"},
        {"display_name": ""},
    ],
)
def test_create_refuses_malformed_bodies(world: World, patch: dict[str, Any]) -> None:
    response = world.post(STEWARD, _create_path(), _agent_body(**patch))
    assert response.status_code == 422, response.text


def test_create_without_entity_type_is_422(world: World) -> None:
    body = _agent_body()
    del body["entity_type"]
    assert world.post(STEWARD, _create_path(), body).status_code == 422


def test_create_without_catalog_curate_is_403(world: World) -> None:
    assert world.post(VIEWER, _create_path(), _agent_body()).status_code == 403
    # Authorization runs before any schema feedback: a bad body is still 403.
    smuggled = _agent_body(domain_id=FINANCE)
    assert world.post(VIEWER, _create_path(), smuggled).status_code == 403


def test_create_in_a_domain_the_caller_does_not_curate_is_403(world: World) -> None:
    assert world.post(STEWARD, _create_path(OPERATIONS), _agent_body()).status_code == 403
    response = world.post(STEWARD, _create_path(OTHER_CUSTOMER_FINANCE), _agent_body())
    assert response.status_code == 403


def test_create_unauthenticated_is_401(world: World) -> None:
    assert world.post(None, _create_path(), _agent_body()).status_code == 401


# --------------------------------------------------------------------------- update


def test_update_round_trips_and_keeps_server_owned_fields(world: World) -> None:
    created = _create(world)
    path = _put_path(created["id"])
    response = _put(world, STEWARD, path, _update_body(created, display_name="Renamed"), None)
    assert response.status_code == 422  # If-Match is required, as on the PRP-10 route
    etag = _get(world, STEWARD, created["id"]).headers["etag"]
    response = _put(world, STEWARD, path, _update_body(created, display_name="Renamed"), etag)
    assert response.status_code == 200, response.text
    updated = response.json()
    assert updated["display_name"] == "Renamed"
    assert updated["version"] == 2
    for key in ("id", "cloud", "customer_id", "domain_id", "created_at", "lifecycle_status"):
        assert updated[key] == created[key], key
    assert response.headers["etag"] != etag
    got = _get(world, VIEWER, created["id"])
    assert got.json() == updated


def test_missing_if_match_matches_the_prp10_route(world: World) -> None:
    created = _create(world)
    adapter = _put(world, STEWARD, _put_path(created["id"]), _update_body(created), None)
    legacy_body = {k: v for k, v in created.items()}
    legacy = _put(
        world,
        STEWARD,
        f"/api/v1/catalog/entities/{quote(created['id'], safe=':')}",
        legacy_body,
        None,
    )
    assert adapter.status_code == legacy.status_code == 422
    assert adapter.json()["code"] == legacy.json()["code"]


def test_stale_if_match_is_409_like_the_prp10_route(world: World) -> None:
    created = _create(world)
    adapter = _put(world, STEWARD, _put_path(created["id"]), _update_body(created), '"old"')
    legacy = _put(
        world,
        STEWARD,
        f"/api/v1/catalog/entities/{quote(created['id'], safe=':')}",
        dict(created),
        '"old"',
    )
    assert adapter.status_code == legacy.status_code == 409, adapter.text
    assert adapter.json()["code"] == legacy.json()["code"]


def test_update_audit_records_carry_the_button_channel(world: World) -> None:
    created = _create(world)
    etag = _get(world, STEWARD, created["id"]).headers["etag"]
    body = _update_body(created, display_name="Audited")
    response = _put(world, STEWARD, _put_path(created["id"]), body, etag)
    assert response.status_code == 200, response.text
    records = [r for r in world.records() if r.operation == "catalog.entity_update"]
    assert [r.kind for r in records] == ["before", "after"]
    assert {r.channel for r in records} == {"button"}


@pytest.mark.parametrize("key", sorted(UPDATE_SERVER_OWNED_ENTITY_KEYS))
def test_update_refuses_every_server_owned_key(world: World, key: str) -> None:
    created = _create(world)
    etag = _get(world, STEWARD, created["id"]).headers["etag"]
    body = _update_body(created, **{key: created.get(key, "2026-10-01T08:00:00Z")})
    response = _put(world, STEWARD, _put_path(created["id"]), body, etag)
    assert response.status_code == 422, response.text
    assert key in response.text
    unchanged = _get(world, STEWARD, created["id"]).json()
    assert unchanged["version"] == 1


def test_update_cannot_change_the_entity_type(world: World) -> None:
    created = _create(world)
    etag = _get(world, STEWARD, created["id"]).headers["etag"]
    body = _update_body(created, entity_type="tool")
    response = _put(world, STEWARD, _put_path(created["id"]), body, etag)
    assert response.status_code == 422, response.text


def test_update_without_catalog_curate_is_403(world: World) -> None:
    created = _create(world)
    etag = _get(world, VIEWER, created["id"]).headers["etag"]
    response = _put(world, VIEWER, _put_path(created["id"]), _update_body(created), etag)
    assert response.status_code == 403


def _not_found_shape(response: Any) -> tuple[int, Any, Any]:
    body = response.json()
    return response.status_code, body.get("title"), body.get("detail")


def test_cross_domain_update_is_404_and_indistinguishable_from_missing(world: World) -> None:
    ops = agent_id("ops-a")
    fin = agent_id("fin-a")
    body = _strip(agent_doc("ops-a", OPERATIONS), UPDATE_SERVER_OWNED_ENTITY_KEYS)
    # A curator of both domains naming the wrong path domain: 404.
    both = _put(world, STEWARD_BOTH, _put_path(ops, FINANCE), body, '"x"')
    assert both.status_code == 404, both.text
    # A FINANCE-only curator: an OPERATIONS entity under the FINANCE path looks exactly like an
    # id that does not exist at all.
    hidden = _put(world, STEWARD, _put_path(ops, FINANCE), body, '"x"')
    missing = _put(world, STEWARD, _put_path(fin + "-missing", FINANCE), body, '"x"')
    assert _not_found_shape(hidden) == _not_found_shape(missing)
    assert hidden.status_code == 404
    # ... and naming OPERATIONS in the path is 403 whether or not the entity exists.
    real = _put(world, STEWARD, _put_path(ops, OPERATIONS), body, '"x"')
    ghost = _put(world, STEWARD, _put_path(ops + "-missing", OPERATIONS), body, '"x"')
    assert real.status_code == ghost.status_code == 403
    assert _get(world, STEWARD_BOTH, ops).json()["version"] == 1


def test_cross_customer_update_is_404_or_403(world: World) -> None:
    foreign = "commercial:fabrikam:foundry:agent:fin-a"
    body = _strip(agent_doc("fin-a"), UPDATE_SERVER_OWNED_ENTITY_KEYS)
    assert _put(world, STEWARD, _put_path(foreign, FINANCE), body, '"x"').status_code == 404
    other = _put(world, STEWARD, _put_path(foreign, OTHER_CUSTOMER_FINANCE), body, '"x"')
    assert other.status_code == 403


def test_slash_ids_reach_the_update_route(world: World) -> None:
    (stored,) = world.seed(agent_doc("team/a-1", FINANCE))
    assert "/" in stored.id
    created = json.loads(stored.model_dump_json())
    for path in (
        f"{BASE}/{FINANCE}/entities/{stored.id}",
        f"{BASE}/{FINANCE}/entities/{quote(stored.id, safe='')}",
    ):
        etag = _get(world, STEWARD, stored.id).headers["etag"]
        response = _put(world, STEWARD, path, _update_body(created, display_name="S"), etag)
        assert response.status_code == 200, response.text
        assert response.json()["id"] == stored.id


# --------------------------------------------------------------------------- inventory / ordering

WRITE_ROUTES = {
    ("POST", "/api/v1/catalog/domains/{domain}/entities"): ("catalog.curate",),
    ("PUT", "/api/v1/catalog/domains/{domain}/entities/{entity_id:path}"): ("catalog.curate",),
}


def test_write_routes_declare_catalog_curate() -> None:
    app = default_app()
    assert undeclared_routes(app) == ()
    found = {
        (method, e.path): e.permissions
        for e in route_inventory(app)
        for method in e.methods
        if (method, e.path) in WRITE_ROUTES
    }
    assert found == WRITE_ROUTES


ENTITY = "commercial:contoso:manual:agent:a/b-1"
SAMPLES = [
    ("POST", f"{BASE}/{FINANCE}/entities"),
    ("PUT", f"{BASE}/{FINANCE}/entities/{ENTITY}"),
    ("PUT", f"{BASE}/{FINANCE}/entities/{quote(ENTITY, safe='')}"),
]


@pytest.mark.parametrize(("method", "path"), SAMPLES)
def test_no_earlier_route_shadows_the_write_adapters(method: str, path: str) -> None:
    """The FIRST matching route (Starlette's order) is the adapter, never a PRP-29 catalog route
    such as ``/api/v1/catalog/entities/{entity_id:path}``."""
    app = default_app()
    first = None
    for context in iter_route_contexts(app.routes):
        regex = getattr(context, "path_regex", None)
        methods = getattr(context, "methods", None) or ()
        if isinstance(regex, re.Pattern) and regex.match(path) and method in methods:
            first = context
            break
    assert first is not None, path
    assert first.endpoint.__module__ == "neurosphere_api.ui_adapters.entities", (
        first.path,
        first.endpoint.__module__,
    )
