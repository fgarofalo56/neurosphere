"""Impact route: dependents of a failing node by depth, health, budget (PRP-74 item 3)."""

from impact_helpers import post_impact, twin  # pyright: ignore[reportMissingImports]
from map_api_helpers import (  # pyright: ignore[reportMissingImports]
    ALICE,
    FINANCE,
    agent_doc,
    agent_id,
    make_api,
    make_edge,
    put_points,
    service_doc,
    service_id,
    subject_point,
    tool_doc,
    tool_id,
)
from neurosphere_core.aggregates import subject_series_key


def _ids(level: dict) -> list[str]:  # pyright: ignore[reportMissingTypeArgument]
    return sorted(n["id"] for n in level["nodes"])


def test_impact_lists_exactly_the_downstream_agents_by_depth() -> None:
    t = twin()
    response = post_impact(t.api, ALICE, FINANCE, t.service, max_depth=3)
    assert response.status_code == 200
    body = response.json()
    assert body["direction"] == "dependents"
    assert body["domain_id"] == FINANCE
    assert body["node_id"] == t.service
    assert body["truncated"] is False
    levels = {lv["depth"]: lv for lv in body["levels"]}
    assert set(levels) == {1, 2}
    assert _ids(levels[1]) == sorted(t.downstream_depth_1)
    assert _ids(levels[2]) == sorted(t.downstream_depth_2)
    assert len(levels[1]["edge_ids"]) == 2
    assert len(levels[2]["edge_ids"]) == 1
    assert t.unrelated not in response.text
    assert t.service not in {n["id"] for lv in body["levels"] for n in lv["nodes"]}


def test_nodes_carry_kind_label_domain_and_measured_health() -> None:
    t = twin()
    body = post_impact(t.api, ALICE, FINANCE, t.service, max_depth=2).json()
    nodes = {n["id"]: n for lv in body["levels"] for n in lv["nodes"]}
    assert nodes[agent_id("a1")]["health"] == "failing"
    assert nodes[agent_id("a2")]["health"] == "ok"
    assert nodes[agent_id("b1")]["health"] == "unknown"  # no point: never guessed for agents
    assert all(n["health_inferred"] is False for n in nodes.values())
    assert all(n["kind"] == "agent" and n["domain_id"] == FINANCE for n in nodes.values())
    assert nodes[agent_id("a1")]["label"] == "Agent a1"


def test_depth_one_stops_at_direct_dependents() -> None:
    t = twin()
    one = post_impact(t.api, ALICE, FINANCE, t.service, max_depth=1).json()
    assert [lv["depth"] for lv in one["levels"]] == [1]
    assert one["truncated"] is False
    three = post_impact(t.api, ALICE, FINANCE, t.service, max_depth=3).json()
    assert [lv["depth"] for lv in three["levels"]] == [1, 2]


def test_leaf_node_has_no_levels() -> None:
    t = twin()
    body = post_impact(t.api, ALICE, FINANCE, t.unrelated, max_depth=3).json()
    assert body["levels"] == []
    assert body["truncated"] is False


def test_max_depth_outside_one_to_five_is_422() -> None:
    t = twin()
    assert post_impact(t.api, ALICE, FINANCE, t.service, max_depth=0).status_code == 422
    assert post_impact(t.api, ALICE, FINANCE, t.service, max_depth=6).status_code == 422
    assert post_impact(t.api, ALICE, FINANCE, t.service, max_depth=5).status_code == 200


def test_budget_truncates_with_a_reason() -> None:
    api = make_api()
    api.seed(service_doc("svc"), *[agent_doc(f"d{i}") for i in range(6)])
    api.seed_edges(
        *[
            make_edge(f"e{i}", agent_id(f"d{i}"), service_id("svc"), relation="depends_on")
            for i in range(6)
        ]
    )
    full = post_impact(api, ALICE, FINANCE, service_id("svc"), max_depth=1).json()
    assert sum(len(lv["nodes"]) for lv in full["levels"]) == 6
    assert full["truncated"] is False
    cut = post_impact(
        api, ALICE, FINANCE, service_id("svc"), max_depth=1, budget={"max_accessors": 2}
    ).json()
    assert cut["truncated"] is True
    assert cut["truncation_reason"] == "node_budget"
    assert sum(len(lv["nodes"]) for lv in cut["levels"]) <= 2


def test_service_without_a_point_gets_inferred_health_from_its_dependents() -> None:
    api = make_api()
    api.seed(
        agent_doc("root"),
        tool_doc("t"),
        agent_doc("u1"),
        agent_doc("u2"),
    )
    api.seed_edges(
        make_edge("t-root", tool_id("t"), agent_id("root"), relation="depends_on"),
        make_edge("u1-t", agent_id("u1"), tool_id("t"), relation="depends_on"),
        make_edge("u2-t", agent_id("u2"), tool_id("t"), relation="depends_on"),
    )
    put_points(
        api,
        subject_point(subject_series_key("agent", agent_id("u1")), error_rate=0.9),
        subject_point(subject_series_key("agent", agent_id("u2")), error_rate=0.9),
    )
    body = post_impact(api, ALICE, FINANCE, agent_id("root"), max_depth=2).json()
    nodes = {n["id"]: n for lv in body["levels"] for n in lv["nodes"]}
    assert nodes[tool_id("t")]["health"] == "failing"
    assert nodes[tool_id("t")]["health_inferred"] is True
    assert nodes[agent_id("u1")]["health_inferred"] is False
