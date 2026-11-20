"""Sensitivity, personal data, region and classification predicates: null is never false."""

from __future__ import annotations

import pytest
from catalog.graph_helpers import NS, make_scope  # pyright: ignore[reportMissingImports]
from neurosphere_core.catalog.graph.access import (
    AccessQuery,
    AccessQueryError,
    effective_sensitivity,
)
from pydantic import ValidationError

from .access_helpers import SCOPE_AB, asset, asset_id, build_world, make_engine


def _ids(result_assets: list) -> set[str]:  # type: ignore[type-arg]
    return {a.id for a in result_assets}


async def test_category_filter_matches_declared_and_reports_unassessed() -> None:
    world = await build_world()
    engine = make_engine(world.repo)
    plain = await engine.who_accesses(SCOPE_AB, AccessQuery(sensitivity_categories=["pii"]))
    assert _ids(plain.assets) == {asset_id("customers"), asset_id("ledger")}
    assert plain.unassessed_assets is None
    assert plain.unassessed_count is None
    asked = await engine.who_accesses(
        SCOPE_AB, AccessQuery(sensitivity_categories=["pii"], include_unassessed=True)
    )
    # mystery (null) and public (empty list: the contract cannot tell none from unassessed).
    assert asked.unassessed_assets is not None
    assert _ids(asked.unassessed_assets) == {asset_id("mystery"), asset_id("public")}
    assert asked.unassessed_count == 2
    assert asked.assets_scanned == 5
    # Unassessed assets are reported, never scanned for accessors.
    assert all(r.asset_id in {asset_id("customers"), asset_id("ledger")} for r in asked.rows)


async def test_phi_and_cui_are_separate_categories() -> None:
    world = await build_world()
    engine = make_engine(world.repo)
    phi = await engine.who_accesses(SCOPE_AB, AccessQuery(sensitivity_categories=["phi"]))
    assert _ids(phi.assets) == {asset_id("claims")}
    cui = await engine.who_accesses(SCOPE_AB, AccessQuery(sensitivity_categories=["cui"]))
    assert cui.assets == []


async def test_personal_data_false_never_matches_null() -> None:
    world = await build_world()
    engine = make_engine(world.repo)
    false = await engine.who_accesses(
        SCOPE_AB, AccessQuery(contains_personal_data=False, include_unassessed=True)
    )
    assert _ids(false.assets) == {asset_id("public")}
    assert false.unassessed_assets is not None
    assert _ids(false.unassessed_assets) == {asset_id("mystery")}
    true = await engine.who_accesses(SCOPE_AB, AccessQuery(contains_personal_data=True))
    assert _ids(true.assets) == {asset_id("customers"), asset_id("claims"), asset_id("ledger")}


async def test_region_group_eu_and_explicit_regions() -> None:
    world = await build_world()
    engine = make_engine(world.repo)
    eu = await engine.who_accesses(
        SCOPE_AB, AccessQuery(region_group="eu", include_unassessed=True)
    )
    assert _ids(eu.assets) == {asset_id("customers"), asset_id("ledger")}
    assert eu.unassessed_assets is not None
    assert _ids(eu.unassessed_assets) == {asset_id("mystery")}  # null region is not "outside EU"
    explicit = await engine.who_accesses(SCOPE_AB, AccessQuery(residency_regions=["EastUS"]))
    assert _ids(explicit.assets) == {asset_id("claims"), asset_id("public")}
    both = await engine.who_accesses(
        SCOPE_AB, AccessQuery(region_group="eu", residency_regions=["eastus"])
    )
    assert len(both.assets) == 4


async def test_filters_combine_with_and() -> None:
    world = await build_world()
    result = await make_engine(world.repo).who_accesses(
        SCOPE_AB,
        AccessQuery(
            sensitivity_categories=["pii"], region_group="eu", classifications=["restricted"]
        ),
    )
    assert _ids(result.assets) == {asset_id("customers"), asset_id("ledger")}
    narrow = await make_engine(world.repo).who_accesses(
        SCOPE_AB, AccessQuery(sensitivity_categories=["pii"], residency_regions=["westeurope"])
    )
    assert _ids(narrow.assets) == {asset_id("customers")}


async def test_classification_unknown_is_unassessed() -> None:
    world = await build_world()
    result = await make_engine(world.repo).who_accesses(
        SCOPE_AB, AccessQuery(classifications=["public"], include_unassessed=True)
    )
    assert _ids(result.assets) == {asset_id("public")}
    assert result.unassessed_assets is not None
    assert _ids(result.unassessed_assets) == {asset_id("mystery")}


async def test_unknown_group_and_region_are_typed_errors() -> None:
    world = await build_world()
    engine = make_engine(world.repo)
    with pytest.raises(AccessQueryError) as group:
        await engine.who_accesses(SCOPE_AB, AccessQuery(region_group="atlantis"))
    assert group.value.reason == "unknown_region_group"
    with pytest.raises(AccessQueryError) as region:
        await engine.who_accesses(SCOPE_AB, AccessQuery(residency_regions=["not a region!"]))
    assert region.value.reason == "unknown_region"


async def test_government_eu_group_is_empty() -> None:
    world = await build_world()
    gov = make_scope(NS, [f"commercial:{NS}:neurosphere:domain:a"], cloud="government")
    result = await make_engine(world.repo).who_accesses(gov, AccessQuery(region_group="eu"))
    assert result.assets == []
    assert result.rows == []


def test_category_vocabulary_is_the_contract_enum() -> None:
    AccessQuery(sensitivity_categories=["pii", "phi", "cui"])
    with pytest.raises(ValidationError):
        AccessQuery(sensitivity_categories=["bogus"])


def test_effective_sensitivity_is_one_function_and_keeps_null() -> None:
    mystery = asset("m", "a", contains_personal_data=None, sensitivity_categories=None)
    value = effective_sensitivity(mystery)
    assert value.categories is None
    assert value.contains_personal_data is None
    declared = effective_sensitivity(asset("d", "a", sensitivity_categories=["pii", "cui"]))
    assert declared.categories == frozenset({"pii", "cui"})
