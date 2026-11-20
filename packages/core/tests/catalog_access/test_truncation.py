"""Truncation reasons, fixed ceilings and request budgets that can only lower them."""

from __future__ import annotations

import pytest
from catalog.graph_helpers import FakeClock  # pyright: ignore[reportMissingImports]
from neurosphere_core.catalog.graph import access
from neurosphere_core.catalog.graph.access import AccessBudget, AccessQuery

from .access_helpers import SCOPE_AB, asset_id, build_world, make_engine

CUSTOMERS = asset_id("customers")


async def test_complete_answer_is_not_truncated() -> None:
    world = await build_world()
    result = await make_engine(world.repo).who_accesses(SCOPE_AB, AccessQuery())
    assert result.truncated is False
    assert result.truncated_reason is None
    assert result.assets_scanned == 5


async def test_max_accessors_budget_truncates() -> None:
    world = await build_world()
    result = await make_engine(world.repo).who_accesses(
        SCOPE_AB,
        AccessQuery(asset_ids=[CUSTOMERS], budget=AccessBudget(max_accessors=1)),
    )
    assert len(result.rows) == 1
    assert result.truncated is True
    assert result.truncated_reason == "max_accessors"


async def test_exactly_at_the_accessor_cap_is_not_truncated() -> None:
    world = await build_world()
    result = await make_engine(world.repo).who_accesses(
        SCOPE_AB,
        AccessQuery(asset_ids=[CUSTOMERS], budget=AccessBudget(max_accessors=3)),
    )
    assert len(result.rows) == 3
    assert result.truncated is False


async def test_max_assets_budget_truncates_and_counts_what_was_scanned() -> None:
    world = await build_world()
    result = await make_engine(world.repo).who_accesses(
        SCOPE_AB, AccessQuery(budget=AccessBudget(max_assets=2))
    )
    assert result.assets_scanned == 2
    assert result.truncated is True
    assert result.truncated_reason == "max_assets"


async def test_asset_page_cap_truncates(monkeypatch: pytest.MonkeyPatch) -> None:
    world = await build_world()
    monkeypatch.setattr(access, "MAX_ASSET_PAGES", 1)
    monkeypatch.setattr(access, "MAX_PAGE_SIZE", 2)
    result = await make_engine(world.repo).who_accesses(SCOPE_AB, AccessQuery())
    assert result.assets_scanned == 2
    assert result.truncated is True
    assert result.truncated_reason == "max_assets"


async def test_edge_page_cap_truncates(monkeypatch: pytest.MonkeyPatch) -> None:
    world = await build_world()
    monkeypatch.setattr(access, "MAX_EDGE_PAGES", 1)
    monkeypatch.setattr(access, "MAX_PAGE_SIZE", 1)
    result = await make_engine(world.repo).who_accesses(
        SCOPE_AB, AccessQuery(asset_ids=[CUSTOMERS])
    )
    assert result.truncated is True
    assert result.truncated_reason == "max_accessors"
    assert len(result.rows) < 3


async def test_timeout_truncates() -> None:
    world = await build_world()
    engine = make_engine(world.repo, clock=FakeClock(step=1.0))
    result = await engine.who_accesses(SCOPE_AB, AccessQuery(budget=AccessBudget(timeout_ms=1)))
    assert result.truncated is True
    assert result.truncated_reason == "timeout_ms"


async def test_request_budget_cannot_raise_the_ceilings() -> None:
    world = await build_world()
    result = await make_engine(world.repo).who_accesses(
        SCOPE_AB,
        AccessQuery(budget=AccessBudget(max_assets=10**9, max_accessors=10**9, timeout_ms=10**9)),
    )
    assert result.bound.max_assets == access.MAX_ASSETS
    assert result.bound.max_accessors == access.MAX_ACCESSORS
    assert result.bound.timeout_ms == access.MAX_TIMEOUT_MS


async def test_request_budget_lowers_the_bound() -> None:
    world = await build_world()
    result = await make_engine(world.repo).who_accesses(
        SCOPE_AB,
        AccessQuery(budget=AccessBudget(max_assets=3, max_accessors=4, timeout_ms=500)),
    )
    assert (result.bound.max_assets, result.bound.max_accessors, result.bound.timeout_ms) == (
        3,
        4,
        500,
    )
