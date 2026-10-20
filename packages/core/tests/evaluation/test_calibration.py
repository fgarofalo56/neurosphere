"""Calibration statistics: agreement, uncertainty, bias, coverage, contract mapping."""

from __future__ import annotations

import random
from datetime import UTC, datetime

import pytest
from neurosphere_contracts.evaluation.v1.evaluation_result import Calibration
from neurosphere_core.errors import InvalidSchemaError
from neurosphere_core.evaluation.calibration import (
    HumanLabelRecord,
    JudgedItem,
    LabelSet,
    calibrate,
    ingest_labels,
    to_contract_calibration,
)

T = datetime(2026, 10, 19, 12, 0, 0, tzinfo=UTC)


def label_set(values: dict[str, float], version: str = "labels-1") -> LabelSet:
    return ingest_labels(
        [
            HumanLabelRecord(
                item_id=k,
                dimension="groundedness",
                label_set_version=version,
                value=v,
                labeler="l1",
                labelled_at=T,
            )
            for k, v in values.items()
        ]
    )


def judged(
    scores: dict[str, float | None],
    stratum: str = "s1",
    lengths: dict[str, int] | None = None,
    version: str = "j1",
) -> list[JudgedItem]:
    return [
        JudgedItem(
            item_id=k,
            stratum=stratum,
            dimension="groundedness",
            judge_config_id="judge",
            judge_config_version=version,
            score=v,
            response_length=(lengths or {}).get(k),
        )
        for k, v in scores.items()
    ]


def binary_fixture(n: int = 40, flips: int = 4) -> tuple[list[JudgedItem], LabelSet]:
    human = {f"i{i}": float(i % 2) for i in range(n)}
    judge: dict[str, float | None] = {
        k: (1.0 - v if int(k[1:]) < flips else v) for k, v in human.items()
    }
    return judged(judge), label_set(human)


def run(items: list[JudgedItem], labels: LabelSet, metric: str = "cohen_kappa", **kw):  # type: ignore[no-untyped-def]
    return calibrate(
        items,
        labels,
        dimension="groundedness",
        label_set_version="labels-1",
        metric=metric,  # type: ignore[arg-type]
        calibration_ref="cal:run1",
        calibrated_at=T,
        **kw,
    )


def test_kappa_value_interval_and_contract_block() -> None:
    items, labels = binary_fixture()
    rep = run(items, labels)
    # 36/40 agree, balanced marginals: po = 0.9, pe = 0.5, kappa = 0.8
    assert rep.state == "calibrated"
    assert rep.agreement == pytest.approx(0.8)
    assert rep.agreement_sample_size == 40
    iv = rep.agreement_interval
    assert iv.method == "bootstrap" and iv.level == 0.95
    assert iv.lower is not None and iv.upper is not None
    assert iv.lower < 0.8 < iv.upper
    block = to_contract_calibration(rep)
    assert isinstance(block, Calibration)
    assert Calibration.model_validate(block.model_dump(mode="json")) == block
    assert block.agreement.sample_size == 40
    assert block.human_label_set_version.root == "labels-1"
    assert block.calibrated_at.root == "2026-10-19T12:00:00Z"
    checks = {c.check: c.result for c in block.bias_checks or []}
    assert checks == {
        "position_bias": "not_run",
        "verbosity_bias": "not_run",
        "self_preference_bias": "not_run",
        "length_bias": "not_run",
    }


def test_bootstrap_is_deterministic_per_seed() -> None:
    items, labels = binary_fixture()
    a, b = run(items, labels, seed=7), run(items, labels, seed=7)
    assert a.agreement_interval == b.agreement_interval
    assert run(items, labels, seed=8).agreement_interval != a.agreement_interval


def test_accuracy_uses_wilson() -> None:
    items, labels = binary_fixture(n=50, flips=5)  # 45/50
    rep = run(items, labels, metric="accuracy")
    assert rep.agreement == pytest.approx(0.9)
    assert rep.agreement_interval.method == "confidence_interval"
    assert rep.agreement_interval.lower == pytest.approx(0.78640, abs=1e-5)
    assert rep.agreement_interval.upper == pytest.approx(0.95652, abs=1e-5)


def test_spearman_on_ordinal_scores() -> None:
    rng = random.Random(3)  # noqa: S311 - seeded fixture data
    human = {f"i{i}": float(rng.randint(1, 5)) for i in range(40)}
    judge: dict[str, float | None] = {
        k: v + (1.0 if i % 5 == 0 else 0.0) for i, (k, v) in enumerate(human.items())
    }
    rep = run(judged(judge), label_set(human), metric="spearman")
    assert rep.state == "calibrated"
    assert rep.agreement is not None and rep.agreement > 0.85
    assert rep.bias.mean_difference == pytest.approx(0.2)
    assert rep.bias.interval.method == "confidence_interval"
    assert to_contract_calibration(rep) is not None


def test_too_few_labels_is_uncalibrated_with_nulls() -> None:
    items, labels = binary_fixture(n=10, flips=1)
    rep = run(items, labels, min_labels=20)
    assert rep.state == "uncalibrated"
    assert rep.uncalibrated_reason == "insufficient_labels"
    assert rep.agreement is None
    assert rep.agreement_interval.method == "not_estimable"
    assert rep.agreement_interval.lower is None
    assert to_contract_calibration(rep) is None


def test_no_labels_at_all_is_uncalibrated_and_coverage_is_zero_not_unknown() -> None:
    items = judged({f"i{i}": 1.0 for i in range(25)})
    rep = run(items, label_set({"other": 1.0}))
    assert rep.state == "uncalibrated"
    assert rep.agreement_sample_size == 0
    assert rep.bias.mean_difference is None
    assert rep.overall_coverage.judged == 25
    assert rep.overall_coverage.labelled == 0
    assert rep.overall_coverage.label_fraction == 0.0  # known: 25 judged, none labelled


def test_nothing_judged_coverage_fraction_is_null() -> None:
    rep = run([], label_set({"x": 1.0}))
    assert rep.overall_coverage.judged == 0
    assert rep.overall_coverage.label_fraction is None
    assert rep.coverage == ()
    assert rep.judge_config_id is None


def test_constant_series_statistic_undefined_is_uncalibrated() -> None:
    items = judged({f"i{i}": 1.0 for i in range(30)})
    rep = run(items, label_set({f"i{i}": 1.0 for i in range(30)}))
    assert rep.state == "uncalibrated"
    assert rep.uncalibrated_reason == "statistic_undefined"
    assert rep.agreement is None


def test_coverage_per_stratum_excludes_abstained() -> None:
    a = judged({"a1": 1.0, "a2": 0.0, "a3": None, "a4": 1.0}, stratum="alpha")
    b = judged({"b1": 1.0}, stratum="beta")
    rep = run(a + b, label_set({"a1": 1.0, "a2": 0.0, "b1": 1.0}), min_labels=1)
    by = {c.stratum: c for c in rep.coverage}
    assert (by["alpha"].judged, by["alpha"].labelled, by["alpha"].missing) == (3, 2, 1)
    assert by["alpha"].label_fraction == pytest.approx(2 / 3)
    assert by["beta"].label_fraction == 1.0
    assert rep.overall_coverage.judged == 4


def test_length_bias_failed_when_error_tracks_length() -> None:
    n = 40
    human = {f"i{i}": 0.5 for i in range(n)}
    judge: dict[str, float | None] = {f"i{i}": 0.5 + i / 100 for i in range(n)}
    lengths = {f"i{i}": 100 + i * 10 for i in range(n)}
    rep = run(judged(judge, lengths=lengths), label_set(human), metric="spearman", min_labels=20)
    check = next(c for c in rep.bias_checks if c.check == "length_bias")
    assert check.result == "failed"
    assert check.value == pytest.approx(1.0)


def test_length_bias_passed_when_uncorrelated() -> None:
    rng = random.Random(5)  # noqa: S311 - seeded fixture data
    n = 60
    human = {f"i{i}": 0.5 for i in range(n)}
    judge: dict[str, float | None] = {f"i{i}": 0.5 + rng.uniform(-0.1, 0.1) for i in range(n)}
    lengths = {f"i{i}": rng.randint(50, 500) for i in range(n)}
    rep = run(judged(judge, lengths=lengths), label_set(human), metric="spearman")
    check = next(c for c in rep.bias_checks if c.check == "length_bias")
    assert check.result == "passed"
    assert check.value is not None and abs(check.value) < 0.3


def test_length_bias_not_run_when_lengths_incomplete() -> None:
    items, labels = binary_fixture()
    items[0] = items[0].model_copy(update={"response_length": 10})
    rep = run(items, labels)
    assert next(c for c in rep.bias_checks if c.check == "length_bias").result == "not_run"


def test_rejections() -> None:
    items, labels = binary_fixture()
    with pytest.raises(InvalidSchemaError) as exc:
        run(items + items[:1], labels)
    assert exc.value.reason == "duplicate_judged_item"
    mixed = [items[0].model_copy(update={"judge_config_version": "j2"}), *items[1:]]
    with pytest.raises(InvalidSchemaError) as exc2:
        run(mixed, labels)
    assert exc2.value.reason == "mixed_judges"
    with pytest.raises(InvalidSchemaError) as exc3:
        calibrate(
            items,
            labels,
            dimension="groundedness",
            label_set_version="other",
            metric="accuracy",
            calibration_ref="cal:x",
            calibrated_at=T,
        )
    assert exc3.value.reason == "label_set_version_mismatch"
