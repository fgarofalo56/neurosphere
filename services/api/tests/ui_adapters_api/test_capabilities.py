"""PRP-31 item 2: ``GET /api/v1/capabilities`` serves the shipped PRP-02 matrix rows unchanged."""

from __future__ import annotations

from typing import Any

import pytest
from neurosphere_api.ui_adapters.capabilities import matrix_version
from neurosphere_contracts.deployment.v1.capability_matrix_entry import CapabilityMatrixEntry
from neurosphere_core.capabilities import CapabilityMatrix, load_matrix, matrix_from_rows

from .adapter_support import AUDITOR, STEWARD, VIEWER, World, make_world

PATH = "/api/v1/capabilities"


@pytest.fixture(scope="module")
def world() -> World:
    return make_world()


@pytest.fixture(scope="module")
def shipped() -> CapabilityMatrix:
    return load_matrix()


def _row(**patch: Any) -> CapabilityMatrixEntry:
    raw: dict[str, Any] = {
        "schema_version": "1.1.0",
        "service": "ai_search",
        "feature": "base",
        "cloud": "commercial",
        "region": "eastus",
        "sku": None,
        "availability": "available",
        "ga_status": "ga",
        "authorization_scope": "none_claimed",
        "source_url": "https://learn.microsoft.com/azure/search/",
        "observed_on": "2026-10-11",
        "notes": None,
    }
    raw.update(patch)
    region = "any" if raw["region"] == "*" else raw["region"]
    raw["id"] = f"{raw['service']}.{raw['feature']}.{raw['cloud']}.{region}.any"
    return CapabilityMatrixEntry.model_validate(raw)


def test_rows_are_the_shipped_matrix_unchanged(world: World, shipped: CapabilityMatrix) -> None:
    response = world.get(VIEWER, PATH)
    assert response.status_code == 200, response.text
    body = response.json()
    served = [CapabilityMatrixEntry.model_validate(r) for r in body["items"]]
    assert sorted(served, key=lambda r: r.id) == sorted(shipped.rows, key=lambda r: r.id)
    assert body["matrix_version"] == matrix_version(shipped)
    assert body["observed_at"] == max(r.observed_on for r in shipped.rows)


def test_unverified_rows_stay_unverified(world: World, shipped: CapabilityMatrix) -> None:
    unverified = {r.id for r in shipped.rows if r.availability == "unverified"}
    assert unverified, "the shipped matrix is expected to carry unverified rows"
    body = world.get(VIEWER, PATH).json()
    served = {r["id"]: r for r in body["items"]}
    for row_id in unverified:
        assert served[row_id]["availability"] == "unverified"


@pytest.mark.parametrize("cloud", ["commercial", "government"])
def test_cloud_filter_never_mixes_clouds(world: World, cloud: str) -> None:
    response = world.get(VIEWER, PATH, params={"cloud": cloud})
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert items
    assert {r["cloud"] for r in items} == {cloud}


def test_region_filter_keeps_exact_wildcard_and_global_rows() -> None:
    w = make_world()
    w.h.app.state.capability_matrix = matrix_from_rows(
        [
            _row(region="eastus"),
            _row(region="westus", feature="private_endpoint"),
            _row(region="global", feature="semantic_ranker"),
            _row(region="*", feature="vector"),
            _row(cloud="government", region="*", feature="vector"),
            _row(cloud="government", region="usgovvirginia", feature="base"),
        ]
    )
    body = w.get(VIEWER, PATH, params={"region": "eastus"}).json()
    assert {r["id"] for r in body["items"]} == {
        "ai_search.base.commercial.eastus.any",
        "ai_search.semantic_ranker.commercial.global.any",
        "ai_search.vector.commercial.any.any",
    }
    gov = w.get(VIEWER, PATH, params={"region": "usgovvirginia"}).json()
    assert {r["id"] for r in gov["items"]} == {
        "ai_search.semantic_ranker.commercial.global.any",
        "ai_search.vector.government.any.any",
        "ai_search.base.government.usgovvirginia.any",
    }
    gov_only = w.get(VIEWER, PATH, params={"region": "usgovvirginia", "cloud": "government"})
    assert {r["cloud"] for r in gov_only.json()["items"]} == {"government"}


def test_matrix_version_changes_with_the_rows() -> None:
    one = matrix_from_rows([_row()])
    two = matrix_from_rows([_row(availability="preview", ga_status="preview")])
    assert matrix_version(one) != matrix_version(two)
    assert matrix_version(one) == matrix_version(matrix_from_rows([_row()]))


@pytest.mark.parametrize("params", [{"cloud": "azure"}, {"region": "East US"}, {"region": "*"}])
def test_bad_filters_are_422(world: World, params: dict[str, str]) -> None:
    assert world.get(VIEWER, PATH, params=params).status_code == 422


def test_data_read_anywhere_is_required(world: World) -> None:
    assert world.get(None, PATH).status_code == 401
    assert world.get(STEWARD, PATH).status_code == 200
    # An auditor holds no data.read.
    response = world.get(AUDITOR, PATH)
    assert response.status_code == 403
    assert response.json()["reason"] == "permission_missing"
