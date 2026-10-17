"""Catalog API: search, scope-filtered lineage, ownership recertification and stale-agent
reconciliation (PRP-10 item 5)."""

from __future__ import annotations

import asyncio
from typing import Any

from authz.authz_helpers import FINANCE, OPERATIONS  # pyright: ignore[reportMissingImports]
from catalog_api_helpers import (  # pyright: ignore[reportMissingImports]
    STEWARD_BOTH,
    STEWARD_FINANCE,
    VIEWER,
    Api,
    agent_doc,
    agent_id,
    make_api,
    make_edge,
    owner_doc,
    owner_id,
)
from neurosphere_api.catalog import plan_digest

BUDGET = {"timeout_ms": 2000, "limit": 50, "max_depth": 5}


# --------------------------------------------------------------------------- search


def _search_api() -> Api:
    api = make_api()
    api.seed(
        agent_doc("pay-fin", FINANCE, display_name="Payments assistant"),
        agent_doc("pay-ops", OPERATIONS, display_name="Payments hidden"),
        agent_doc("other", FINANCE, display_name="Unrelated"),
    )
    return api


def test_search_is_scope_filtered_even_when_the_request_names_the_other_domain() -> None:
    api = _search_api()
    body = {"term": "payments", "budget": BUDGET}
    hits = api.post(VIEWER, "/search", body)
    assert hits.status_code == 200, hits.text
    assert [n["id"] for n in hits.json()["nodes"]] == [agent_id("pay-fin")]

    named = api.post(VIEWER, "/search", {**body, "filters": {"domain_ids": [OPERATIONS]}})
    assert named.status_code == 200
    assert named.json()["nodes"] == []

    both = api.post(STEWARD_BOTH, "/search", body)
    assert {n["id"] for n in both.json()["nodes"]} == {agent_id("pay-fin"), agent_id("pay-ops")}


def test_search_takes_structured_input_only() -> None:
    api = _search_api()
    no_budget = api.post(VIEWER, "/search", {"term": "payments"})
    assert no_budget.json()["code"] == "invalid_schema"
    raw_query = api.post(
        VIEWER, "/search", {"term": "x", "budget": BUDGET, "query": "SELECT * FROM c"}
    )
    assert raw_query.json()["code"] == "invalid_schema"
    bad_filter = api.post(
        VIEWER, "/search", {"term": "x", "budget": BUDGET, "filters": {"sql": "1=1"}}
    )
    assert bad_filter.json()["code"] == "invalid_schema"
    huge = api.post(
        VIEWER,
        "/search",
        {"term": "payments", "budget": {"timeout_ms": 999999, "limit": 10, "max_depth": 0}},
    )
    assert huge.status_code == 422


# --------------------------------------------------------------------------- lineage


def _lineage_api() -> Api:
    api = make_api()
    api.seed(
        agent_doc("fin-a", FINANCE),
        agent_doc("fin-b", FINANCE),
        agent_doc("ops-c", OPERATIONS),
    )
    api.seed_edges(
        make_edge("a-b", "fin-a", "fin-b", FINANCE),
        # A finance edge whose far end is an OPERATIONS node: never shown to a finance viewer.
        make_edge("b-c", "fin-b", "ops-c", FINANCE),
    )
    return api


def test_neighbors_exclude_nodes_and_edges_outside_the_scope() -> None:
    api = _lineage_api()
    body = {"node_id": agent_id("fin-b"), "budget": BUDGET}
    mine = api.post(VIEWER, "/lineage/neighbors", body)
    assert mine.status_code == 200, mine.text
    ids = {n["id"] for n in mine.json()["nodes"]}
    assert agent_id("ops-c") not in ids
    assert agent_id("fin-a") in ids
    assert all("b-c" not in e["edge_id"] for e in mine.json()["edges"])
    wide = api.post(STEWARD_BOTH, "/lineage/neighbors", body)
    assert agent_id("ops-c") in {n["id"] for n in wide.json()["nodes"]}


def test_lineage_of_a_hidden_node_is_empty_and_raw_view_is_not_offered() -> None:
    api = _lineage_api()
    hidden = api.post(
        VIEWER, "/lineage/neighbors", {"node_id": agent_id("ops-c"), "budget": BUDGET}
    )
    assert hidden.status_code == 200
    assert hidden.json()["nodes"] == []
    assert hidden.json()["edges"] == []
    raw = api.post(
        VIEWER,
        "/lineage/neighbors",
        {"node_id": agent_id("fin-b"), "budget": BUDGET, "view": "raw"},
    )
    assert raw.json()["code"] == "invalid_schema"


def test_impact_paths_never_cross_a_hidden_node_and_report_truncation() -> None:
    api = _lineage_api()
    body = {"node_id": agent_id("fin-a"), "budget": BUDGET}
    mine = api.post(VIEWER, "/lineage/impact", body).json()
    assert mine["paths"]
    for path in mine["paths"]:
        assert agent_id("ops-c") not in path["node_ids"]
    wide = api.post(STEWARD_BOTH, "/lineage/impact", body).json()
    assert any(agent_id("ops-c") in p["node_ids"] for p in wide["paths"])

    tight = api.post(
        VIEWER,
        "/lineage/impact",
        {"node_id": agent_id("fin-a"), "budget": {**BUDGET, "max_nodes": 1}},
    ).json()
    assert tight["truncated"] is True
    assert tight["truncated_reason"] == "max_nodes"


# --------------------------------------------------------------------------- recertification


def _owner_api() -> Api:
    api = make_api()
    api.seed(
        owner_doc("team-a", FINANCE, recertify_by="2026-12-01T00:00:00Z"),  # overdue
        owner_doc("team-b", FINANCE, recertify_by="2027-02-01T00:00:00Z"),  # due in 17 days
        owner_doc("team-c", FINANCE, recertify_by="2027-12-01T00:00:00Z"),  # not due
        owner_doc("team-d", OPERATIONS, recertify_by="2026-12-01T00:00:00Z"),  # not visible
        agent_doc("an-agent", FINANCE),
    )
    return api


def _owner_ids(response: Any) -> list[str]:
    return [i["owner_id"] for i in response.json()["items"]]


def test_due_and_overdue_owners_are_listed_in_scope() -> None:
    api = _owner_api()
    both = api.get(VIEWER, "/recertifications")
    assert both.status_code == 200, both.text
    assert _owner_ids(both) == [owner_id("team-a"), owner_id("team-b")]
    states = {i["owner_id"]: i["state"] for i in both.json()["items"]}
    assert states == {owner_id("team-a"): "overdue", owner_id("team-b"): "due"}
    assert _owner_ids(api.get(VIEWER, "/recertifications", params={"include": "overdue"})) == [
        owner_id("team-a")
    ]
    assert _owner_ids(api.get(VIEWER, "/recertifications", params={"include": "due"})) == [
        owner_id("team-b")
    ]
    assert _owner_ids(api.get(VIEWER, "/recertifications", params={"within_days": 0})) == [
        owner_id("team-a")
    ]
    wide = api.get(STEWARD_BOTH, "/recertifications")
    assert owner_id("team-d") in _owner_ids(wide)


def test_recertify_records_expiry_requires_etag_and_is_audited() -> None:
    api = _owner_api()
    path = f"/entities/{owner_id('team-b')}/recertify"
    etag = api.get(STEWARD_FINANCE, f"/entities/{owner_id('team-b')}").headers["ETag"]
    body = {"valid_for_days": 90}

    assert api.post(STEWARD_FINANCE, path, body).json()["code"] == "invalid_schema"
    stale = api.post(STEWARD_FINANCE, path, body, headers={"If-Match": '"old"'})
    assert stale.json()["code"] == "stale_version"
    assert api.post(VIEWER, path, body, headers={"If-Match": etag}).status_code == 403
    assert (
        api.post(STEWARD_FINANCE, path, {"valid_for_days": 0}, headers={"If-Match": etag}).json()[
            "code"
        ]
        == "invalid_schema"
    )

    ok = api.post(STEWARD_FINANCE, path, body, headers={"If-Match": etag})
    assert ok.status_code == 200, ok.text
    assert ok.json()["recertified_at"].startswith("2027-01-15T")
    assert ok.json()["recertify_by"].startswith("2027-04-15T")
    assert owner_id("team-b") not in _owner_ids(api.get(VIEWER, "/recertifications"))

    agent_path = f"/entities/{agent_id('an-agent')}/recertify"
    agent_etag = api.get(STEWARD_FINANCE, f"/entities/{agent_id('an-agent')}").headers["ETag"]
    not_owner = api.post(STEWARD_FINANCE, agent_path, body, headers={"If-Match": agent_etag})
    assert not_owner.json()["code"] == "invalid_schema"

    operations = {(r.kind, r.operation) for r in asyncio.run(api.audit_records())}
    assert ("after", "catalog.owner_recertify") in operations
    assert ("denied", "catalog.owner_recertify") in operations


# --------------------------------------------------------------------------- stale agents


def _stale_api() -> Api:
    api = make_api()
    api.seed(
        agent_doc("stale-1", FINANCE),
        agent_doc("stale-2", FINANCE),
        agent_doc("fresh", FINANCE),
        agent_doc("ops-stale", OPERATIONS),
    )
    api.seed_edges(
        make_edge("fresh-self", "fresh", "fresh", FINANCE, last_observed="2027-01-10T00:00:00Z")
    )
    return api


def _plan(api: Api, who: str = STEWARD_FINANCE, window: int = 30) -> dict[str, Any]:
    response = api.post(who, "/reconcile/stale-agents/dry-run", {"window_days": window})
    assert response.status_code == 200, response.text
    return dict(response.json())


def _confirm_body(plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "plan_id": plan["plan_id"],
        "as_of": plan["as_of"],
        "window_days": plan["window_days"],
        "candidates": [{"agent_id": c["agent_id"], "etag": c["etag"]} for c in plan["candidates"]],
    }


def _versions(api: Api) -> dict[str, tuple[int, str]]:
    out: dict[str, tuple[int, str]] = {}
    for name in ("stale-1", "stale-2", "fresh", "ops-stale"):
        entity = api.stored(agent_id(name))
        assert entity is not None
        out[name] = (entity.version.root, entity.etag.root)
    return out


def test_dry_run_changes_nothing_and_lists_only_the_callers_stale_agents() -> None:
    api = _stale_api()
    before = _versions(api)
    plan = _plan(api)
    assert {c["agent_id"] for c in plan["candidates"]} == {
        agent_id("stale-1"),
        agent_id("stale-2"),
    }
    assert plan["truncated"] is False
    assert _versions(api) == before
    assert asyncio.run(api.audit_records()) == []
    assert _plan(api) == plan  # deterministic: same clock, same data, same digest


def test_confirm_applies_exactly_the_dry_run_set_etag_checked() -> None:
    api = _stale_api()
    before = _versions(api)
    plan = _plan(api)
    response = api.post(STEWARD_FINANCE, "/reconcile/stale-agents/confirm", _confirm_body(plan))
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert {i["agent_id"] for i in items} == {c["agent_id"] for c in plan["candidates"]}
    assert all(i["status"] == "marked" for i in items)

    after = _versions(api)
    assert after["fresh"] == before["fresh"]
    assert after["ops-stale"] == before["ops-stale"]
    for name in ("stale-1", "stale-2"):
        assert after[name][0] == before[name][0] + 1
        marked = api.stored(agent_id(name))
        assert marked is not None
        assert marked.lifecycle_status.root == "active"  # marked, never deleted or retired
        assert marked.attributes is not None
        assert marked.attributes.root["stale_since"].startswith("2027-01-15T")
    # Marked agents are no longer candidates.
    assert _plan(api)["candidates"] == []
    operations = {(r.kind, r.operation) for r in asyncio.run(api.audit_records())}
    assert ("after", "catalog.agent_mark_stale") in operations


def test_confirm_refuses_a_tampered_or_drifted_plan_and_applies_nothing() -> None:
    api = _stale_api()
    before = _versions(api)
    plan = _plan(api)

    forged_id = {**_confirm_body(plan), "plan_id": "plan-" + "0" * 48}
    assert (
        api.post(STEWARD_FINANCE, "/reconcile/stale-agents/confirm", forged_id).json()["code"]
        == "invalid_schema"
    )

    # A subset with a digest that matches ITS contents still differs from the live set.
    scope = asyncio.run(api.scope_of(STEWARD_FINANCE))
    first = plan["candidates"][0]
    subset = _confirm_body({**plan, "candidates": [first]})
    subset["plan_id"] = plan_digest(
        scope.scope_hash, plan["as_of"], plan["window_days"], [(first["agent_id"], first["etag"])]
    )
    refused = api.post(STEWARD_FINANCE, "/reconcile/stale-agents/confirm", subset)
    assert refused.status_code == 409
    assert refused.json()["code"] == "stale_version"

    # An agent edited after the dry run changes its ETag: the plan is stale.
    current = api.get(STEWARD_FINANCE, f"/entities/{first['agent_id']}")
    edited = api.put(
        STEWARD_FINANCE,
        f"/entities/{first['agent_id']}",
        {**current.json(), "display_name": "Edited"},
        current.headers["ETag"],
    )
    assert edited.status_code == 200
    drifted = api.post(STEWARD_FINANCE, "/reconcile/stale-agents/confirm", _confirm_body(plan))
    assert drifted.json()["code"] == "stale_version"
    after = _versions(api)
    assert after["stale-2"] == before["stale-2"]


def test_confirm_refuses_an_expired_plan_and_other_callers() -> None:
    api = _stale_api()
    plan = _plan(api)
    assert (
        api.post(VIEWER, "/reconcile/stale-agents/confirm", _confirm_body(plan)).status_code == 403
    )
    # A plan built for another caller's scope does not verify for this caller.
    other = api.post(STEWARD_BOTH, "/reconcile/stale-agents/confirm", _confirm_body(plan))
    assert other.json()["code"] == "invalid_schema"
    api.h.clock.advance(2 * 3600)
    expired = api.post(STEWARD_FINANCE, "/reconcile/stale-agents/confirm", _confirm_body(plan))
    assert expired.status_code == 409
    assert expired.json()["code"] == "stale_version"
    entity = api.stored(agent_id("stale-1"))
    assert entity is not None
    assert entity.attributes is None
