"""Derived health of a service, tool or MCP server (PRP-74 item 1, criterion 4)."""

from typing import Any

import pytest
from map_api_helpers import (  # pyright: ignore[reportMissingImports]
    ALICE,
    FINANCE,
    agent_doc,
    agent_id,
    make_api,
    make_edge,
    mcp_doc,
    model_doc,
    put_points,
    service_doc,
    service_id,
    subject_point,
    tool_doc,
    tool_id,
)
from neurosphere_api.map.facets import derive_health
from neurosphere_api.map.service import model_deployment_ids
from neurosphere_contracts.catalog.v1.model_deployment import ModelDeployment

MCP = "commercial:contoso:neurosphere:mcp_server:ledger"
FAIL = 0.5
DEGRADE = 0.34


def _derive(*health: Any) -> str:
    return derive_health(list(health), failing_ratio=FAIL, degraded_ratio=DEGRADE)


def _agent_point(name: str, rate: float) -> Any:
    return subject_point(
        f"agent:{agent_id(name)}", events=20, error_count=int(rate * 20), error_rate=rate
    )


def _nodes(api: Any) -> dict[str, dict[str, Any]]:
    return {n["id"]: n for n in api.get(ALICE, FINANCE).json()["nodes"]}


def test_derive_health_rules() -> None:
    assert _derive("failing", "failing") == "failing"
    assert _derive("failing", "failing", "ok") == "failing"  # 2/3 >= 0.5
    assert _derive("failing", "failing", "ok", "ok") == "failing"  # 2/4 >= 0.5
    assert _derive("failing", "failing", "ok", "ok", "ok") == "degraded"  # 2/5 < 0.5, >= 0.34
    assert _derive("degraded", "failing", "ok") == "degraded"
    assert _derive("degraded", "degraded", "ok", "ok") == "degraded"
    assert _derive("degraded", "ok", "ok") == "unknown"


def test_at_least_two_dependents_are_needed() -> None:
    assert _derive() == "unknown"
    assert _derive("failing") == "unknown"
    assert _derive("failing", "ok") == "unknown"  # one failing is not enough
    assert _derive("degraded", "ok") == "unknown"


@pytest.mark.parametrize(
    "dependents",
    [[], ["ok"], ["ok", "ok", "ok"], ["unknown", "unknown"], ["failing", "ok", "ok", "ok", "ok"]],
)
def test_inference_never_says_ok(dependents: list[Any]) -> None:
    assert _derive(*dependents) != "ok"


def test_incident_world_failing_service_with_downstream_agents() -> None:
    api = make_api()
    api.seed(
        service_doc("orders"),
        agent_doc("d1"),
        agent_doc("d2"),
        agent_doc("d3"),
        agent_doc("u1"),
        agent_doc("u2"),
    )
    api.seed_edges(
        make_edge("d1", agent_id("d1"), service_id("orders"), relation="depends_on"),
        make_edge("d2", agent_id("d2"), service_id("orders"), relation="depends_on"),
        make_edge("d3", agent_id("d3"), service_id("orders"), relation="depends_on"),
    )
    put_points(
        api,
        _agent_point("d1", 0.4),
        _agent_point("d2", 0.5),
        _agent_point("d3", 0.3),
        _agent_point("u1", 0.0),
        _agent_point("u2", 0.0),
    )
    nodes = _nodes(api)
    service = nodes[service_id("orders")]
    assert service["metrics"]["health"] == "failing"
    assert service["facets"]["health"] == "failing"
    assert service["health_inferred"] is True
    assert service["facets"]["error_rate"] is None  # inferred health carries no measured numbers
    for name in ("d1", "d2", "d3"):
        assert nodes[agent_id(name)]["metrics"]["health"] == "failing"
        assert nodes[agent_id(name)]["health_inferred"] is False
    for name in ("u1", "u2"):
        assert nodes[agent_id(name)]["metrics"]["health"] == "ok"


def test_a_measured_point_wins_over_the_dependents_rule() -> None:
    api = make_api()
    api.seed(service_doc("orders"), agent_doc("d1"), agent_doc("d2"))
    api.seed_edges(
        make_edge("d1", agent_id("d1"), service_id("orders"), relation="depends_on"),
        make_edge("d2", agent_id("d2"), service_id("orders"), relation="depends_on"),
    )
    put_points(
        api,
        _agent_point("d1", 0.5),
        _agent_point("d2", 0.5),
        subject_point(
            f"service:{service_id('orders')}", events=100, error_count=1, error_rate=0.01
        ),
    )
    service = _nodes(api)[service_id("orders")]
    assert service["metrics"]["health"] == "ok"
    assert service["facets"]["health"] == "ok"
    assert service["facets"]["error_count"] == 1
    assert service["facets"]["request_count"] == 100
    assert service["health_inferred"] is False


def test_tool_with_a_point_uses_it_and_a_degraded_service_reads_its_point() -> None:
    api = make_api()
    api.seed(tool_doc("lookup"), service_doc("orders"))
    put_points(
        api,
        subject_point(f"tool:{tool_id('lookup')}", error_count=5, error_rate=0.1),
        subject_point(f"service:{service_id('orders')}", error_count=30, error_rate=0.3),
    )
    nodes = _nodes(api)
    assert nodes[tool_id("lookup")]["facets"]["health"] == "degraded"
    assert nodes[service_id("orders")]["facets"]["health"] == "failing"


def test_tool_and_mcp_server_fall_back_to_dependents_and_stay_unknown_otherwise() -> None:
    api = make_api()
    api.seed(
        tool_doc("lookup"),
        mcp_doc("ledger"),
        agent_doc("d1"),
        agent_doc("d2"),
        agent_doc("d3"),
    )
    api.seed_edges(
        make_edge("t1", agent_id("d1"), tool_id("lookup")),
        make_edge("t2", agent_id("d2"), tool_id("lookup")),
    )
    put_points(api, _agent_point("d1", 0.3), _agent_point("d2", 0.3), _agent_point("d3", 0.0))
    nodes = _nodes(api)
    assert nodes[tool_id("lookup")]["metrics"]["health"] == "failing"
    assert nodes[tool_id("lookup")]["health_inferred"] is True
    # the edge contracts cannot target an MCP server, so it has no dependents: unknown, never ok
    assert nodes[MCP]["metrics"]["health"] == "unknown"
    assert nodes[MCP]["facets"]["health"] == "unknown"
    assert nodes[MCP]["health_inferred"] is False


def test_dependents_without_a_point_do_not_count_as_failing() -> None:
    api = make_api()
    api.seed(service_doc("orders"), agent_doc("d1"), agent_doc("d2"))
    api.seed_edges(
        make_edge("d1", agent_id("d1"), service_id("orders"), relation="depends_on"),
        make_edge("d2", agent_id("d2"), service_id("orders"), relation="depends_on"),
    )
    assert _nodes(api)[service_id("orders")]["metrics"]["health"] == "unknown"


def test_model_deployment_ids_maps_provider_and_model_to_every_deployment() -> None:
    from neurosphere_core.catalog.repo.documents import parse_entity

    def entity(name: str, **patch: Any) -> ModelDeployment:
        doc = model_doc(name)
        doc.update(patch)
        parsed = parse_entity(doc)
        assert isinstance(parsed, ModelDeployment)
        return parsed

    one = entity("dep-1")
    two = entity("dep-2")
    other = entity("dep-3", model_name="gpt-35")
    provider = str(getattr(one.provider, "root", one.provider))
    ids = model_deployment_ids([one, two, other], provider.upper(), one.model_name.upper())
    assert ids == sorted([one.id, two.id])
    assert model_deployment_ids([one, two, other], "nobody", "nothing") == []
    assert model_deployment_ids([], provider, one.model_name) == []
