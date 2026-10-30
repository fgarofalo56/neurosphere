"""Catalog API: entity CRUD, ETags, authorization, import, export, lifecycle, routing
(PRP-10 item 5)."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from authz.authz_helpers import FINANCE, OPERATIONS  # pyright: ignore[reportMissingImports]
from catalog_api_helpers import (  # pyright: ignore[reportMissingImports]
    ANALYST_MIXED,
    PREFIX,
    STEWARD_FINANCE,
    STEWARD_MIXED,
    VIEWER,
    Api,
    agent_doc,
    agent_id,
    make_api,
    make_both_routers_api,
    make_edge,
    owner_doc,
)
from neurosphere_api.authz import route_inventory, undeclared_routes
from neurosphere_api.catalog import (
    build_router,
    clamp_budget,
    get_repository,
)
from neurosphere_api.routers import RouterRegistry
from neurosphere_contracts.query.v1.budget import Budget

OPS_AGENT = agent_id("ops-bot")
FIN_AGENT = agent_id("fin-bot")


def _api() -> Api:
    api = make_api()
    api.seed(agent_doc("fin-bot", FINANCE), agent_doc("ops-bot", OPERATIONS))
    return api


def _etag(api: Api, entity_id: str) -> str:
    stored = api.stored(entity_id)
    assert stored is not None
    return stored.etag.root


# --------------------------------------------------------------------------- create / read


def test_create_assigns_server_fields_and_ignores_caller_ones() -> None:
    api = _api()
    doc = agent_doc("new-bot", FINANCE, customer_id="evil", cloud="government", version=9)
    response = api.post(STEWARD_FINANCE, "/entities", doc)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["version"] == 1
    assert body["customer_id"] == "contoso"
    assert body["cloud"] == "commercial"
    assert body["etag"] != doc["etag"]
    assert response.headers["ETag"] == f'"{body["etag"]}"'
    assert body["created_at"].startswith("2027-01-15T")
    got = api.get(VIEWER, f"/entities/{agent_id('new-bot')}")
    assert got.status_code == 200
    assert got.json()["id"] == agent_id("new-bot")
    assert got.headers["ETag"] == response.headers["ETag"]


def test_create_duplicate_and_malformed_are_invalid_schema() -> None:
    api = _api()
    duplicate = api.post(STEWARD_FINANCE, "/entities", agent_doc("fin-bot", FINANCE))
    assert duplicate.status_code == 422
    assert duplicate.json()["code"] == "invalid_schema"
    broken = api.post(STEWARD_FINANCE, "/entities", {"entity_type": "agent", "id": "nope"})
    assert broken.json()["code"] == "invalid_schema"
    retired = api.post(
        STEWARD_FINANCE, "/entities", agent_doc("r-bot", FINANCE, lifecycle_status="retired")
    )
    assert retired.json()["code"] == "invalid_schema"


def test_list_is_scope_filtered_and_paged() -> None:
    api = _api()
    api.seed(agent_doc("fin-2", FINANCE), agent_doc("fin-3", FINANCE))
    first = api.get(VIEWER, "/entities", params={"entity_type": "agent", "page_size": 2})
    assert first.status_code == 200
    page = first.json()
    assert len(page["items"]) == 2
    assert page["next_cursor"]
    rest = api.get(
        VIEWER,
        "/entities",
        params={"entity_type": "agent", "page_size": 2, "cursor": page["next_cursor"]},
    )
    ids = [i["id"] for i in page["items"] + rest.json()["items"]]
    assert OPS_AGENT not in ids
    assert FIN_AGENT in ids
    # Naming a domain the viewer cannot read narrows to nothing; it never widens the scope.
    named = api.get(VIEWER, "/entities", params={"domain_id": OPERATIONS})
    assert named.status_code == 200
    assert named.json()["items"] == []


def test_filters_are_allowlisted() -> None:
    api = _api()
    assert api.get(VIEWER, "/entities", params={"entity_type": "sql"}).json()["code"] == (
        "invalid_schema"
    )
    assert api.get(VIEWER, "/entities", params={"page_size": 100000}).status_code == 422


def test_missing_and_out_of_scope_read_alike() -> None:
    api = _api()
    missing = api.get(VIEWER, f"/entities/{agent_id('does-not-exist')}")
    hidden = api.get(VIEWER, f"/entities/{OPS_AGENT}")
    assert missing.status_code == hidden.status_code == 403
    assert missing.json()["code"] == hidden.json()["code"] == "forbidden"
    assert api.get(None, f"/entities/{FIN_AGENT}").status_code == 401


# --------------------------------------------------------------------------- update / ETag


def test_update_requires_etag_and_detects_stale_versions() -> None:
    api = _api()
    current = api.get(STEWARD_FINANCE, f"/entities/{FIN_AGENT}")
    etag = current.headers["ETag"]
    changed = {**current.json(), "display_name": "Renamed"}

    missing = api.put(STEWARD_FINANCE, f"/entities/{FIN_AGENT}", changed, None)
    assert missing.status_code == 422
    assert missing.json()["code"] == "invalid_schema"

    wrong = api.put(STEWARD_FINANCE, f"/entities/{FIN_AGENT}", changed, '"not-the-etag"')
    assert wrong.status_code == 409
    assert wrong.json()["code"] == "stale_version"

    ok = api.put(STEWARD_FINANCE, f"/entities/{FIN_AGENT}", changed, etag)
    assert ok.status_code == 200, ok.text
    assert ok.json()["display_name"] == "Renamed"
    assert ok.json()["version"] == current.json()["version"] + 1
    assert ok.headers["ETag"] != etag

    replay = api.put(STEWARD_FINANCE, f"/entities/{FIN_AGENT}", changed, etag)
    assert replay.json()["code"] == "stale_version"


def test_update_keeps_server_owned_fields_from_the_stored_entity() -> None:
    api = _api()
    current = api.get(STEWARD_FINANCE, f"/entities/{FIN_AGENT}")
    forged = {
        **current.json(),
        "domain_id": OPERATIONS,
        "customer_id": "evil",
        "lifecycle_status": "retired",
        "created_at": "2001-01-01T00:00:00Z",
    }
    response = api.put(STEWARD_FINANCE, f"/entities/{FIN_AGENT}", forged, current.headers["ETag"])
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["domain_id"] == FINANCE
    assert body["customer_id"] == "contoso"
    assert body["lifecycle_status"] == current.json()["lifecycle_status"]
    assert body["created_at"] == current.json()["created_at"]


def test_owner_recertification_fields_cannot_be_edited_through_update() -> None:
    api = _api()
    api.seed(owner_doc("team-a", FINANCE))
    oid = "commercial:contoso:foundry:owner:team-a"
    current = api.get(STEWARD_FINANCE, f"/entities/{oid}")
    forged = {**current.json(), "recertify_by": "2099-01-01T00:00:00Z"}
    response = api.put(STEWARD_FINANCE, f"/entities/{oid}", forged, current.headers["ETag"])
    assert response.status_code == 200, response.text
    assert response.json()["recertify_by"] == current.json()["recertify_by"]


# --------------------------------------------------------------------------- authorization


def test_viewer_cannot_write_anywhere() -> None:
    api = _api()
    etag = f'"{_etag(api, FIN_AGENT)}"'
    current = api.get(VIEWER, f"/entities/{FIN_AGENT}").json()
    calls: list[Any] = [
        api.post(VIEWER, "/entities", agent_doc("v-bot", FINANCE)),
        api.put(VIEWER, f"/entities/{FIN_AGENT}", current, etag),
        api.post(VIEWER, f"/entities/{FIN_AGENT}/deprecate", None, headers={"If-Match": etag}),
        api.post(
            VIEWER,
            "/import",
            {"items": [agent_doc("v-bot", FINANCE)]},
        ),
        api.post(VIEWER, "/reconcile/stale-agents/dry-run", {"window_days": 30}),
        api.post(VIEWER, "/reconcile/stale-agents/confirm", {}),
    ]
    assert [c.status_code for c in calls] == [403] * 6
    assert api.stored("commercial:contoso:foundry:agent:v-bot") is None
    assert api.stored(FIN_AGENT) is not None


def test_steward_of_a_cannot_write_in_b_even_if_the_body_claims_a() -> None:
    api = _api()
    # STEWARD_MIXED holds catalog.curate on FINANCE and only data.read on OPERATIONS.
    visible = api.get(STEWARD_MIXED, f"/entities/{OPS_AGENT}")
    assert visible.status_code == 200
    claimed = {**visible.json(), "domain_id": FINANCE}
    put = api.put(STEWARD_MIXED, f"/entities/{OPS_AGENT}", claimed, visible.headers["ETag"])
    assert put.status_code == 403
    deprecate = api.post(
        STEWARD_MIXED,
        f"/entities/{OPS_AGENT}/deprecate",
        None,
        headers={"If-Match": visible.headers["ETag"]},
    )
    assert deprecate.status_code == 403
    # Steward of FINANCE only: the OPERATIONS entity is invisible, so also refused.
    assert api.put(STEWARD_FINANCE, f"/entities/{OPS_AGENT}", claimed, '"x"').status_code == 403
    # Create names its domain in the body; naming one the caller cannot curate is refused.
    create = api.post(STEWARD_MIXED, "/entities", agent_doc("ops-2", OPERATIONS))
    assert create.status_code == 403
    after = api.stored(OPS_AGENT)
    assert after is not None
    assert after.version.root == visible.json()["version"]
    assert after.display_name.root == visible.json()["display_name"]


# --------------------------------------------------------------------------- export


def test_export_never_contains_a_domain_without_export_permission() -> None:
    api = _api()
    api.seed(agent_doc("fin-2", FINANCE), agent_doc("ops-2", OPERATIONS))
    # ANALYST_MIXED: analyst (data.export) of FINANCE, viewer only of OPERATIONS.
    plain = api.get(ANALYST_MIXED, "/export")
    assert plain.status_code == 200
    ids = {i["id"] for i in plain.json()["items"]}
    assert ids == {FIN_AGENT, agent_id("fin-2")}
    assert plain.json()["domains"] == [FINANCE]
    # The request names the other domain: dropped, never honored.
    named = api.get(ANALYST_MIXED, "/export", params={"domain_id": OPERATIONS})
    assert named.status_code == 200
    assert named.json()["items"] == []
    assert named.json()["domains"] == []
    both = api.get(ANALYST_MIXED, "/export", params={"domain_id": [OPERATIONS, FINANCE]})
    assert {i["id"] for i in both.json()["items"]} == ids
    # The same user can READ the other domain through the normal route, which proves the export
    # filter (not scope visibility) is what excludes it.
    assert api.get(ANALYST_MIXED, f"/entities/{OPS_AGENT}").status_code == 200


def test_export_requires_data_export_and_pages() -> None:
    api = _api()
    assert api.get(VIEWER, "/export").status_code == 403
    api.seed(agent_doc("fin-2", FINANCE), agent_doc("fin-3", FINANCE))
    first = api.get(STEWARD_FINANCE, "/export", params={"page_size": 2}).json()
    assert len(first["items"]) == 2
    rest = api.get(
        STEWARD_FINANCE, "/export", params={"page_size": 2, "cursor": first["next_cursor"]}
    ).json()
    seen = [i["id"] for i in first["items"] + rest["items"]]
    assert len(seen) == len(set(seen)) == 3


# --------------------------------------------------------------------------- import


def test_import_dry_run_writes_nothing_and_commit_creates_all() -> None:
    api = _api()
    items = [agent_doc("imp-1", FINANCE), owner_doc("imp-owner", FINANCE)]
    dry = api.post(STEWARD_FINANCE, "/import", {"items": items, "dry_run": True})
    assert dry.status_code == 200
    assert [i["status"] for i in dry.json()["items"]] == ["valid", "valid"]
    assert dry.json()["committed"] is False
    assert api.stored(agent_id("imp-1")) is None

    done = api.post(STEWARD_FINANCE, "/import", {"items": items})
    assert done.status_code == 200, done.text
    assert done.json()["committed"] is True
    assert [i["status"] for i in done.json()["items"]] == ["created", "created"]
    assert api.stored(agent_id("imp-1")) is not None
    records = asyncio.run(api.audit_records())
    assert len([r for r in records if r.kind == "after"]) >= 2


def test_import_with_a_bad_item_reports_every_item_and_writes_nothing() -> None:
    api = _api()
    items = [
        agent_doc("imp-1", FINANCE),
        {"entity_type": "agent", "id": "broken"},
        agent_doc("imp-3", OPERATIONS),  # a domain this steward cannot curate
        agent_doc("fin-bot", FINANCE),  # already exists
        agent_doc("imp-1", FINANCE),  # duplicate inside the batch
    ]
    response = api.post(STEWARD_FINANCE, "/import", {"items": items})
    assert response.status_code == 422
    body = response.json()
    assert body["committed"] is False
    assert [i["status"] for i in body["items"]] == [
        "valid",
        "rejected",
        "rejected",
        "rejected",
        "rejected",
    ]
    assert body["items"][2]["code"] == "forbidden"
    assert api.stored(agent_id("imp-1")) is None


def test_import_is_bounded() -> None:
    api = _api()
    too_many = [agent_doc(f"b-{i}", FINANCE) for i in range(101)]
    assert api.post(STEWARD_FINANCE, "/import", {"items": too_many}).status_code == 422
    assert api.post(STEWARD_FINANCE, "/import", {"items": []}).status_code == 422


# --------------------------------------------------------------------------- lifecycle / audit


def test_deprecate_is_a_lifecycle_state_with_etag_and_audit() -> None:
    api = _api()
    api.seed_edges(make_edge("e1", "fin-bot", "fin-bot", FINANCE))
    etag = api.get(STEWARD_FINANCE, f"/entities/{FIN_AGENT}").headers["ETag"]
    stale = api.post(
        STEWARD_FINANCE, f"/entities/{FIN_AGENT}/deprecate", None, headers={"If-Match": '"old"'}
    )
    assert stale.json()["code"] == "stale_version"
    missing = api.post(STEWARD_FINANCE, f"/entities/{FIN_AGENT}/deprecate", None)
    assert missing.json()["code"] == "invalid_schema"

    ok = api.post(
        STEWARD_FINANCE, f"/entities/{FIN_AGENT}/deprecate", None, headers={"If-Match": etag}
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["lifecycle_status"] == "deprecated"
    still = api.get(VIEWER, f"/entities/{FIN_AGENT}")
    assert still.status_code == 200  # deprecated, not deleted
    again = api.post(
        STEWARD_FINANCE,
        f"/entities/{FIN_AGENT}/deprecate",
        None,
        headers={"If-Match": ok.headers["ETag"]},
    )
    assert again.json()["code"] == "invalid_schema"

    records = asyncio.run(api.audit_records())
    kinds = [(r.kind, r.operation) for r in records]
    assert ("before", "catalog.entity_deprecate") in kinds
    assert ("after", "catalog.entity_deprecate") in kinds
    assert ("denied", "catalog.entity_deprecate") in kinds
    failed = [
        r for r in records if r.kind == "after" and r.outcome and r.outcome.result == "failed"
    ]
    assert failed, "the stale attempt must leave a failed after-record"


def test_failed_audit_write_aborts_the_mutation() -> None:
    api = _api()

    async def boom(*_a: object, **_k: object) -> None:
        raise RuntimeError("audit store down")

    api.audit.append = boom  # type: ignore[method-assign]
    before = api.stored(FIN_AGENT)
    assert before is not None
    response = api.post(
        STEWARD_FINANCE,
        f"/entities/{FIN_AGENT}/deprecate",
        None,
        headers={"If-Match": f'"{before.etag.root}"'},
    )
    assert response.status_code >= 500
    after = api.stored(FIN_AGENT)
    assert after is not None
    assert after.version.root == before.version.root


# --------------------------------------------------------------------------- wiring


def test_unconfigured_dependencies_fail_closed() -> None:
    api = make_api(graph=False)
    api.h.app.dependency_overrides.pop(get_repository)
    assert api.get(VIEWER, f"/entities/{FIN_AGENT}").status_code == 503
    assert api.get(VIEWER, "/entities").status_code == 503
    api2 = make_api(graph=False)
    body = {
        "term": "bot",
        "budget": {"timeout_ms": 1000, "limit": 10, "max_depth": 0},
    }
    assert api2.post(VIEWER, "/search", body).status_code == 503
    assert (
        api2.post(VIEWER, "/lineage/neighbors", {**body, "node_id": FIN_AGENT}).status_code == 503
    )


@pytest.mark.parametrize("curation_first", [False, True])
def test_catalog_and_curation_routers_coexist_without_shadowing(curation_first: bool) -> None:
    api = make_both_routers_api(curation_first=curation_first)
    api.seed(agent_doc("fin-bot", FINANCE))
    edge = make_edge("e-curation", "fin-bot", "fin-bot", FINANCE)
    api.seed_edges(edge)
    stored_edge_id = edge.id

    curation = api.h.client.get(
        f"{PREFIX}/curation/edges/{stored_edge_id}", headers=api.h.auth(VIEWER)
    )
    assert curation.status_code == 200, curation.text
    assert curation.json()["edge_id"] == stored_edge_id  # PresentedEdge, not a catalog entity
    entity = api.get(VIEWER, f"/entities/{FIN_AGENT}")
    assert entity.status_code == 200
    assert entity.json()["entity_type"] == "agent"
    # An entity id that looks like a curation path is still an entity lookup, never curation.
    lookalike = api.get(VIEWER, "/entities/curation/edges/x")
    assert lookalike.json()["code"] == "invalid_schema"  # malformed entity id, not curation


def test_no_catalog_route_can_match_a_curation_path() -> None:
    router = build_router()
    for route in router.routes:
        path = getattr(route, "path", "")
        assert not path.startswith("/curation"), path
        assert path.split("/")[1] != "{path:path}"
        match = getattr(route, "path_regex", None)
        assert match is not None
        assert match.match(f"/curation/edges/{FIN_AGENT}") is None, path


def test_all_catalog_routes_declare_permissions() -> None:
    api = make_both_routers_api(curation_first=False)
    assert undeclared_routes(api.h.app) == ()
    declared = {
        (e.path, e.methods): e.permissions
        for e in route_inventory(api.h.app)
        if e.path.startswith(PREFIX) and not e.path.startswith(f"{PREFIX}/curation")
    }
    curate = ("catalog.curate",)
    read = ("data.read",)
    assert declared == {
        (f"{PREFIX}/entities", ("GET",)): read,
        (f"{PREFIX}/entities", ("POST",)): curate,
        (f"{PREFIX}/entities/{{entity_id:path}}/deprecate", ("POST",)): curate,
        (f"{PREFIX}/entities/{{entity_id:path}}/recertify", ("POST",)): curate,
        (f"{PREFIX}/entities/{{entity_id:path}}", ("PUT",)): curate,
        (f"{PREFIX}/entities/{{entity_id:path}}", ("GET",)): read,
        (f"{PREFIX}/search", ("POST",)): read,
        (f"{PREFIX}/lineage/neighbors", ("POST",)): read,
        (f"{PREFIX}/lineage/impact", ("POST",)): read,
        (f"{PREFIX}/import", ("POST",)): curate,
        (f"{PREFIX}/export", ("GET",)): ("data.export",),
        (f"{PREFIX}/recertifications", ("GET",)): read,
        (f"{PREFIX}/reconcile/stale-agents/dry-run", ("POST",)): curate,
        (f"{PREFIX}/reconcile/stale-agents/confirm", ("POST",)): curate,
        (f"{PREFIX}/grants/{{entity_id:path}}/publish", ("POST",)): ("action.propose",),
        (f"{PREFIX}/grants/{{entity_id:path}}/unpublish", ("POST",)): ("action.propose",),
        (f"{PREFIX}/grants/{{entity_id:path}}/publication", ("POST",)): curate,
    }


def test_register_hook_uses_the_catalog_prefix() -> None:
    from neurosphere_api.catalog import register

    registry = RouterRegistry()
    register(registry)
    # The successor prefix and its deprecated alias PREFIX (PRP-29 item 4).
    # Plus the MCP publication router (PRP-34 item 6), registered on its own successor prefix.
    assert registry.prefixes == ("/api/v1/catalog", PREFIX, "/api/v1/catalog/mcp-servers")


def test_budget_clamp_lowers_but_never_raises() -> None:
    big = Budget(timeout_ms=30000, limit=1000, max_depth=5)
    small = Budget(timeout_ms=100, limit=5, max_depth=2)
    assert (clamp_budget(big).timeout_ms, clamp_budget(big).limit) == (10_000, 500)
    assert clamp_budget(small) == small
