"""Manifest validator against the PRP-01 valid/invalid examples, plus the builder."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from neurosphere_connector import build_manifest, manifest_issues, validate_manifest
from neurosphere_contracts.connectors.v1.connector_manifest import (
    ConnectorManifest,
    Freshness,
    Granularity,
)
from neurosphere_core.errors import InvalidSchemaError

EXAMPLES = (
    Path(__file__).resolve().parents[3]
    / "packages/contracts/schemas/connectors/v1/examples/connector-manifest"
)
VALID = sorted((EXAMPLES / "valid").glob("*.json"))
INVALID = sorted((EXAMPLES / "invalid").glob("*.json"))
GRAIN = Granularity(time_grain="event", subject_level="request")


def test_examples_found() -> None:
    assert VALID
    assert INVALID


@pytest.mark.parametrize("path", VALID, ids=lambda p: p.stem)
def test_valid_examples_accepted(path: Path) -> None:
    assert manifest_issues(path.read_text(encoding="utf-8")) == []
    assert isinstance(
        validate_manifest(json.loads(path.read_text(encoding="utf-8"))), ConnectorManifest
    )


@pytest.mark.parametrize("path", INVALID, ids=lambda p: p.stem)
def test_invalid_examples_rejected(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    assert manifest_issues(text)
    with pytest.raises(InvalidSchemaError) as info:
        validate_manifest(json.loads(text))
    assert info.value.errors


def test_non_json_rejected() -> None:
    assert manifest_issues("{not json")
    assert manifest_issues("[]")


def test_builder_defaults_unknown_not_zero() -> None:
    m = build_manifest(
        name="demo",
        version="1.0.0",
        capabilities=["telemetry_ingest"],
        supported_clouds=["commercial"],
        granularity=GRAIN,
    )
    assert m.freshness == Freshness(typical_delay_ms=None, max_delay_ms=None)
    assert m.rate_limits is None
    assert m.advisory is True
    assert m.auth_mode == "managed_identity"


def test_builder_write_actions_derive_capability_and_not_advisory() -> None:
    m = build_manifest(
        name="demo",
        version="1.0.0",
        capabilities=["catalog_discovery"],
        supported_clouds=["government"],
        granularity=GRAIN,
        write_actions=["agent_disable"],
    )
    assert m.advisory is False
    assert m.write_support.supported
    assert "action_execution" in m.capabilities


def test_builder_rejects_invalid_combination() -> None:
    with pytest.raises(InvalidSchemaError):
        build_manifest(
            name="demo",
            version="1.0.0",
            capabilities=["action_execution"],  # no write actions
            supported_clouds=["commercial"],
            granularity=GRAIN,
        )


def test_issue_messages_do_not_echo_submitted_values() -> None:
    value = "plain-" + "value-should-not-echo"
    doc = json.loads((VALID[0]).read_text(encoding="utf-8"))
    doc["name"] = value + " BAD"
    issues = manifest_issues(doc)
    assert issues
    assert all(value not in i.detail and value not in i.pointer for i in issues)
