"""Suite-owned golden fixtures for PRP-01 acceptance item 1 (tests/contracts/fixtures/).

* A telemetry event missing token breakdown, duration or model/version deserializes to
  null or ``unknown``, never 0 (Clarification 5) - in JSON Schema defaults and in the
  generated Pydantic model.
* ``schema_version`` is required on the envelope and the cost record.
* An estimated CostRecord without ``price_version`` is rejected (by JSON Schema; the
  Pydantic model does not carry the conditional, ADR-0004).
"""

from __future__ import annotations

from typing import Any

import pytest
from contract_support import (
    FIXTURES_DIR,
    iter_subschemas,
    load_json,
    load_schema,
    model_for,
    schema_errors,
    schema_files,
)

TELEMETRY = "telemetry/v1/telemetry-event.schema.json"
COST = "cost/v1/cost-record.schema.json"


def _zeros(node: Any, path: str = "") -> list[str]:
    if isinstance(node, bool):
        return []
    if isinstance(node, int | float) and node == 0:
        return [path or "/"]
    if isinstance(node, str) and node.strip() in ("0", "0.0"):
        return [path or "/"]
    if isinstance(node, dict):
        return [z for k, v in node.items() for z in _zeros(v, f"{path}/{k}")]
    if isinstance(node, list):
        return [z for i, v in enumerate(node) for z in _zeros(v, f"{path}/{i}")]
    return []


@pytest.mark.parametrize(
    ("fixture", "schema"),
    [
        ("telemetry/telemetry-event.required-only.json", TELEMETRY),
        ("telemetry/telemetry-event.empty-breakdown.json", TELEMETRY),
        ("cost/cost-record.invoiced-required-only.json", COST),
    ],
)
def test_missing_values_are_null_or_unknown_never_zero(fixture: str, schema: str) -> None:
    document = load_json(FIXTURES_DIR / fixture)
    assert schema_errors(schema, document) == []
    full = model_for(schema).model_validate(document).model_dump(mode="json")
    assert _zeros(full) == [], "an unset field defaulted to 0"
    supplied = set(document)
    for name, value in full.items():
        if name in supplied:
            continue
        assert value is None or value == "unknown", f"{name} defaulted to {value!r}"


def test_telemetry_unknowns_by_name() -> None:
    event = model_for(TELEMETRY).model_validate(
        load_json(FIXTURES_DIR / "telemetry/telemetry-event.required-only.json")
    )
    assert event.duration_ms is None
    assert event.token_breakdown is None
    assert event.model is None and event.model_version is None and event.provider is None
    dumped = event.model_dump(mode="json")
    assert (dumped["outcome"], dumped["span_kind"], dumped["environment"]) == ("unknown",) * 3
    breakdown = (
        model_for(TELEMETRY)
        .model_validate(load_json(FIXTURES_DIR / "telemetry/telemetry-event.empty-breakdown.json"))
        .token_breakdown
    )
    assert breakdown is not None
    assert (breakdown.input, breakdown.output, breakdown.cached, breakdown.reasoning) == (None,) * 4


@pytest.mark.parametrize("schema", [TELEMETRY, COST])
def test_schema_version_is_required(schema: str) -> None:
    assert "schema_version" in load_schema(schema)["required"]
    document = load_json(FIXTURES_DIR / "telemetry/telemetry-event.required-only.json")
    if schema == COST:
        document = load_json(FIXTURES_DIR / "cost/cost-record.invoiced-required-only.json")
    del document["schema_version"]
    assert any(e.validator == "required" for e in schema_errors(schema, document))


def test_estimated_cost_without_price_version_is_rejected() -> None:
    document = load_json(FIXTURES_DIR / "cost/cost-record.estimated-without-price-version.json")
    errors = schema_errors(COST, document)
    assert any(e.validator == "required" and "price_version" in e.message for e in errors)
    assert schema_errors(COST, {**document, "price_version": "azure-retail-2026-10-01"}) == []
    assert schema_errors(COST, {**document, "price_version": None})


@pytest.mark.parametrize("rel", schema_files())
def test_no_schema_defaults_a_number_to_zero(rel: str) -> None:
    """Numeric 0 is only ever a measured zero: no default may manufacture one."""
    zero_defaults = [
        sub.pointer
        for sub in iter_subschemas(load_schema(rel))
        if "default" in sub.node and _zeros(sub.node["default"])
    ]
    assert not zero_defaults, zero_defaults
