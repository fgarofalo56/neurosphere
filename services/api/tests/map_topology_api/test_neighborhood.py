"""Neighbourhood route: both directions, clamps, identical 404s, authorization (PRP-74 item 2)."""

from typing import Any

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
    tool_doc,
    tool_id,
)
from topology_helpers import get_neighborhood  # pyright: ignore[reportMissingImports]

_STABLE = ("type", "title", "status", "detail", "code", "reason", "retryable")


def _stable(body: dict[str, Any]) -> dict[str, Any]:
    return {k: body.get(k) for k in _STABLE}


def test_node_and_neighbours_in_both_directions() -> None:
    api = make_api()
    api.seed(
        agent_doc("hub", FINANCE),
        agent_doc("caller", FINANCE),
        tool_doc("used", FINANCE),
        service_doc("far", FINANCE),
    )
    api.seed_edges(
        make_edge("out", agent_id("hub"), tool_id("used")),
        make_edge("in", agent_id("caller"), agent_id("hub")),
        make_edge("two-hops", agent_id("caller"), service_id("far"), relation="depends_on"),
    )
    response = get_neighborhood(api, ALICE, FINANCE, agent_id("hub"))
    assert response.status_code == 200
    body = response.json()
    ids = {n["id"] for n in body["nodes"]}
    assert ids == {agent_id("hub"), agent_id("caller"), tool_id("used")}
    assert body["nodes"][0]["id"] == agent_id("hub")
    assert body["truncated"] is False
    pairs = {(e["source"], e["target"]) for e in body["edges"]}
    assert pairs == {
        (agent_id("hub"), tool_id("used")),
        (agent_id("caller"), agent_id("hub")),
    }
    assert all(n["facets"] is not None for n in body["nodes"])


def test_node_budget_is_clamped_and_reported() -> None:
    api = make_api()
    api.seed(agent_doc("hub", FINANCE), *[tool_doc(f"t{i:02d}", FINANCE) for i in range(10)])
    api.seed_edges(
        *[make_edge(f"e{i:02d}", agent_id("hub"), tool_id(f"t{i:02d}")) for i in range(10)]
    )
    full = get_neighborhood(api, ALICE, FINANCE, agent_id("hub")).json()
    assert len(full["nodes"]) == 11
    assert full["truncated"] is False
    clamped = get_neighborhood(api, ALICE, FINANCE, agent_id("hub"), node_budget=4).json()
    assert len(clamped["nodes"]) == 4
    assert clamped["nodes"][0]["id"] == agent_id("hub")
    assert clamped["truncated"] is True
    assert clamped["truncation_reason"] == "node_budget"
    ids = {n["id"] for n in clamped["nodes"]}
    assert all(e["source"] in ids and e["target"] in ids for e in clamped["edges"])
    # The server ceiling wins over a huge request.
    api.limits(max_nodes=3)
    capped = get_neighborhood(api, ALICE, FINANCE, agent_id("hub"), node_budget=100_000).json()
    assert len(capped["nodes"]) == 3
    assert capped["truncated"] is True


def test_edge_budget_is_clamped_and_reported() -> None:
    api = make_api()
    api.seed(agent_doc("hub", FINANCE), *[tool_doc(f"t{i}", FINANCE) for i in range(5)])
    api.seed_edges(*[make_edge(f"e{i}", agent_id("hub"), tool_id(f"t{i}")) for i in range(5)])
    body = get_neighborhood(api, ALICE, FINANCE, agent_id("hub"), edge_budget=2).json()
    assert len(body["nodes"]) == 6
    assert len(body["edges"]) == 2
    assert body["truncated"] is True
    assert body["truncation_reason"] == "edge_budget"


def test_neighbour_in_another_domain_is_not_returned() -> None:
    api = make_api()
    api.seed(agent_doc("fin", FINANCE), agent_doc("ops", OPERATIONS))
    api.seed_edges(make_edge("cross", agent_id("fin"), agent_id("ops"), FINANCE))
    response = get_neighborhood(api, ALICE, FINANCE, agent_id("fin"))
    assert [n["id"] for n in response.json()["nodes"]] == [agent_id("fin")]
    assert agent_id("ops") not in response.text


def test_person_node_is_shown_by_pseudonym_only() -> None:
    api = make_api()
    person = person_doc("janedoesmithaccount01", FINANCE)
    api.seed(agent_doc("hub", FINANCE), person)
    response = get_neighborhood(api, ALICE, FINANCE, person["id"])
    assert response.status_code == 200
    nodes = response.json()["nodes"]
    assert [n["kind"] for n in nodes] == ["person"]
    assert nodes[0]["id"] == nodes[0]["label"]
    assert "janedoe" not in response.text.replace(response.json().get("instance", ""), "")
    assert "psn_" not in response.text


def test_missing_other_domain_and_out_of_scope_nodes_share_one_404_body() -> None:
    api = make_api()
    api.seed(agent_doc("fin", FINANCE), agent_doc("ops", OPERATIONS))
    missing = get_neighborhood(api, ALICE, FINANCE, agent_id("nope"))
    other_domain_steward = get_neighborhood(api, STEWARD_BOTH, FINANCE, agent_id("ops"))
    out_of_scope = get_neighborhood(api, ALICE, FINANCE, agent_id("ops"))
    for response in (missing, other_domain_steward, out_of_scope):
        assert response.status_code == 404
    assert _stable(missing.json()) == _stable(other_domain_steward.json())
    assert _stable(missing.json()) == _stable(out_of_scope.json())
    assert missing.json()["code"] == "not_found"
    assert agent_id("ops") not in out_of_scope.text.replace(out_of_scope.json()["instance"], "")


def test_caller_without_data_read_gets_403() -> None:
    api = make_api()
    api.seed(agent_doc("fin", FINANCE))
    assert get_neighborhood(api, BOB, FINANCE, agent_id("fin")).status_code == 403
    assert get_neighborhood(api, ALICE, OPERATIONS, agent_id("fin")).status_code == 403
    assert get_neighborhood(api, None, FINANCE, agent_id("fin")).status_code == 401
