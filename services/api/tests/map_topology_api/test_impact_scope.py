"""Impact route: identical 404s, authorization, pseudonyms, scope (PRP-74 item 3)."""

from typing import Any

from impact_helpers import post_impact  # pyright: ignore[reportMissingImports]
from map_api_helpers import (  # pyright: ignore[reportMissingImports]
    ALICE,
    BOB,
    FINANCE,
    OPERATIONS,
    STEWARD_BOTH,
    agent_doc,
    agent_id,
    make_api,
    make_edge,
    person_doc,
    service_doc,
    service_id,
)
from neurosphere_api.map.dependencies import get_access_engine
from neurosphere_core.catalog.graph.access import AccessResult, AccessRow, ScanBound

_STABLE = ("type", "title", "status", "detail", "code", "reason", "retryable")


def _stable(body: dict[str, Any]) -> dict[str, Any]:
    return {k: body.get(k) for k in _STABLE}


def test_missing_other_domain_and_unreadable_nodes_share_one_404_body() -> None:
    api = make_api()
    api.seed(service_doc("fin"), service_doc("ops", OPERATIONS), agent_doc("dep", OPERATIONS))
    api.seed_edges(
        make_edge("dep-ops", agent_id("dep"), service_id("ops"), OPERATIONS, relation="depends_on")
    )
    missing = post_impact(api, ALICE, FINANCE, service_id("nope"))
    other_domain_steward = post_impact(api, STEWARD_BOTH, FINANCE, service_id("ops"))
    unreadable = post_impact(api, ALICE, FINANCE, service_id("ops"))
    for response in (missing, other_domain_steward, unreadable):
        assert response.status_code == 404
    assert _stable(missing.json()) == _stable(other_domain_steward.json())
    assert _stable(missing.json()) == _stable(unreadable.json())
    assert missing.json()["code"] == "not_found"
    assert service_id("ops") not in unreadable.text.replace(unreadable.json()["instance"], "")
    assert agent_id("dep") not in unreadable.text


def test_caller_without_data_read_gets_403() -> None:
    api = make_api()
    api.seed(service_doc("fin"))
    assert post_impact(api, BOB, FINANCE, service_id("fin")).status_code == 403
    assert post_impact(api, ALICE, OPERATIONS, service_id("fin")).status_code == 403
    assert post_impact(api, None, FINANCE, service_id("fin")).status_code == 401


def test_person_dependent_appears_only_by_pseudonym() -> None:
    api = make_api()
    person = person_doc("janedoesmithaccount01", FINANCE)
    api.seed(service_doc("svc"), person)
    # Edge contracts forbid a person as a source, so a stub engine stands in for a store that
    # reports one, carrying the real-looking name the route must never copy.
    row = AccessRow(
        asset_id=service_id("svc"),
        accessor_id=person["id"],
        accessor_type="person",
        accessor_name="Jane Doe Smith",
        accessor_domain_id=FINANCE,
        mode=None,
        relation="depends_on",
        edge_id="commercial:contoso:neurosphere:depends_on:p-svc",
        status="inferred",
        confidence=0.5,
        provenance_method="test",
        provenance_source_id="test",
        evidence_ids=[],
        last_observed="2027-01-15T08:00:00Z",
        depth=1,
        relation_path=["depends_on"],
        path_node_ids=[person["id"], service_id("svc")],
    )

    class _Stub:
        async def dependents(self, *_: Any, **__: Any) -> AccessResult:
            bound = ScanBound(max_assets=1, max_accessors=1, timeout_ms=1, max_depth=2)
            return AccessResult(rows=[row], bound=bound)

    api.h.app.dependency_overrides[get_access_engine] = lambda: _Stub()
    response = post_impact(api, ALICE, FINANCE, service_id("svc"), max_depth=2)
    assert response.status_code == 200
    nodes = [n for lv in response.json()["levels"] for n in lv["nodes"]]
    assert [n["kind"] for n in nodes] == ["person"]
    assert nodes[0]["id"] == nodes[0]["label"]
    text = response.text.replace(response.json().get("instance", ""), "")
    assert "janedoe" not in text
    assert "Jane" not in text
    assert "psn_" not in text
    assert person["id"] not in text


def test_person_as_the_node_is_echoed_by_pseudonym() -> None:
    api = make_api()
    person = person_doc("janedoesmithaccount01", FINANCE)
    api.seed(person)
    response = post_impact(api, ALICE, FINANCE, person["id"])
    assert response.status_code == 200
    assert "janedoe" not in response.text
    assert response.json()["node_id"] != person["id"]


def test_out_of_scope_dependent_is_never_listed() -> None:
    api = make_api()
    api.seed(service_doc("svc"), agent_doc("fin"), agent_doc("ops", OPERATIONS))
    api.seed_edges(
        make_edge("fin-svc", agent_id("fin"), service_id("svc"), relation="depends_on"),
        make_edge("ops-svc", agent_id("ops"), service_id("svc"), OPERATIONS, relation="depends_on"),
    )
    for who in (ALICE, STEWARD_BOTH):
        body = post_impact(api, who, FINANCE, service_id("svc"), max_depth=3)
        assert body.status_code == 200
        ids = {n["id"] for lv in body.json()["levels"] for n in lv["nodes"]}
        assert ids == {agent_id("fin")}
        assert agent_id("ops") not in body.text
