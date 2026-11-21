"""``POST /api/v1/catalog/access/query`` and ``GET /access/region-groups`` (PRP-73 item 3)."""

from __future__ import annotations

from typing import Any

import pytest
from authz.authz_helpers import FINANCE, OPERATIONS  # pyright: ignore[reportMissingImports]
from catalog_access_support import (  # pyright: ignore[reportMissingImports]
    ACCESS,
    REGION_GROUPS,
    asset_id,
    build_world,
)
from ui_adapters_api.adapter_support import (  # pyright: ignore[reportMissingImports]
    AUDITOR,
    STEWARD_BOTH,
    VIEWER,
    World,
    agent_id,
)

ENVELOPE_KEYS = ("truncated", "truncated_reason", "assets_scanned", "bound")


@pytest.fixture
def world() -> World:
    return build_world()


def _ask(world: World, who: str, body: dict[str, Any]) -> dict[str, Any]:
    response = world.post(who, ACCESS, body)
    assert response.status_code == 200, response.text
    return response.json()


def _accessors(data: dict[str, Any]) -> set[str]:
    return {r["accessor_id"] for r in data["rows"]}


def test_writers_of_an_asset_carry_edge_evidence(world: World) -> None:
    data = _ask(world, STEWARD_BOTH, {"asset_ids": [asset_id("customers")], "modes": ["write"]})
    assert _accessors(data) == {agent_id("fin-a1")}
    row = data["rows"][0]
    assert row["mode"] == "write"
    assert row["relation"] == "writes"
    assert row["status"] == "inferred"
    assert row["asset_id"] == asset_id("customers")
    assert isinstance(row["confidence"], float)
    assert row["provenance_method"] and row["provenance_source_id"]
    assert row["evidence_ids"] and row["last_observed"]
    assert row["depth"] == 1


def test_every_response_carries_the_truncation_envelope(world: World) -> None:
    data = _ask(world, VIEWER, {"asset_ids": [asset_id("customers")]})
    for key in ENVELOPE_KEYS:
        assert key in data
    assert data["truncated"] is False
    assert data["truncated_reason"] is None
    assert data["assets_scanned"] == 1


def test_out_of_scope_accessor_never_appears(world: World) -> None:
    response = world.post(VIEWER, ACCESS, {"asset_ids": [asset_id("customers")]})
    assert response.status_code == 200
    data = response.json()
    assert _accessors(data) == {agent_id("fin-a1"), agent_id("fin-a2")}
    assert "ops-b1" not in response.text
    assert OPERATIONS not in response.text


def test_out_of_scope_asset_is_indistinguishable_from_missing(world: World) -> None:
    hidden = world.post(VIEWER, ACCESS, {"asset_ids": [asset_id("ledger")]})
    missing = world.post(VIEWER, ACCESS, {"asset_ids": [asset_id("no-such-asset")]})
    assert hidden.status_code == missing.status_code == 200
    assert hidden.json()["rows"] == [] and hidden.json()["assets"] == []
    assert hidden.json()["assets_scanned"] == missing.json()["assets_scanned"] == 0
    assert "ledger" not in hidden.text and OPERATIONS not in hidden.text


@pytest.mark.parametrize("field", ["customer_id", "cloud", "domain_id", "allowed_domains", "scope"])
def test_body_supplied_scope_is_not_honoured(world: World, field: str) -> None:
    value: Any = OPERATIONS if field != "allowed_domains" else [OPERATIONS]
    response = world.post(VIEWER, ACCESS, {"asset_ids": [asset_id("ledger")], field: value})
    # Request models forbid extra fields, like the lineage requests: refused, never honoured.
    assert response.status_code == 422
    assert "ops-b1" not in response.text
    assert "ledger" not in response.text


def test_domain_filter_narrows_within_scope_never_widens(world: World) -> None:
    widened = _ask(world, VIEWER, {"filters": {"domain_ids": [OPERATIONS]}})
    assert widened["assets"] == [] and widened["rows"] == []
    both = _ask(world, VIEWER, {"filters": {"domain_ids": [FINANCE, OPERATIONS]}})
    # A domain-only filter matches every FINANCE asset and nothing from OPERATIONS.
    assert {a["id"] for a in both["assets"]} == {
        asset_id("customers"),
        asset_id("claims"),
        asset_id("mystery"),
    }
    unfiltered = _ask(world, VIEWER, {})
    assert {a["domain_id"] for a in unfiltered["assets"]} == {FINANCE}


def test_sensitivity_category_filter_and_unassessed(world: World) -> None:
    body: dict[str, Any] = {"filters": {"sensitivity_categories": ["pii"]}}
    data = _ask(world, STEWARD_BOTH, body)
    assert {a["id"] for a in data["assets"]} == {asset_id("customers"), asset_id("ledger")}
    assert data["unassessed_assets"] is None and data["unassessed_count"] is None

    with_flag = _ask(world, STEWARD_BOTH, {**body, "include_unassessed": True})
    assert with_flag["unassessed_count"] == 1
    assert [a["id"] for a in with_flag["unassessed_assets"]] == [asset_id("mystery")]
    mystery = with_flag["unassessed_assets"][0]
    assert mystery["sensitivity_categories"] is None
    assert mystery["contains_personal_data"] is None
    assert _accessors(with_flag) == _accessors(data)  # unassessed assets add no accessors


def test_contains_personal_data_filter_never_treats_null_as_false(world: World) -> None:
    data = _ask(
        world,
        STEWARD_BOTH,
        {"filters": {"contains_personal_data": False}, "include_unassessed": True},
    )
    assert data["assets"] == []
    assert [a["id"] for a in data["unassessed_assets"]] == [asset_id("mystery")]


def test_eu_region_group_and_union_with_explicit_regions(world: World) -> None:
    eu = _ask(world, STEWARD_BOTH, {"filters": {"region_group": "eu"}})
    assert {a["id"] for a in eu["assets"]} == {asset_id("customers"), asset_id("ledger")}
    union = _ask(
        world, STEWARD_BOTH, {"filters": {"region_group": "eu", "residency_regions": ["eastus"]}}
    )
    assert {a["id"] for a in union["assets"]} == {
        asset_id("customers"),
        asset_id("ledger"),
        asset_id("claims"),
    }


def test_max_assets_budget_labels_the_answer_partial(world: World) -> None:
    data = _ask(world, STEWARD_BOTH, {"budget": {"max_assets": 1}})
    assert data["truncated"] is True
    assert data["truncated_reason"] == "max_assets"
    assert data["assets_scanned"] == 1


def _reason(response: Any) -> str | None:
    return response.json().get("reason")


@pytest.mark.parametrize(
    ("body", "reason"),
    [
        ({"filters": {"region_group": "mars"}}, "unknown_region_group"),
        ({"filters": {"residency_regions": ["not a region!"]}}, "unknown_region"),
        ({"filters": {"residency_regions": ["atlantis"]}}, "unknown_region"),
        ({"filters": {"residency_regions": ["usgovvirginia"]}}, "unknown_region"),
        ({"asset_ids": [f"x:{i}" for i in range(51)]}, "too_many_assets"),
    ],
)
def test_invalid_query_is_422_with_a_reason_code(
    world: World, body: dict[str, Any], reason: str
) -> None:
    response = world.post(VIEWER, ACCESS, body)
    assert response.status_code == 422
    assert _reason(response) == reason
    assert response.json()["code"] == "invalid_schema"


def test_unknown_sensitivity_category_is_a_schema_422(world: World) -> None:
    response = world.post(VIEWER, ACCESS, {"filters": {"sensitivity_categories": ["gossip"]}})
    assert response.status_code == 422
    assert response.json()["code"] == "invalid_schema"


def test_exactly_fifty_asset_ids_are_accepted(world: World) -> None:
    ids = [asset_id(f"n{i}") for i in range(50)]
    assert world.post(VIEWER, ACCESS, {"asset_ids": ids}).status_code == 200


def test_no_data_read_permission_is_403(world: World) -> None:
    assert world.post(AUDITOR, ACCESS, {}).status_code == 403
    assert world.get(AUDITOR, REGION_GROUPS).status_code == 403


def test_alias_prefix_serves_the_same_route(world: World) -> None:
    response = world.post(VIEWER, "/catalog/access/query", {"asset_ids": [asset_id("claims")]})
    assert response.status_code == 200
    assert _accessors(response.json()) == {agent_id("fin-a1")}


def test_region_groups_lists_names_and_members_only(world: World) -> None:
    response = world.get(VIEWER, REGION_GROUPS)
    assert response.status_code == 200
    data = response.json()
    assert set(data) == {"groups"}
    eu = next(g for g in data["groups"] if g["name"] == "eu")
    assert set(eu) == {"name", "regions"}
    assert {"westeurope", "northeurope"} <= set(eu["regions"])
