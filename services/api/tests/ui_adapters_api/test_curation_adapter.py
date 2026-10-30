"""PRP-31 item 2: the browser decision route stamps every server-owned field, refuses smuggled
fields with 422, enforces 403/404/409, refuses non-user principals and audits ``channel=button``."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import pytest
from authz.authz_helpers import (  # pyright: ignore[reportMissingImports]
    FINANCE,
    OPERATIONS,
    principal_id_for,
)
from neurosphere_core.catalog import CatalogEdge, format_timestamp

from .adapter_support import (
    APP_STEWARD,
    AUDITOR,
    STEWARD,
    STEWARD_BOTH,
    VIEWER,
    World,
    agent_doc,
    make_edge,
    make_world,
)

BASE = "/api/v1/catalog/domains"
EXPIRY = "2027-03-01T00:00:00Z"


@pytest.fixture
def world() -> World:
    w = make_world()
    w.seed(
        agent_doc("fin-a", FINANCE),
        agent_doc("fin-b", FINANCE),
        agent_doc("ops-a", OPERATIONS),
        agent_doc("ops-b", OPERATIONS),
    )
    return w


def _seed(world: World, domain: str = FINANCE, name: str = "e-fin") -> CatalogEdge:
    src, dst = ("fin-a", "fin-b") if domain == FINANCE else ("ops-a", "ops-b")
    (stored,) = world.seed_edges(make_edge(name, src, dst, domain))
    return stored


def _path(edge: CatalogEdge, domain: str = FINANCE) -> str:
    return f"{BASE}/{domain}/curation/edges/{quote(edge.id, safe=':')}/decisions"


def _body(edge: CatalogEdge, decision: str = "accept", **extra: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "decision": decision,
        "reason": f"steward {decision}",
        "expected_edge_version": edge.version.root,
        "expected_edge_etag": edge.etag.root,
    }
    if decision in ("lock", "override"):
        body["lock_expiry"] = EXPIRY
    body.update(extra)
    return body


# --------------------------------------------------------------------------- 201


def test_accept_is_stamped_from_the_stored_edge_and_the_caller(world: World) -> None:
    edge = _seed(world)
    response = world.post(STEWARD, _path(edge), _body(edge))
    assert response.status_code == 201, response.text
    override = response.json()["override"]
    assert override["actor"] == principal_id_for(STEWARD)
    assert override["edge_id"] == edge.id
    assert override["relation_type"] == edge.relation_type
    assert override["domain_id"] == FINANCE
    assert override["customer_id"] == "contoso"
    assert override["cloud"] == "commercial"
    assert override["id"].startswith("commercial:contoso:neurosphere:edge_override:")
    assert override["decided_at"] == format_timestamp(world.now())
    assert override.get("lock") is None


def test_lock_stamps_the_lock_actor_and_presents_the_lock(world: World) -> None:
    edge = _seed(world)
    body = _body(edge, "lock", set_confidence=0.9)
    response = world.post(STEWARD, _path(edge), body)
    assert response.status_code == 201, response.text
    payload = response.json()
    lock = payload["override"]["lock"]
    assert lock == {
        "locked": True,
        "reason": "steward lock",
        "expiry": EXPIRY,
        "actor": principal_id_for(STEWARD),
    }
    assert payload["presented"]["lock"]["locked"] is True
    assert payload["presented"]["pinned"] is True


def test_raw_slash_and_colon_edge_ids_round_trip(world: World) -> None:
    edge = _seed(world, name="team/a-1")
    assert "/" in edge.id
    encoded = f"{BASE}/{FINANCE}/curation/edges/{quote(edge.id, safe='')}/decisions"
    response = world.post(STEWARD, encoded, _body(edge))
    assert response.status_code == 201, response.text
    assert response.json()["override"]["edge_id"] == edge.id


def test_button_channel_lands_in_the_audit_record(world: World) -> None:
    edge = _seed(world)
    response = world.post(STEWARD, _path(edge), _body(edge))
    assert response.status_code == 201
    records = world.records("contoso.finance")
    assert [r.kind for r in records] == ["before", "after"]
    assert {r.channel for r in records} == {"button"}
    assert {r.operation for r in records} == {"catalog.curate"}
    assert records[-1].subject is not None
    assert records[-1].subject.target.canonical_id == edge.id


# --------------------------------------------------------------------------- edge read


def _read_path(edge: CatalogEdge, domain: str = FINANCE) -> str:
    return f"{BASE}/{domain}/curation/edges/{quote(edge.id, safe=':')}"


def test_read_returns_version_etag_and_header(world: World) -> None:
    edge = _seed(world)
    response = world.get(VIEWER, _read_path(edge))
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"edge", "edge_version", "edge_etag"}
    assert body["edge_version"] == edge.version.root
    assert body["edge_etag"] == edge.etag.root
    assert response.headers["etag"] == body["edge_etag"]
    assert body["edge"]["edge_id"] == edge.id


@pytest.mark.parametrize("decision", ["accept", "lock"])
def test_read_values_are_accepted_by_the_decision_route(world: World, decision: str) -> None:
    edge = _seed(world)
    got = world.get(STEWARD, _read_path(edge)).json()
    body: dict[str, Any] = {
        "decision": decision,
        "reason": f"steward {decision}",
        "expected_edge_version": got["edge_version"],
        "expected_edge_etag": got["edge_etag"],
    }
    if decision == "lock":
        body["lock_expiry"] = EXPIRY
    response = world.post(STEWARD, _path(edge), body)
    assert response.status_code == 201, response.text


def test_read_slash_edge_id(world: World) -> None:
    edge = _seed(world, name="team/a-1")
    encoded = f"{BASE}/{FINANCE}/curation/edges/{quote(edge.id, safe='')}"
    assert world.get(VIEWER, encoded).status_code == 200


def test_read_edge_in_another_domain_is_404(world: World) -> None:
    edge = _seed(world, OPERATIONS, "e-ops")
    assert world.get(STEWARD_BOTH, _read_path(edge, FINANCE)).status_code == 404


def test_read_unknown_edge_is_404(world: World) -> None:
    edge = _seed(world)
    assert world.get(VIEWER, _read_path(edge) + "-missing").status_code == 404


def test_read_without_data_read_on_domain_is_403(world: World) -> None:
    edge = _seed(world)
    assert world.get(AUDITOR, _read_path(edge)).status_code == 403
    other = _seed(world, OPERATIONS, "e-ops")
    assert world.get(VIEWER, _read_path(other, OPERATIONS)).status_code == 403


def test_read_unauthenticated_is_401(world: World) -> None:
    edge = _seed(world)
    assert world.get(None, _read_path(edge)).status_code == 401


# --------------------------------------------------------------------------- 409 / 403 / 404


def test_stale_edge_is_409_and_audited_as_denied(world: World) -> None:
    edge = _seed(world)
    stale = _body(edge, expected_edge_version=edge.version.root + 1)
    response = world.post(STEWARD, _path(edge), stale)
    assert response.status_code == 409, response.text
    assert response.json()["reason"] == "stale_edge"
    records = world.records("contoso.finance")
    assert [r.kind for r in records] == ["denied"]
    assert records[0].channel == "button"


def test_wrong_etag_is_409(world: World) -> None:
    edge = _seed(world)
    response = world.post(STEWARD, _path(edge), _body(edge, expected_edge_etag='"other"'))
    assert response.status_code == 409
    assert response.json()["reason"] == "stale_edge"


def test_viewer_without_catalog_curate_is_403(world: World) -> None:
    edge = _seed(world)
    response = world.post(VIEWER, _path(edge), _body(edge))
    assert response.status_code == 403
    assert response.json()["reason"] == "target_out_of_scope"
    assert world.records("contoso.finance") == []


def test_steward_of_another_domain_is_403(world: World) -> None:
    edge = _seed(world, OPERATIONS, "e-ops")
    # STEWARD curates FINANCE only; the path names the edge's real domain.
    response = world.post(STEWARD, _path(edge, OPERATIONS), _body(edge))
    assert response.status_code == 403


def test_edge_outside_the_path_domain_is_404(world: World) -> None:
    edge = _seed(world, OPERATIONS, "e-ops")
    # STEWARD_BOTH may curate both domains, but the edge is not in FINANCE.
    response = world.post(STEWARD_BOTH, _path(edge, FINANCE), _body(edge))
    assert response.status_code == 404
    assert world.records("contoso.operations") == []


def test_unknown_edge_is_404(world: World) -> None:
    edge = _seed(world)
    missing = f"{BASE}/{FINANCE}/curation/edges/{edge.id}-missing/decisions"
    response = world.post(STEWARD, missing, _body(edge))
    assert response.status_code == 404


def test_unauthenticated_is_401(world: World) -> None:
    edge = _seed(world)
    response = world.post(None, _path(edge), _body(edge))
    assert response.status_code == 401


def test_service_principal_is_refused(world: World) -> None:
    edge = _seed(world)
    path = _path(edge)
    response = world.h.client.post(
        path, json=_body(edge), headers=world.h.auth(APP_STEWARD, idtyp="app")
    )
    assert response.status_code == 403, response.text
    assert response.json()["reason"] == "principal_not_user"
    assert world.records("contoso.finance") == []


# --------------------------------------------------------------------------- 422

SMUGGLED: dict[str, Any] = {
    "actor": "commercial:contoso:entra:person:psn_0123456789abcdef",
    "decided_at": "2020-01-01T00:00:00Z",
    "cloud": "commercial",
    "customer_id": "contoso",
    "domain_id": FINANCE,
    "edge_id": "commercial:contoso:neurosphere:invokes:e-fin",
    "relation_type": "invokes",
    "channel": "rest",
    "id": "commercial:contoso:neurosphere:edge_override:x",
    "lock": {"locked": True},
    "schema_version": "1.0.0",
    "add_evidence_ids": ["audit:sec-1"],
}


@pytest.mark.parametrize("field", sorted(SMUGGLED))
def test_any_server_owned_field_is_422(world: World, field: str) -> None:
    edge = _seed(world)
    body = _body(edge, **{field: SMUGGLED[field]})
    response = world.post(STEWARD, _path(edge), body)
    assert response.status_code == 422, response.text
    assert world.records("contoso.finance") == []


@pytest.mark.parametrize(
    "patch",
    [
        {"decision": "approve"},
        {"reason": ""},
        {"expected_edge_version": 0},
        {"lock_expiry": "tomorrow"},
        {"set_confidence": 1.5},
    ],
)
def test_malformed_fields_are_422(world: World, patch: dict[str, Any]) -> None:
    edge = _seed(world)
    response = world.post(STEWARD, _path(edge), {**_body(edge), **patch})
    assert response.status_code == 422


def test_lock_expiry_on_accept_is_422(world: World) -> None:
    edge = _seed(world)
    response = world.post(STEWARD, _path(edge), _body(edge, lock_expiry=EXPIRY))
    assert response.status_code == 422
    assert response.json()["reason"] == "lock_not_allowed"


def test_lock_without_expiry_is_refused_by_the_service(world: World) -> None:
    edge = _seed(world)
    body = _body(edge, "lock")
    del body["lock_expiry"]
    response = world.post(STEWARD, _path(edge), body)
    assert response.status_code == 422
    assert response.json()["reason"] == "lock_requires_reason_and_expiry"
