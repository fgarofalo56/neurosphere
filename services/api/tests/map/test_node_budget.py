"""Viewport budgets: node clamp, truncation, cluster pagination, edge budget (PRP-18 item 2)."""

from map_api_helpers import (  # pyright: ignore[reportMissingImports]
    ALICE,
    FINANCE,
    agent_doc,
    agent_id,
    make_api,
    make_edge,
)
from neurosphere_api.map import MAX_VIEWPORT_NODES


def _agents(count: int) -> list[dict[str, object]]:
    return [agent_doc(f"a{i:05d}") for i in range(count)]


def test_small_domain_returns_every_node_untruncated() -> None:
    api = make_api()
    api.seed(*_agents(5))
    body = api.get(ALICE, FINANCE).json()
    assert len(body["nodes"]) == 5
    assert body["truncated"] is False
    assert body["truncation_reason"] is None
    assert body["next_cursor"] is None
    assert {n["kind"] for n in body["nodes"]} == {"agent"}


def test_request_for_50k_nodes_is_clamped_to_the_server_ceiling() -> None:
    api = make_api()
    api.seed(*_agents(MAX_VIEWPORT_NODES + 100))
    response = api.get(ALICE, FINANCE, node_budget=50_000, edge_budget=10_000_000)
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["nodes"]) <= MAX_VIEWPORT_NODES
    assert body["truncated"] is True
    assert body["truncation_reason"] == "node_budget"
    clusters = [n for n in body["nodes"] if n["kind"] == "cluster"]
    assert [c["member_count"] for c in clusters] == [MAX_VIEWPORT_NODES + 100]
    assert clusters[0]["id"] == clusters[0]["cluster_id"]


def test_expansion_with_oversized_budget_never_exceeds_the_ceiling() -> None:
    api = make_api()
    api.seed(*_agents(MAX_VIEWPORT_NODES + 50))
    body = api.get(ALICE, FINANCE, cluster_id="kind:agent", node_budget=50_000).json()
    assert len(body["nodes"]) == MAX_VIEWPORT_NODES
    assert body["truncated"] is True
    assert body["next_cursor"] is not None


def test_cluster_pagination_round_trip_covers_every_member_once() -> None:
    api = make_api()
    api.seed(*_agents(95))
    api.limits(max_nodes=40)
    top = api.get(ALICE, FINANCE, node_budget=40).json()
    assert top["truncated"] is True
    cluster = top["nodes"][0]
    assert cluster["kind"] == "cluster"
    assert cluster["member_count"] == 95

    seen: list[str] = []
    cursor: str | None = None
    pages = 0
    while True:
        params: dict[str, object] = {"cluster_id": cluster["cluster_id"], "node_budget": 40}
        if cursor is not None:
            params["cursor"] = cursor
        page = api.get(ALICE, FINANCE, **params).json()
        pages += 1
        assert len(page["nodes"]) <= 40
        assert all(n["cluster_id"] == cluster["cluster_id"] for n in page["nodes"])
        seen.extend(n["id"] for n in page["nodes"])
        cursor = page["next_cursor"]
        if cursor is None:
            assert page["truncated"] is False
            break
        assert page["truncated"] is True
    assert pages == 3
    assert len(seen) == 95
    assert len(set(seen)) == 95


def test_cursor_of_another_cluster_or_garbage_is_rejected() -> None:
    api = make_api()
    api.seed(*_agents(10))
    api.limits(max_nodes=4)
    first = api.get(ALICE, FINANCE, cluster_id="kind:agent", node_budget=4).json()
    cursor = first["next_cursor"]
    assert cursor
    assert api.get(ALICE, FINANCE, cluster_id="kind:person", cursor=cursor).status_code == 422
    assert api.get(ALICE, FINANCE, cluster_id="kind:agent", cursor="!!!").status_code == 422
    assert api.get(ALICE, FINANCE, cursor=cursor).status_code == 422
    assert api.get(ALICE, FINANCE, cluster_id="kind:nope").status_code == 422


def test_edge_budget_truncates_edges_and_flags_it() -> None:
    api = make_api()
    api.seed(*_agents(8))
    api.seed_edges(
        *(make_edge(f"e{i}", agent_id(f"a{i:05d}"), agent_id(f"a{i + 1:05d}")) for i in range(7))
    )
    full = api.get(ALICE, FINANCE).json()
    assert len(full["edges"]) == 7
    assert full["truncated"] is False
    cut = api.get(ALICE, FINANCE, edge_budget=3).json()
    assert len(cut["edges"]) == 3
    assert cut["truncated"] is True
    assert cut["truncation_reason"] == "edge_budget"
    api.limits(max_nodes=2000, max_edges=2)
    clamped = api.get(ALICE, FINANCE, edge_budget=1_000_000).json()
    assert len(clamped["edges"]) == 2
    assert clamped["truncation_reason"] == "edge_budget"


def test_budget_below_one_is_a_validation_error() -> None:
    api = make_api()
    assert api.get(ALICE, FINANCE, node_budget=0).status_code == 422
    assert api.get(ALICE, FINANCE, edge_budget=0).status_code == 422
