"""PRP-43 item 5 (issue #208): pinned behaviour of the entity write adapters.

Domain self-edit needs ``catalog.curate`` on that domain, a ``grant`` catalog entity is inert for
scope derivation, a declared oversize ``Content-Length`` is refused before parsing, and a
non-user principal is accepted exactly as on the PRP-10 create route.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote

import pytest
from authz.authz_helpers import FINANCE, OPERATIONS  # pyright: ignore[reportMissingImports]
from neurosphere_api.ui_adapters.models import (
    MAX_ENTITY_BYTES,
    SERVER_OWNED_ENTITY_KEYS,
    UPDATE_SERVER_OWNED_ENTITY_KEYS,
)

from .adapter_support import (
    APP_STEWARD,
    STEWARD,
    STEWARD_BOTH,
    VIEWER,
    World,
    agent_doc,
    domain_doc,
    example,
    make_world,
)

BASE = "/api/v1/catalog/domains"


@pytest.fixture
def world() -> World:
    w = make_world()
    w.seed(domain_doc(FINANCE, "Finance"), domain_doc(OPERATIONS, "Operations"))
    w.seed(agent_doc("fin-a", FINANCE))
    return w


def _put_path(entity_id: str, domain: str) -> str:
    return f"{BASE}/{domain}/entities/{quote(entity_id, safe=':')}"


def _stored(world: World, who: str, entity_id: str) -> Any:
    return world.get(who, f"/api/v1/catalog/entities/{quote(entity_id, safe=':')}")


def _put_domain(world: World, who: str, path_domain: str, entity_id: str) -> Any:
    stored = _stored(world, STEWARD_BOTH, entity_id)
    assert stored.status_code == 200, stored.text
    body = {k: v for k, v in stored.json().items() if k not in UPDATE_SERVER_OWNED_ENTITY_KEYS}
    body["display_name"] = "Renamed"
    headers = {**world.headers(who), "If-Match": stored.headers["etag"]}
    return world.h.client.put(_put_path(entity_id, path_domain), json=body, headers=headers)


def test_domain_self_edit_needs_curate_on_that_domain(world: World) -> None:
    # STEWARD curates FINANCE only: editing OPERATIONS' own Domain entity is 403 before any read.
    denied = _put_domain(world, STEWARD, OPERATIONS, OPERATIONS)
    assert denied.status_code == 403, denied.text
    # naming FINANCE in the path does not reach another domain's entity either
    wrong_path = _put_domain(world, STEWARD, FINANCE, OPERATIONS)
    assert wrong_path.status_code == 404, wrong_path.text
    # a viewer cannot edit even the domain it reads
    assert _put_domain(world, VIEWER, FINANCE, FINANCE).status_code == 403
    ok = _put_domain(world, STEWARD, FINANCE, FINANCE)
    assert ok.status_code == 200, ok.text
    assert ok.json()["display_name"] == "Renamed"


async def test_grant_entity_changes_no_principals_computed_permissions(world: World) -> None:
    before = {who: (await world.scope_of(who)).scope_hash for who in (STEWARD, VIEWER)}
    body = {
        k: v
        for k, v in example("grant.user-model-deployment-token-limits.json").items()
        if k not in SERVER_OWNED_ENTITY_KEYS
    }
    response = world.post(STEWARD, f"{BASE}/{FINANCE}/entities", body)
    assert response.status_code == 201, response.text
    assert response.json()["entity_type"] == "grant"
    after = {who: (await world.scope_of(who)).scope_hash for who in (STEWARD, VIEWER)}
    assert after == before


def test_oversize_declared_content_length_is_refused_before_parsing(world: World) -> None:
    payload = json.dumps({"entity_type": "agent", "pad": "x" * (MAX_ENTITY_BYTES + 10)})
    headers = {**world.headers(STEWARD), "Content-Type": "application/json"}
    response = world.h.client.post(
        f"{BASE}/{FINANCE}/entities", content=payload.encode(), headers=headers
    )
    assert response.status_code == 422, response.text
    assert response.json()["reason"] == "request_too_large"
    # PUT is guarded the same way
    put = world.h.client.put(
        _put_path("commercial:contoso:foundry:agent:fin-a", FINANCE),
        content=payload.encode(),
        headers={**headers, "If-Match": '"x"'},
    )
    assert put.status_code == 422, put.text
    assert put.json()["reason"] == "request_too_large"


def test_a_body_under_the_cap_is_still_parsed_normally(world: World) -> None:
    body = {k: v for k, v in agent_doc("small").items() if k not in SERVER_OWNED_ENTITY_KEYS}
    body["lifecycle_status"] = "draft"
    assert world.post(STEWARD, f"{BASE}/{FINANCE}/entities", body).status_code == 201


def test_non_user_principal_creates_exactly_as_on_the_prp10_route(world: World) -> None:
    body = {k: v for k, v in agent_doc("svc-made").items() if k not in SERVER_OWNED_ENTITY_KEYS}
    body["lifecycle_status"] = "draft"
    adapter = world.post(
        None, f"{BASE}/{FINANCE}/entities", body, headers=world.h.auth(APP_STEWARD, idtyp="app")
    )
    assert adapter.status_code == 201, adapter.text
    legacy_doc = agent_doc("svc-legacy")
    legacy_doc.update(
        cloud="commercial", customer_id="contoso", lifecycle_status="draft", version=1, etag="x"
    )
    legacy = world.post(
        None,
        "/api/v1/catalog/entities",
        legacy_doc,
        headers=world.h.auth(APP_STEWARD, idtyp="app"),
    )
    assert legacy.status_code == adapter.status_code == 201, legacy.text
