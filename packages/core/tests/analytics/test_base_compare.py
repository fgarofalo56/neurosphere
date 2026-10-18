from __future__ import annotations

from decimal import Decimal

from neurosphere_contracts.telemetry.v1.telemetry_event import TelemetryEvent
from neurosphere_core.analytics.base import (
    AggregateResult,
    AggregateRow,
    Aggregation,
    Dimension,
    ExecutionStats,
    Metric,
    compare_results,
    record_from_observation,
    record_from_telemetry_event,
)
from neurosphere_core.analytics.base.compare import QUANTILE_ABS_TOL, QUANTILE_REL_TOL
from neurosphere_core.ledger import Observation


def _result(
    aggregation: Aggregation,
    value: str | None,
    *,
    metric: Metric = Metric.DURATION_MS,
    unknown: int = 0,
) -> AggregateResult:
    return AggregateResult(
        backend="x",
        cloud="commercial",
        metric=metric,
        aggregation=aggregation,
        quantile=0.5 if aggregation is Aggregation.APPROX_QUANTILE else None,
        group_by=(Dimension.MODEL,),
        rows=(
            AggregateRow(
                keys=("m",),
                value=None if value is None else Decimal(value),
                row_count=10,
                unknown_count=unknown,
            ),
        ),
        stats=ExecutionStats(rows_scanned=1, cost_units=Decimal(0)),
    )


def test_exact_aggregates_must_match_exactly() -> None:
    assert compare_results(_result(Aggregation.SUM, "100"), _result(Aggregation.SUM, "100.0")) == []
    (m,) = compare_results(_result(Aggregation.SUM, "100"), _result(Aggregation.SUM, "100.001"))
    assert m.field == "value"
    cost_a = _result(Aggregation.SUM, "0.000000000001", metric=Metric.COST_AMOUNT)
    cost_b = _result(Aggregation.SUM, "0.000000000002", metric=Metric.COST_AMOUNT)
    assert compare_results(cost_a, cost_b)  # money is compared exactly, not approximately


def test_unknown_equals_only_unknown() -> None:
    assert compare_results(_result(Aggregation.SUM, None), _result(Aggregation.SUM, None)) == []
    assert compare_results(_result(Aggregation.SUM, None), _result(Aggregation.SUM, "0"))


def test_quantile_tolerance_is_relative_with_integer_floor() -> None:
    assert QUANTILE_REL_TOL == Decimal("0.02") and QUANTILE_ABS_TOL == Decimal("1")
    q = Aggregation.APPROX_QUANTILE
    assert compare_results(_result(q, "1000"), _result(q, "1019")) == []
    assert compare_results(_result(q, "1000"), _result(q, "1030"))
    assert compare_results(_result(q, "10"), _result(q, "11")) == []  # integer metric floor
    cost = Metric.COST_AMOUNT
    assert compare_results(_result(q, "10", metric=cost), _result(q, "11", metric=cost))


def test_counts_and_structure_are_compared() -> None:
    a, b = _result(Aggregation.SUM, "1"), _result(Aggregation.SUM, "1", unknown=1)
    assert [m.field for m in compare_results(a, b)] == ["unknown_count"]
    assert compare_results(a, _result(Aggregation.MAX, "1"))[0].where == "structure"


def test_projection_from_ledger_observation_keeps_unknown_null() -> None:
    obs = Observation.model_validate(
        {
            "observation_kind": "gateway",
            "doc_id": "a" * 64,
            "kind": "estimated",
            "amount": None,
            "price_unresolved": True,
            "observed_at": "2026-10-01T10:00:00Z",
            "cloud": "commercial",
            "source_id": "gw",
            "model": "gpt-4o",
            "token_breakdown": {"input": 12},
        }
    )
    record = record_from_observation(obs, customer_id="contoso")
    assert record.cost_amount is None and record.currency is None
    assert record.input_tokens == 12 and record.output_tokens is None
    assert record.customer_id == "contoso" and record.model == "gpt-4o"


def test_projection_from_telemetry_event() -> None:
    event = TelemetryEvent.model_validate(
        {
            "schema_version": "1.0.0",
            "event_id": "e1",
            "event_time": "2026-10-01T10:00:00Z",
            "cloud": "government",
            "customer_id": "contoso",
            "source_id": "otel",
            "duration_ms": 0,
        }
    )
    record = record_from_telemetry_event(event)
    assert record.duration_ms == 0  # a measured zero stays 0
    assert record.domain_id is None and record.input_tokens is None
