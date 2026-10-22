"""Validator for the Government evidence register (docs/evidence/G02/register.yaml).

Availability, GA/preview and authorization are separate fields. The authorization enum has no
"authorized" member, and no row text may claim a dependency or NeuroSphere is authorized.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

import pytest
import yaml
from neurosphere_core.capabilities.loader import load_matrix
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

REGISTER_PATH = Path(__file__).resolve().parents[3] / "docs" / "evidence" / "G02" / "register.yaml"

ALLOWED_HOSTS = frozenset({"learn.microsoft.com", "www.microsoft.com", "azure.microsoft.com"})
ENVIRONMENTS = ("azure_government", "gcc", "gcc_high", "dod")
AVAILABILITY = ("available", "unavailable", "preview", "not_verified")
GA_STATUS = ("ga", "preview", "not_verified")
AUTHORIZATION_VALUES = (
    "not_verified",
    "audit_scope_listed",
    "assessment_in_progress",
    "customer_determines",
)

# "authorized" is allowed only when directly preceded by "not " or "not FedRAMP ".
AUTHORIZED_CLAIM = re.compile(r"(?<!not )(?<!not FedRAMP )\bauthorized\b", re.IGNORECASE)


class RegisterRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    dependency: str
    feature: str
    cloud: Literal["government"]
    environment: Literal["azure_government", "gcc", "gcc_high", "dod"]
    region: str
    sku: str | None
    availability: Literal["available", "unavailable", "preview", "not_verified"]
    ga_status: Literal["ga", "preview", "not_verified"]
    authorization: Literal[
        "not_verified", "audit_scope_listed", "assessment_in_progress", "customer_determines"
    ]
    authorization_note: str
    is_preview: bool
    is_saas: bool
    capability_rows: list[str]
    source_url: str
    retrieved_on: str
    notes: str

    @field_validator("source_url")
    @classmethod
    def _first_party_https(cls, value: str) -> str:
        parts = urlsplit(value)
        if parts.scheme != "https" or parts.hostname not in ALLOWED_HOSTS:
            raise ValueError(f"source_url must be https on a Microsoft first-party host: {value!r}")
        return value

    @field_validator("retrieved_on")
    @classmethod
    def _iso_date(cls, value: str) -> str:
        date.fromisoformat(value)
        return value

    @field_validator("id", "dependency", "feature", "authorization_note", "notes")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must be non-empty")
        return value


def _load() -> dict[str, Any]:
    loaded = yaml.safe_load(REGISTER_PATH.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


@pytest.fixture(scope="module")
def document() -> dict[str, Any]:
    return _load()


@pytest.fixture(scope="module")
def rows(document: dict[str, Any]) -> list[RegisterRow]:
    return [RegisterRow.model_validate(raw) for raw in document["rows"]]


def _good_row() -> dict[str, Any]:
    return {
        "id": "x",
        "dependency": "d",
        "feature": "f",
        "cloud": "government",
        "environment": "azure_government",
        "region": "*",
        "sku": None,
        "availability": "not_verified",
        "ga_status": "not_verified",
        "authorization": "not_verified",
        "authorization_note": "n",
        "is_preview": False,
        "is_saas": False,
        "capability_rows": [],
        "source_url": "https://learn.microsoft.com/azure/x",
        "retrieved_on": "2026-10-22",
        "notes": "n",
    }


def test_header_states_availability_is_not_authorization(document: dict[str, Any]) -> None:
    assert document["schema_version"]
    assert document["generated_note"]
    assert "Availability is not authorization" in document["statement"]
    assert "not FedRAMP authorized; the authorizing official decides" in document["statement"]


def test_rows_validate_and_ids_unique(rows: list[RegisterRow]) -> None:
    assert len(rows) >= 40
    ids = [row.id for row in rows]
    assert len(ids) == len(set(ids))


def test_good_row_baseline_validates() -> None:
    RegisterRow.model_validate(_good_row())


@pytest.mark.parametrize("field", ["source_url", "retrieved_on"])
def test_row_missing_source_or_date_is_rejected(field: str) -> None:
    bad = _good_row()
    del bad[field]
    with pytest.raises(ValidationError):
        RegisterRow.model_validate(bad)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source_url", ""),
        ("source_url", "http://learn.microsoft.com/azure/x"),
        ("source_url", "https://learn.microsoft.com.evil.example/azure/x"),
        ("source_url", "https://example.com/learn.microsoft.com"),
        ("retrieved_on", ""),
        ("retrieved_on", "22/10/2026"),
        ("retrieved_on", "2026-13-45"),
        ("authorization", "authorized"),
        ("environment", "government"),
        ("availability", "ga"),
        ("ga_status", "available"),
    ],
)
def test_bad_values_are_rejected(field: str, value: str) -> None:
    bad = _good_row()
    bad[field] = value
    with pytest.raises(ValidationError):
        RegisterRow.model_validate(bad)


def test_unknown_field_is_rejected() -> None:
    bad = _good_row()
    bad["extra"] = 1
    with pytest.raises(ValidationError):
        RegisterRow.model_validate(bad)


def test_every_source_is_first_party_and_dated(rows: list[RegisterRow]) -> None:
    for row in rows:
        assert urlsplit(row.source_url).hostname in ALLOWED_HOSTS, row.id
        assert date.fromisoformat(row.retrieved_on) <= date.today(), row.id


def test_enums_have_no_authorized_member() -> None:
    assert "authorized" not in AUTHORIZATION_VALUES
    assert not any("authorized" in value for value in AUTHORIZATION_VALUES)
    assert set(AUTHORIZATION_VALUES) == {
        "not_verified",
        "audit_scope_listed",
        "assessment_in_progress",
        "customer_determines",
    }
    declared = RegisterRow.model_fields["authorization"].annotation
    assert declared == Literal[AUTHORIZATION_VALUES]  # type: ignore[valid-type]


def test_availability_ga_and_authorization_are_separate_keys(document: dict[str, Any]) -> None:
    for raw in document["rows"]:
        for key in ("availability", "ga_status", "authorization", "is_preview", "is_saas"):
            assert key in raw, (raw["id"], key)
    assert len({"availability", "ga_status", "authorization"}) == 3


def test_authorized_claim_regex_semantics() -> None:
    assert AUTHORIZED_CLAIM.search("This service is authorized for the agency workload")
    assert AUTHORIZED_CLAIM.search("NeuroSphere is FedRAMP authorized")
    assert AUTHORIZED_CLAIM.search("Authorized to operate")
    assert not AUTHORIZED_CLAIM.search("NeuroSphere is not FedRAMP authorized")
    assert not AUTHORIZED_CLAIM.search("this is not authorized")
    assert not AUTHORIZED_CLAIM.search("not an agency authorization")
    assert not AUTHORIZED_CLAIM.search("Audit-scope listing only")


def test_no_row_claims_authorized(rows: list[RegisterRow]) -> None:
    for row in rows:
        for text in (row.authorization, row.authorization_note, row.notes):
            assert not AUTHORIZED_CLAIM.search(text), (row.id, text)


def test_audit_scope_rows_say_listing_only(rows: list[RegisterRow]) -> None:
    listed = [row for row in rows if row.authorization == "audit_scope_listed"]
    assert listed
    for row in listed:
        assert "not an agency authorization" in row.authorization_note, row.id


def test_preview_flag_consistent(rows: list[RegisterRow]) -> None:
    for row in rows:
        if row.ga_status == "preview" or row.availability == "preview":
            assert row.is_preview, row.id
        if row.is_preview:
            assert row.ga_status == "preview" or row.availability == "preview", row.id
    assert any(row.is_preview for row in rows)


def test_saas_flagged(rows: list[RegisterRow]) -> None:
    saas = {row.dependency for row in rows if row.is_saas}
    assert "Microsoft Fabric" in saas
    assert "Microsoft Foundry Agent Service" in saas


def test_fabric_rows(rows: list[RegisterRow]) -> None:
    fabric = [row for row in rows if row.dependency == "Microsoft Fabric"]
    high = [row for row in fabric if row.environment == "gcc_high"]
    assert {row.region for row in high} == {"usgovvirginia", "usgovtexas"}
    for row in high:
        assert row.authorization == "assessment_in_progress", row.id
    base = [row for row in high if row.feature.startswith("base")]
    assert {row.region for row in base} == {"usgovvirginia", "usgovtexas"}
    for row in base:
        assert row.availability == "available"
        assert row.ga_status == "ga"
    for env in ("gcc", "dod"):
        env_rows = [row for row in fabric if row.environment == env]
        assert env_rows, env
        for row in env_rows:
            assert row.availability == "not_verified", row.id
            assert row.authorization == "not_verified", row.id


def test_environments_are_distinct_values(rows: list[RegisterRow]) -> None:
    assert len(set(ENVIRONMENTS)) == len(ENVIRONMENTS)
    assert {row.environment for row in rows} <= set(ENVIRONMENTS)
    for env in ("gcc", "gcc_high", "dod"):
        for row in rows:
            if row.environment == env:
                assert row.dependency == "Microsoft Fabric", row.id
    assert not any(row.environment == "gcc" and "GCC High" in row.feature for row in rows)


def test_required_dependencies_covered(rows: list[RegisterRow]) -> None:
    text = " ".join(f"{row.dependency} {row.feature}" for row in rows)
    for needle in (
        "Cosmos DB",
        "Event Hubs",
        "geo-replication",
        "geo-DR",
        "Storage",
        "Key Vault",
        "AI Search",
        "semantic ranker",
        "agentic retrieval",
        "API Management",
        "B2C",
        "Kubernetes",
        "App Service",
        "Managed Certificate",
        "Container Registry",
        "Azure Monitor",
        "Entra",
        "Resource Graph",
        "Foundry",
        "Fabric",
        "Synapse",
        "Databricks",
    ):
        assert needle in text, needle


def test_foundry_conflict_is_recorded_not_resolved(rows: list[RegisterRow]) -> None:
    agent = {row.id: row for row in rows if row.id.startswith("foundry-agent-")}
    for key in ("prompt-agents", "ai-search-tool", "mcp-servers", "function-calling"):
        row = agent[f"foundry-agent-{key}"]
        assert row.availability == "not_verified", row.id
        assert "CONFLICT" in row.notes, row.id
    assert agent["foundry-agent-workflows"].is_preview


def test_search_texas_has_no_semantic_or_agentic(rows: list[RegisterRow]) -> None:
    texas = [
        row for row in rows if row.dependency == "Azure AI Search" and row.region == "usgovtexas"
    ]
    assert {row.availability for row in texas} == {"unavailable"}
    assert len(texas) == 2


def test_capability_rows_exist_in_matrix(rows: list[RegisterRow]) -> None:
    matrix = load_matrix()
    linked = {cap for row in rows for cap in row.capability_rows}
    assert linked
    missing = sorted(cap for cap in linked if matrix.by_id(cap) is None)
    assert not missing, missing
