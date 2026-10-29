"""Lint over the real shipped data (PRP-02 item 1 acceptance, enforced on every run)."""

from __future__ import annotations

import re
from datetime import date

import pytest
from neurosphere_core.capabilities import CapabilityMatrix, load_matrix

NINE = {
    "foundry",
    "fabric",
    "synapse",
    "databricks",
    "cosmos_db",
    "apim",
    "ai_search",
    "event_hubs",
    "resource_graph",
    "aks",
    "app_service",
}
CLAIMS = re.compile(
    r"neurosphere\s+(is|has|holds|received|obtained)|ato\s+(granted|issued)|"
    r"authorized for (the )?agenc|agency authori[sz]ation granted|compliance parity",
    re.IGNORECASE,
)
FABRIC_GA_REGIONS = {"usgovvirginia", "usgovtexas"}


@pytest.fixture(scope="module")
def matrix() -> CapabilityMatrix:
    return load_matrix(today=date(2026, 10, 29))


def test_every_row_has_source_and_date(matrix: CapabilityMatrix) -> None:
    for row in matrix:
        assert row.source_url.startswith("https://"), row.id
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", row.observed_on), row.id


def test_ids_unique(matrix: CapabilityMatrix) -> None:
    ids = [r.id for r in matrix]
    assert len(ids) == len(set(ids))


def test_all_eleven_services_have_rows(matrix: CapabilityMatrix) -> None:
    assert NINE <= matrix.services()


def test_fabric_government_gcc_high_ga_only_virginia_and_texas(matrix: CapabilityMatrix) -> None:
    gov_base = [
        r
        for r in matrix
        if r.service == "fabric" and r.feature == "base" and r.cloud == "government"
    ]
    ga = [r for r in gov_base if r.availability == "available"]
    assert {r.region for r in ga} == FABRIC_GA_REGIONS
    assert all(r.ga_status == "ga" for r in ga)
    assert {r.region for r in gov_base} == FABRIC_GA_REGIONS
    for feature in ("base_gcc", "base_dod"):
        rows = [r for r in matrix if r.service == "fabric" and r.feature == feature]
        assert rows, feature
        assert all(r.availability == "unverified" and r.ga_status == "unverified" for r in rows)


def test_no_row_claims_neurosphere_or_agency_authorization(matrix: CapabilityMatrix) -> None:
    for row in matrix:
        assert not CLAIMS.search(row.authorization_scope), row.id
        text = row.authorization_scope.lower()
        if "neurosphere" in text:  # only ever as a disclaimer
            assert re.search(r"\b(not|no|never)\b", text), row.id


def test_foundry_conflicting_rows_are_unverified(matrix: CapabilityMatrix) -> None:
    conflicting = [
        r
        for r in matrix
        if r.service == "foundry"
        and r.feature in {"availability_government_roadmap", "availability_region_support_page"}
    ]
    assert len(conflicting) >= 2
    assert all(r.availability == "unverified" for r in conflicting)
    assert len({r.source_url for r in conflicting}) == len(conflicting)


def test_unavailable_rows_have_no_ga_status(matrix: CapabilityMatrix) -> None:
    for row in matrix:
        if row.availability == "unavailable":
            assert row.ga_status == "not_applicable", row.id
