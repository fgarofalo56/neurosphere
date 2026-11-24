"""Viewport filters: node_type, tag, environment, cloud, health (PRP-74 item 2)."""

from typing import Any

import pytest
from map_api_helpers import (  # pyright: ignore[reportMissingImports]
    ALICE,
    FINANCE,
    Api,
    agent_doc,
    agent_id,
    make_api,
    put_points,
    service_doc,
    service_id,
    subject_point,
    tool_doc,
    tool_id,
)
from neurosphere_core.aggregates import subject_series_key


def _world() -> Api:
    api = make_api()
    api.seed(
        agent_doc("a1", FINANCE) | {"environment": "production", "tags": ["payments"]},
        agent_doc("a2", FINANCE) | {"environment": "staging", "tags": ["internal"]},
        tool_doc("t1", FINANCE) | {"environment": "production", "tags": ["payments", "pii"]},
        service_doc("s1", FINANCE) | {"environment": "staging", "tags": []},
    )
    put_points(
        api,
        subject_point(
            subject_series_key("agent", agent_id("a1")), error_count=9, error_rate=0.9, events=10
        ),
        subject_point(subject_series_key("agent", agent_id("a2")), error_count=0, error_rate=0.0),
    )
    return api


def _ids(body: dict[str, Any]) -> set[str]:
    return {n["id"] for n in body["nodes"]}


def test_no_filter_is_unchanged_and_reports_none_applied() -> None:
    api = _world()
    body = api.get(ALICE, FINANCE).json()
    assert body["filters_applied"] is None
    assert _ids(body) == {agent_id("a1"), agent_id("a2"), tool_id("t1"), service_id("s1")}


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({"node_type": "agent"}, {"a1", "a2"}),
        ({"node_type": ["agent", "tool"]}, {"a1", "a2", "t1"}),
        ({"tag": "payments"}, {"a1", "t1"}),
        ({"tag": ["pii", "internal"]}, {"t1", "a2"}),
        ({"environment": "production"}, {"a1", "t1"}),
        ({"environment": "staging"}, {"a2", "s1"}),
        ({"cloud": "commercial"}, {"a1", "a2", "t1", "s1"}),
        ({"cloud": "government"}, set()),
        ({"health": "failing"}, {"a1"}),
        ({"health": "ok"}, {"a2"}),
        ({"health": "unknown"}, {"t1", "s1"}),
    ],
)
def test_each_filter_alone(params: dict[str, Any], expected: set[str]) -> None:
    api = _world()
    body = api.get(ALICE, FINANCE, **params).json()
    ids = {n["id"].rsplit(":", 1)[-1] for n in body["nodes"]}
    assert ids == expected
    applied = body["filters_applied"]
    for key, value in params.items():
        assert applied[key] == ([value] if isinstance(value, str) else value)


def test_filters_combine_with_and() -> None:
    api = _world()
    body = api.get(ALICE, FINANCE, node_type="agent", environment="production", tag="payments")
    assert {n["id"] for n in body.json()["nodes"]} == {agent_id("a1")}
    both = api.get(ALICE, FINANCE, tag="payments", health="failing").json()
    assert _ids(both) == {agent_id("a1")}
    none = api.get(ALICE, FINANCE, node_type="tool", health="failing").json()
    assert none["nodes"] == []


def test_cluster_counts_reflect_only_matching_entities() -> None:
    api = _world()
    unfiltered = api.get(ALICE, FINANCE, node_budget=1).json()
    counts = {n["id"]: n["member_count"] for n in unfiltered["nodes"]}
    assert counts == {"kind:agent": 2, "kind:service": 1, "kind:tool": 1}
    filtered = api.get(ALICE, FINANCE, node_budget=1, environment="production").json()
    counts = {n["id"]: n["member_count"] for n in filtered["nodes"]}
    assert counts == {"kind:agent": 1, "kind:tool": 1}
    assert filtered["filters_applied"]["environment"] == ["production"]


def test_cluster_page_is_filtered() -> None:
    api = _world()
    body = api.get(ALICE, FINANCE, cluster_id="kind:agent", tag="payments").json()
    assert _ids(body) == {agent_id("a1")}


@pytest.mark.parametrize(
    "params",
    [
        {"node_type": "robot"},
        {"node_type": "cluster"},
        {"environment": "prod"},
        {"cloud": "azure"},
        {"health": "great"},
        {"tag": "x" * 200},
        {"environment": ["production", "nope"]},
    ],
)
def test_unknown_filter_value_is_422_invalid_filter(params: dict[str, Any]) -> None:
    api = _world()
    response = api.get(ALICE, FINANCE, **params)
    assert response.status_code == 422
    assert response.json()["reason"] == "invalid_filter"
