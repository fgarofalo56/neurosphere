"""Bounded /quality read (window + row cap + truncation flag) and missing-label counting
(PRP-16 round 2 item 11)."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

import pytest
from neurosphere_api.evaluation import compute_quality
from neurosphere_api.evaluation.models import MissingLabels
from neurosphere_contracts.evaluation.v1.evaluation_result import EvaluationResult
from neurosphere_core.evaluation.calibration import CalibrationReport
from quality_api_helpers import (  # pyright: ignore[reportMissingImports]
    ALICE,
    FINANCE,
    OPERATIONS,
    T,
    make_api,
    make_report,
    make_result,
    score,
)

_FMT = "%Y-%m-%dT%H:%M:%SZ"


def _at(n: int, days_ago: int, **extra: Any) -> EvaluationResult:
    moment = T - timedelta(days=days_ago)
    return make_result(
        n,
        started_at=(moment - timedelta(minutes=1)).strftime(_FMT),
        completed_at=moment.strftime(_FMT),
        **extra,
    )


def test_window_excludes_older_results_and_is_not_truncated() -> None:
    api = make_api(
        _at(1, 100, scores=[score("groundedness", 0.1, 10)]),
        _at(2, 5, scores=[score("groundedness", 0.9, 10)]),
    )
    body = api.get(ALICE, f"/domains/{FINANCE}/quality").json()
    (trend,) = body["trends"]
    assert [p["value"] for p in trend["points"]] == [pytest.approx(0.9)]
    assert body["truncated"] is None


def test_cap_truncates_to_the_newest_and_says_so() -> None:
    results = [_at(n, 10 - n, scores=[score("groundedness", n / 10, 10)]) for n in range(1, 6)]
    api = make_api(*results, quality_max_results=2)
    body = api.get(ALICE, f"/domains/{FINANCE}/quality").json()
    assert body["truncated"] == {"limit": 2, "window_days": 90}
    (trend,) = body["trends"]
    assert sum(p["sample_size"] for p in trend["points"]) == 20  # newest 2 of 5 only
    assert sorted(p["value"] for p in trend["points"]) == [pytest.approx(0.4), pytest.approx(0.5)]


def test_exactly_at_the_cap_is_not_truncated() -> None:
    results = [_at(n, n, scores=[score("groundedness", 0.5, 10)]) for n in range(1, 4)]
    body = make_api(*results, quality_max_results=3).get(ALICE, f"/domains/{FINANCE}/quality")
    assert body.json()["truncated"] is None


def test_window_days_is_settings_driven() -> None:
    api = make_api(
        _at(1, 20, scores=[score("groundedness", 0.2, 10)]),
        _at(2, 3, scores=[score("groundedness", 0.8, 10)]),
        quality_window_days=7,
    )
    body = api.get(ALICE, f"/domains/{FINANCE}/quality").json()
    (trend,) = body["trends"]
    assert [p["sample_size"] for p in trend["points"]] == [10]
    assert body["truncated"] is None


def test_cross_domain_is_still_403_with_the_bounded_read() -> None:
    api = make_api(_at(1, 1))
    assert api.get(ALICE, f"/domains/{OPERATIONS}/quality").status_code == 403


def test_empty_window_keeps_unknown_null_not_zero() -> None:
    api = make_api(_at(1, 200))
    body = api.get(ALICE, f"/domains/{FINANCE}/quality").json()
    assert body["trends"] == []
    assert body["pilot_grounded_rate"]["value"] is None
    assert body["truncated"] is None


# --- missing labels across dimensions ---------------------------------------------------------


def _missing(report: CalibrationReport) -> MissingLabels:
    return compute_quality([], [report], [], [], frozenset()).missing_labels


def test_missing_labels_count_each_dimension_once_and_use_the_newest_report() -> None:
    api = make_api(make_result(1))
    older = make_report("groundedness", judged=10, labelled=4)
    newer = make_report("groundedness", judged=12, labelled=9).model_copy(
        update={"calibrated_at": T + timedelta(days=1), "judge_config_version": "2026-09-01+8"}
    )
    safety = make_report("safety", judged=12, labelled=12)
    for report in (older, newer, safety):
        asyncio.run(api.store.put_calibration("commercial", "contoso", FINANCE, report))
    body = api.get(ALICE, f"/domains/{FINANCE}/quality").json()
    # groundedness (newest report 12/9) + safety (12/12); the superseded older groundedness report
    # covers the same items and is not added again.
    assert body["missing_labels"] == {"judged": 24, "labelled": 21, "missing": 3}


def test_missing_labels_never_negative_when_labelled_exceeds_judged() -> None:
    base = make_report(judged=5, labelled=5)
    bad = base.model_copy(
        update={"overall_coverage": base.overall_coverage.model_copy(update={"labelled": 9})}
    )
    out = _missing(bad)
    assert (out.judged, out.labelled, out.missing) == (5, 5, 0)
