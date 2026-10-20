"""Drift detection: seeded drift alerts, stable does not, tiny samples are explicit."""

from __future__ import annotations

import random
from datetime import UTC, datetime

import pytest
from neurosphere_core.errors import InvalidSchemaError
from neurosphere_core.evaluation.calibration import (
    JudgedItem,
    detect_drift,
    population_stability_index,
)

NOW = datetime(2026, 10, 19, 12, 0, 0, tzinfo=UTC)


def items(
    scores: list[float | None], prefix: str, dimension: str = "groundedness"
) -> list[JudgedItem]:
    return [
        JudgedItem(
            item_id=f"{prefix}{i}",
            stratum="s",
            dimension=dimension,  # type: ignore[arg-type]
            judge_config_id="judge",
            judge_config_version="v1",
            score=s,
        )
        for i, s in enumerate(scores)
    ]


def sample(seed: int, n: int, mean: float) -> list[float]:
    rng = random.Random(seed)  # noqa: S311 - seeded fixture data
    return [min(1.0, max(0.0, rng.gauss(mean, 0.12))) for _ in range(n)]


def run(base: list[float | None], cur: list[float | None], min_n: int = 30):
    return detect_drift(
        items(base, "b"),
        items(cur, "c"),
        dimension="groundedness",
        subject_id="agent:support",
        threshold=0.25,
        min_n=min_n,
        detected_at=NOW,
    )


def test_seeded_drift_fires_alert() -> None:
    res = run(list(sample(1, 200, 0.8)), list(sample(2, 200, 0.5)))
    assert res.state == "drift"
    assert res.alert is not None
    assert res.statistic is not None and res.statistic >= 0.25
    assert res.alert.model_dump() == {
        "dimension": "groundedness",
        "subject_id": "agent:support",
        "detected_at": "2026-10-19T12:00:00Z",
        "statistic": res.statistic,
        "threshold": 0.25,
    }


def test_stable_fixture_does_not_alert() -> None:
    res = run(list(sample(1, 200, 0.8)), list(sample(2, 200, 0.8)))
    assert res.state == "stable"
    assert res.alert is None
    assert res.statistic is not None and res.statistic < 0.25


def test_tiny_sample_is_insufficient_evidence_not_stable() -> None:
    res = run(list(sample(1, 200, 0.8)), [0.1, 0.2, 0.1], min_n=30)
    assert res.state == "insufficient_evidence"
    assert res.statistic is None
    assert res.alert is None
    assert res.current_n == 3


def test_abstentions_are_excluded_not_zero() -> None:
    res = run(list(sample(1, 40, 0.8)), [None] * 100 + list(sample(2, 5, 0.8)), min_n=30)
    assert res.state == "insufficient_evidence"
    assert res.current_n == 5


def test_other_dimensions_ignored() -> None:
    other = items(list(sample(2, 200, 0.1)), "c", dimension="safety")
    res = detect_drift(
        items(list(sample(1, 200, 0.8)), "b"),
        other,
        dimension="groundedness",
        subject_id="x",
        threshold=0.25,
        min_n=30,
        detected_at=NOW,
    )
    assert res.state == "insufficient_evidence"


def test_psi_identical_is_zero_and_known_value() -> None:
    assert population_stability_index([0.5] * 10, [0.5] * 10) == pytest.approx(0.0)
    # Two bins, 50/50 vs 80/20 (epsilon floor not hit): (0.3)ln(1.6) + (-0.3)ln(0.4) = 0.2575
    psi = population_stability_index([0.1] * 5 + [0.9] * 5, [0.1] * 8 + [0.9] * 2, bins=2)
    assert psi == pytest.approx(0.3 * 0.470004 + 0.3 * 0.916291, abs=1e-5)


def test_invalid_inputs() -> None:
    with pytest.raises(InvalidSchemaError) as exc:
        population_stability_index([1.5], [0.5])
    assert exc.value.reason == "score_out_of_range"
    with pytest.raises(InvalidSchemaError):
        detect_drift(
            [], [], dimension="safety", subject_id="x", threshold=0, min_n=1, detected_at=NOW
        )
