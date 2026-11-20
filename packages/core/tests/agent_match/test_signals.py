from __future__ import annotations

from neurosphere_core.aggregates.models import SubjectPoint
from neurosphere_core.recommendations.matching import (
    ProximityPath,
    latency_pool_median,
    lexical_signal,
    proximity_signal,
    tag_signal,
    telemetry_signal,
)


def _point(
    *, error_rate: float | None = 0.1, p95_ms: int | None = 100, event_count: int = 100
) -> SubjectPoint:
    return SubjectPoint(
        id="x",
        customer_id="c",
        domain_id="d",
        grain="day",
        bucket_start="2026-01-01T00:00:00Z",
        series_key="agent:a",
        complete=True,
        subject_kind="agent",
        subject_key="agent:a",
        event_count=event_count,
        missing_duration_count=0,
        unknown_outcome_count=0,
        error_rate=error_rate,
        p95_ms=p95_ms,
    )


def test_tag_exact_is_one_and_overlap_is_fraction() -> None:
    cap, tag = tag_signal(["pdf-extraction"], ["summarize"], ["summarize"], ["pdf extraction"])
    assert cap.value == 1.0
    assert tag.value == 1.0
    _, partial = tag_signal(["pdf"], [], [], ["pdf extraction"])
    assert partial.value == 0.5
    assert partial.matched == ("pdf extraction",)


def test_tag_unobserved_when_request_names_none_and_zero_when_no_match() -> None:
    cap, tag = tag_signal(["a"], ["b"], [], [])
    assert cap.value is None and tag.value is None
    _, miss = tag_signal(["x"], [], [], ["pdf"])
    assert miss.value == 0.0 and miss.detail_code == "no_match"


def test_lexical_normalizes_by_top_hit() -> None:
    scores = {"a": 4.0, "b": 2.0}
    assert lexical_signal("a", scores).value == 1.0
    assert lexical_signal("b", scores).value == 0.5
    assert lexical_signal("c", scores).value == 0.0
    assert lexical_signal("a", None).value is None


def test_telemetry_unknown_error_rate_is_unobserved_not_zero_errors() -> None:
    success, latency, usage = telemetry_signal(_point(error_rate=None), 100.0)
    assert success.value is None
    assert success.detail_code == "error_rate_unknown"
    assert latency.value == 0.5
    assert usage.value is not None


def test_telemetry_values_and_none_point() -> None:
    success, latency, usage = telemetry_signal(_point(error_rate=0.25, p95_ms=300), 100.0)
    assert success.value == 0.75
    assert latency.value == 0.25
    assert usage.value is not None and 0.0 < usage.value < 1.0
    none_parts = telemetry_signal(None, 100.0)
    assert all(p.value is None for p in none_parts)
    assert telemetry_signal(_point(p95_ms=None), 100.0)[1].value is None
    assert telemetry_signal(_point(), None)[1].value is None


def test_usage_saturates_and_is_monotonic() -> None:
    values = [
        telemetry_signal(_point(event_count=n), None)[2].value for n in (0, 1, 10, 1000, 10**6)
    ]
    assert values[0] == 0.0 and values[-1] == 1.0
    floats = [v for v in values if v is not None]
    assert floats == sorted(floats)


def test_pool_median() -> None:
    pts = [_point(p95_ms=10), _point(p95_ms=30), None, _point(p95_ms=None)]
    assert latency_pool_median(pts) == 20.0
    assert latency_pool_median([None]) is None


def test_proximity_best_path_and_bounds() -> None:
    near = proximity_signal(
        [ProximityPath(hops=2, edge_type="uses"), ProximityPath(hops=1, edge_type="owns")]
    )
    assert near.value == 1.0 and near.edge_type == "owns" and near.hops == 1
    two = proximity_signal([ProximityPath(hops=2, edge_type="uses")])
    assert two.value == 0.5 and two.hops == 2
    assert proximity_signal([ProximityPath(hops=3, edge_type="uses")]).value == 0.0
    assert proximity_signal([]).value == 0.0
    assert proximity_signal(None).value is None
