"""``POST /api/v1/catalog/access/dependents`` (PRP-73 item 3)."""

from __future__ import annotations

from typing import Any

import pytest
from authz.authz_helpers import FINANCE, OPERATIONS  # pyright: ignore[reportMissingImports]
from catalog_access_support import DEPENDENTS, build_world  # pyright: ignore[reportMissingImports]
from ui_adapters_api.adapter_support import (  # pyright: ignore[reportMissingImports]
    AUDITOR,
    STEWARD_BOTH,
    VIEWER,
    World,
    agent_id,
    make_edge,
)


@pytest.fixture
def world() -> World:
    w = build_world()
    # ops-b1 -> fin-a1 -> fin-a2 (the arrow is "invokes"): fin-a2 fails, fin-a1 and ops-b1 depend.
    w.seed_edges(
        make_edge("i-a1-a2", "fin-a1", "fin-a2", FINANCE),
        make_edge("i-b1-a1", "ops-b1", "fin-a1", OPERATIONS),
    )
    return w


def _ask(world: World, who: str, body: dict[str, Any]) -> dict[str, Any]:
    response = world.post(who, DEPENDENTS, body)
    assert response.status_code == 200, response.text
    return response.json()


def test_dependents_are_grouped_by_depth_with_the_relation_path(world: World) -> None:
    data = _ask(world, STEWARD_BOTH, {"node_id": agent_id("fin-a2"), "max_depth": 3})
    assert [g["depth"] for g in data["groups"]] == [1, 2]
    first, second = (g["rows"] for g in data["groups"])
    assert [r["accessor_id"] for r in first] == [agent_id("fin-a1")]
    assert [r["accessor_id"] for r in second] == [agent_id("ops-b1")]
    assert second[0]["relation_path"] == ["invokes", "invokes"]
    assert second[0]["path_node_ids"][-1] == agent_id("fin-a2")
    assert second[0]["mode"] is None
    assert data["total"] == 2
    for key in ("truncated", "truncated_reason", "assets_scanned", "bound"):
        assert key in data
    assert data["bound"]["max_depth"] == 3


def test_max_depth_one_stops_at_the_first_ring(world: World) -> None:
    data = _ask(world, STEWARD_BOTH, {"node_id": agent_id("fin-a2"), "max_depth": 1})
    assert [g["depth"] for g in data["groups"]] == [1]
    assert data["total"] == 1


def test_out_of_scope_dependents_never_appear(world: World) -> None:
    response = world.post(VIEWER, DEPENDENTS, {"node_id": agent_id("fin-a2"), "max_depth": 5})
    assert response.status_code == 200
    assert [r["accessor_id"] for g in response.json()["groups"] for r in g["rows"]] == [
        agent_id("fin-a1")
    ]
    assert "ops-b1" not in response.text and OPERATIONS not in response.text


def test_unreadable_node_looks_like_a_node_nobody_depends_on(world: World) -> None:
    hidden = world.post(VIEWER, DEPENDENTS, {"node_id": agent_id("ops-b1"), "max_depth": 2})
    missing = world.post(VIEWER, DEPENDENTS, {"node_id": agent_id("nope"), "max_depth": 2})
    assert hidden.status_code == missing.status_code == 200
    assert hidden.json()["groups"] == [] and hidden.json()["total"] == 0
    assert hidden.json()["truncated"] is False


@pytest.mark.parametrize(("depth", "reason"), [(6, "max_depth_exceeded"), (0, "invalid_depth")])
def test_invalid_depth_is_422_with_a_reason(world: World, depth: int, reason: str) -> None:
    response = world.post(
        STEWARD_BOTH, DEPENDENTS, {"node_id": agent_id("fin-a2"), "max_depth": depth}
    )
    assert response.status_code == 422
    assert response.json()["reason"] == reason


def test_a_small_budget_labels_the_answer_partial(world: World) -> None:
    data = _ask(
        world,
        STEWARD_BOTH,
        {"node_id": agent_id("fin-a2"), "max_depth": 3, "budget": {"max_accessors": 1}},
    )
    assert data["truncated"] is True
    assert data["truncated_reason"] == "max_accessors"
    assert data["total"] <= 1
    assert data["bound"]["max_accessors"] == 1


@pytest.mark.parametrize("field", ["customer_id", "cloud", "domain_id"])
def test_body_supplied_scope_is_refused(world: World, field: str) -> None:
    body = {"node_id": agent_id("fin-a2"), "max_depth": 2, field: OPERATIONS}
    assert world.post(VIEWER, DEPENDENTS, body).status_code == 422


def test_no_data_read_permission_is_403(world: World) -> None:
    body = {"node_id": agent_id("fin-a2"), "max_depth": 2}
    assert world.post(AUDITOR, DEPENDENTS, body).status_code == 403
