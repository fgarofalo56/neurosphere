"""Services, tools and MCP servers are map nodes (PRP-74 item 1, criterion 1)."""

from map_api_helpers import (  # pyright: ignore[reportMissingImports]
    ALICE,
    FINANCE,
    OPERATIONS,
    agent_doc,
    agent_id,
    make_api,
    make_edge,
    mcp_doc,
    service_doc,
    service_id,
    tool_doc,
    tool_id,
)

MCP = "commercial:contoso:neurosphere:mcp_server:ledger"


def test_service_tool_and_mcp_server_appear_with_their_kinds_and_labels() -> None:
    api = make_api()
    api.seed(service_doc("orders"), tool_doc("lookup"), mcp_doc("ledger"))
    body = api.get(ALICE, FINANCE).json()
    kinds = {n["id"]: (n["kind"], n["label"]) for n in body["nodes"]}
    assert kinds[service_id("orders")] == ("service", "Service orders")
    assert kinds[tool_id("lookup")] == ("tool", "Tool lookup")
    assert kinds[MCP] == ("mcp_server", "Mcp ledger")
    assert all(n["facets"] is not None for n in body["nodes"])


def test_over_budget_they_cluster_in_their_own_clusters() -> None:
    api = make_api()
    api.seed(
        agent_doc("alpha"),
        service_doc("orders"),
        service_doc("billing"),
        tool_doc("lookup"),
        mcp_doc("ledger"),
    )
    api.limits(max_nodes=4)  # 5 entities are over budget; 4 clusters fit
    body = api.get(ALICE, FINANCE).json()
    clusters = {n["id"]: n for n in body["nodes"] if n["kind"] == "cluster"}
    assert body["truncated"] is True
    assert clusters["kind:service"]["member_count"] == 2
    assert clusters["kind:service"]["label"] == "Services"
    assert clusters["kind:tool"]["member_count"] == 1
    assert clusters["kind:mcp_server"]["member_count"] == 1
    page = api.get(ALICE, FINANCE, cluster_id="kind:service").json()
    assert {n["id"] for n in page["nodes"]} == {service_id("orders"), service_id("billing")}
    assert {n["kind"] for n in page["nodes"]} == {"service"}


def test_edges_to_and_from_the_new_kinds_appear_both_endpoints_present() -> None:
    api = make_api()
    api.seed(agent_doc("alpha"), service_doc("orders"), tool_doc("lookup"))
    api.seed_edges(
        make_edge("a-t", agent_id("alpha"), tool_id("lookup")),
        make_edge("t-s", tool_id("lookup"), service_id("orders"), relation="depends_on"),
        make_edge("a-s", agent_id("alpha"), service_id("orders"), relation="depends_on"),
    )
    body = api.get(ALICE, FINANCE).json()
    pairs = {(e["source"], e["target"]) for e in body["edges"]}
    assert pairs == {
        (agent_id("alpha"), tool_id("lookup")),
        (tool_id("lookup"), service_id("orders")),
        (agent_id("alpha"), service_id("orders")),
    }


def test_orphan_edge_to_a_service_in_another_domain_is_dropped() -> None:
    api = make_api()
    api.seed(agent_doc("alpha"), service_doc("orders"), service_doc("ops-svc", OPERATIONS))
    api.seed_edges(make_edge("a-s", agent_id("alpha"), service_id("orders"), relation="depends_on"))
    body = api.get(ALICE, FINANCE).json()
    ids = {n["id"] for n in body["nodes"]}
    assert service_id("ops-svc") not in ids
    assert all(e["source"] in ids and e["target"] in ids for e in body["edges"])
