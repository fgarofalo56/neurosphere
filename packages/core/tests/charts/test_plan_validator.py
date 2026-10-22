"""Chart plan validator: hostile plans are rejected, valid subset plans are accepted."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from neurosphere_contracts.chart.v1.chart_plan import ChartPlan
from neurosphere_core.charts import (
    CHART_MAX_BYTES,
    ChartPlanInvalidError,
    validate_chart_plan,
)
from neurosphere_core.errors import InvalidSchemaError

_ROOT = Path(__file__).resolve().parents[4]
_EXAMPLES = _ROOT / "packages/contracts/schemas/chart/v1/examples"
_CORPUS = _ROOT / "tests/security/injection/corpus.json"


def _plan(spec_overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    spec: dict[str, Any] = {
        "data": {"values": [{"agent": "a", "amount": 1.5}, {"agent": "b", "amount": 2.5}]},
        "mark": "bar",
        "encoding": {
            "x": {"field": "agent", "type": "nominal"},
            "y": {"field": "amount", "type": "quantitative"},
        },
    }
    spec.update(spec_overrides or {})
    return {
        "schema_version": "1.0.0",
        "citations": [{"evidence_id": "ev:cost:2026-09", "as_of": "2026-10-10T11:58:00Z"}],
        "spec": spec,
    }


def _load(rel: str) -> dict[str, Any]:
    return json.loads((_EXAMPLES / rel).read_text(encoding="utf-8"))


@pytest.mark.parametrize("mark", ["bar", "line", "area", "point"])
def test_valid_marks_are_accepted(mark: str) -> None:
    plan = validate_chart_plan(_plan({"mark": mark}))
    assert isinstance(plan, ChartPlan)


@pytest.mark.parametrize("name", sorted(p.name for p in (_EXAMPLES / "valid").glob("*.json")))
def test_contract_valid_examples_are_accepted(name: str) -> None:
    validate_chart_plan(_load(f"valid/{name}"))


@pytest.mark.parametrize("name", sorted(p.name for p in (_EXAMPLES / "invalid").glob("*.json")))
def test_contract_invalid_examples_are_rejected(name: str) -> None:
    with pytest.raises(ChartPlanInvalidError):
        validate_chart_plan(_load(f"invalid/{name}"))


def _with(**extra: Any) -> dict[str, Any]:
    return _plan(extra)


HOSTILE: list[tuple[str, dict[str, Any]]] = [
    ("expr-in-mark", _with(mark={"type": "bar", "color": {"expr": "1+1"}})),
    (
        "expr-in-encoding",
        _with(encoding={"x": {"field": "agent", "type": "nominal"}, "y": {"value": {"expr": "x"}}}),
    ),
    ("params", _with(params=[{"name": "p", "value": 1}])),
    ("signals", _with(signals=[{"name": "tick", "on": [{"events": "timer{1000}"}]}])),
    ("signal-key", _with(signal="x")),
    ("selection", _with(selection={"s": {"type": "interval"}})),
    (
        "event-stream",
        _with(encoding={"x": {"field": "agent", "type": "nominal"}, "on": [{"events": "click"}]}),
    ),
    ("external-url-data", _with(data={"url": "https://collector.attacker.example/d.json"})),
    ("file-url-data", _with(data={"url": "file:///etc/hosts"})),
    ("named-data", _with(data={"name": "source"})),
    (
        "href-channel",
        _with(encoding={"x": {"field": "agent", "type": "nominal"}, "href": {"field": "agent"}}),
    ),
    ("calculate", _with(transform=[{"calculate": "datum.amount * 2", "as": "dbl"}])),
    ("lookup", _with(transform=[{"lookup": "agent", "from": {"data": {"url": "x"}}}])),
    ("arc-mark", _with(mark="arc")),
    ("image-mark", _with(mark="image")),
    ("geoshape-mark", _with(mark={"type": "geoshape"})),
    ("datasets", _with(datasets={"d": []})),
    ("config", _with(config={"customFormatTypes": True})),
    ("usermeta", _with(usermeta={"embedOptions": {"loader": {"baseURL": "x"}}})),
    ("schema-ref", _with(**{"$schema": "https://vega.github.io/schema/vega-lite/v6.json"})),
    ("remote-ref", _with(**{"$ref": "https://x.example/s.json"})),
    ("unknown-field-encoding", _with(encoding={"x": {"field": "nope", "type": "nominal"}})),
    (
        "unknown-field-transform",
        _with(transform=[{"filter": {"field": "ghost", "equal": 1}}]),
    ),
    ("text-mark-without-text", _with(mark="text")),
    ("line-without-y", _with(mark="line", encoding={"x": {"field": "agent", "type": "nominal"}})),
    ("quote-in-field", _with(encoding={"x": {"field": "a'b", "type": "nominal"}})),
]


@pytest.mark.parametrize(("label", "plan"), HOSTILE, ids=[h[0] for h in HOSTILE])
def test_hostile_plans_are_rejected(label: str, plan: dict[str, Any]) -> None:
    with pytest.raises(ChartPlanInvalidError) as info:
        validate_chart_plan(plan)
    assert info.value.violations, label


def test_top_level_banned_keys_are_rejected() -> None:
    for key in ("datasets", "config", "usermeta", "$schema"):
        plan = _plan()
        plan[key] = {}
        with pytest.raises(ChartPlanInvalidError):
            validate_chart_plan(plan)


def test_banned_key_is_reported_with_a_pointer_and_no_value() -> None:
    with pytest.raises(ChartPlanInvalidError) as info:
        validate_chart_plan(_with(params=[{"name": "secret-value-xyz"}]))
    issues = info.value.violations
    assert any(i.pointer == "/spec/params" for i in issues)
    assert all("secret-value-xyz" not in i.detail for i in issues)


def test_error_is_the_invalid_schema_taxonomy_member() -> None:
    with pytest.raises(InvalidSchemaError) as info:
        validate_chart_plan({"not": "a plan"})
    assert info.value.status == 422


def test_data_fields_named_like_banned_keys_are_allowed() -> None:
    plan = _plan(
        {
            "data": {"values": [{"url": "a", "config": 1.0, "params": 2.0}]},
            "encoding": {
                "x": {"field": "url", "type": "nominal"},
                "y": {"field": "config", "type": "quantitative"},
            },
        }
    )
    validate_chart_plan(plan)


def test_oversized_serialized_plan_is_rejected() -> None:
    plan = _plan()
    plan["spec"]["title"] = "x" * (CHART_MAX_BYTES + 1)
    with pytest.raises(ChartPlanInvalidError) as info:
        validate_chart_plan(plan)
    assert "bytes" in info.value.violations[0].detail


def test_too_many_rows_are_rejected() -> None:
    plan = _plan()
    plan["spec"]["data"]["values"] = [{"agent": "a", "amount": 1.0}] * 5001
    with pytest.raises(ChartPlanInvalidError):
        validate_chart_plan(plan)


def test_deep_nesting_is_rejected_without_recursion_error() -> None:
    node: dict[str, Any] = {}
    cursor = node
    for _ in range(2000):
        cursor["a"] = {}
        cursor = cursor["a"]
    plan = _plan({"title": node})
    with pytest.raises(ChartPlanInvalidError):
        validate_chart_plan(plan)


@pytest.mark.parametrize("raw", [None, [], "plan", 3, object()])
def test_non_objects_are_rejected(raw: object) -> None:
    with pytest.raises(ChartPlanInvalidError):
        validate_chart_plan(raw)


def test_validation_does_not_mutate_input() -> None:
    plan = _plan()
    before = copy.deepcopy(plan)
    validate_chart_plan(plan)
    assert plan == before


def _corpus_attempts() -> list[tuple[str, dict[str, Any]]]:
    cases = json.loads(_CORPUS.read_text(encoding="utf-8"))["cases"]
    return [
        (case["id"], case["attempt"])
        for case in cases
        if case.get("attempt", {}).get("kind") == "render_chart"
    ]


def test_corpus_has_render_chart_attempts() -> None:
    assert len(_corpus_attempts()) >= 7


@pytest.mark.parametrize(("case_id", "attempt"), _corpus_attempts())
def test_injection_corpus_render_chart_attempts_are_rejected(
    case_id: str, attempt: dict[str, Any]
) -> None:
    plan = {
        "schema_version": "1.0.0",
        "citations": [{"evidence_id": "ev:x", "as_of": "2026-10-10T11:58:00Z"}],
        "spec": attempt["spec"],
    }
    with pytest.raises(ChartPlanInvalidError):
        validate_chart_plan(plan)
    with pytest.raises(ChartPlanInvalidError):
        validate_chart_plan(attempt)
