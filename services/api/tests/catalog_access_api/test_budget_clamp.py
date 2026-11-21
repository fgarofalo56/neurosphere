"""Server ceilings are fixed; a request budget can only lower them (PRP-73 item 3)."""

from __future__ import annotations

from typing import Any

import pytest
from catalog_access_support import ACCESS, build_world  # pyright: ignore[reportMissingImports]
from neurosphere_api.catalog.access.deps import to_access_budget, validate_regions
from neurosphere_api.catalog.access.models import AccessBudgetIn
from neurosphere_api.catalog.router import MAX_LIMIT, MAX_TIMEOUT_MS
from neurosphere_core.catalog.graph.access import MAX_ACCESSORS, MAX_ASSETS, AccessQueryError
from ui_adapters_api.adapter_support import VIEWER, World  # pyright: ignore[reportMissingImports]


@pytest.fixture
def world() -> World:
    return build_world()


def _bound(world: World, budget: dict[str, Any] | None) -> dict[str, Any]:
    body: dict[str, Any] = {} if budget is None else {"budget": budget}
    response = world.post(VIEWER, ACCESS, body)
    assert response.status_code == 200, response.text
    return response.json()["bound"]


def test_no_budget_runs_under_the_engine_ceilings(world: World) -> None:
    bound = _bound(world, None)
    assert bound["max_assets"] == MAX_ASSETS
    assert bound["max_accessors"] == MAX_ACCESSORS
    assert bound["timeout_ms"] == MAX_TIMEOUT_MS


def test_request_values_above_the_ceilings_do_not_raise_them(world: World) -> None:
    bound = _bound(world, {"timeout_ms": 30000, "max_assets": 5000, "max_accessors": 1000})
    assert bound["timeout_ms"] == MAX_TIMEOUT_MS
    assert bound["max_assets"] == MAX_ASSETS
    assert bound["max_accessors"] <= MAX_ACCESSORS


def test_request_values_below_the_ceilings_lower_them(world: World) -> None:
    bound = _bound(world, {"timeout_ms": 500, "max_assets": 7, "max_accessors": 3})
    assert (bound["timeout_ms"], bound["max_assets"], bound["max_accessors"]) == (500, 7, 3)


def test_a_partial_budget_leaves_the_other_ceilings_alone(world: World) -> None:
    bound = _bound(world, {"max_assets": 7})
    assert bound["max_assets"] == 7
    assert bound["timeout_ms"] == MAX_TIMEOUT_MS
    assert bound["max_accessors"] == MAX_ACCESSORS


@pytest.mark.parametrize(
    "budget",
    [{"timeout_ms": 30001}, {"max_assets": 5001}, {"max_accessors": 1001}, {"timeout_ms": 0}],
)
def test_values_beyond_the_contract_ceilings_are_refused(
    world: World, budget: dict[str, Any]
) -> None:
    assert world.post(VIEWER, ACCESS, {"budget": {**budget}}).status_code == 422


def test_to_access_budget_reuses_the_shared_clamp() -> None:
    assert to_access_budget(None) is None
    clamped = to_access_budget(AccessBudgetIn(timeout_ms=30000, max_accessors=1000))
    assert clamped is not None
    assert clamped.timeout_ms == MAX_TIMEOUT_MS
    assert clamped.max_accessors == MAX_LIMIT
    assert clamped.max_assets is None
    lowered = to_access_budget(AccessBudgetIn(timeout_ms=100, max_accessors=5, max_assets=9))
    assert lowered is not None
    assert (lowered.timeout_ms, lowered.max_accessors, lowered.max_assets) == (100, 5, 9)


def test_region_validation_is_one_function_that_rejects_unknown_regions() -> None:
    validate_regions(None, "commercial")
    validate_regions(["westeurope", "NorthEurope"], "commercial")
    validate_regions(["usgovvirginia"], "government")
    for regions, cloud in (
        (["bad region!"], "commercial"),
        (["atlantis"], "commercial"),
        (["usgovvirginia"], "commercial"),
        (["eastus"], "government"),
    ):
        with pytest.raises(AccessQueryError) as raised:
            validate_regions(regions, cloud)
        assert raised.value.reason == "unknown_region"
