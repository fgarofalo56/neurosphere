"""Pure computation of the ``/quality`` response from already scope-filtered records.

Rules (PRP-16 clarifications 8-9, gotchas):

* Trends are bucketed by the UTC day of ``completed_at`` and by judge identity, so a point always
  carries exactly one judge. Within a bucket the value is the sample-size-weighted mean of the
  scores that have a value; bounds are the weighted mean of the contributing bounds and are
  reported only when every valued contributor has bounds at one shared level (a conservative
  approximation: it is never narrower than a pooled interval). Unknown is null, never 0.
* ``calibration_state`` is ``not_applicable`` for programmatic and human judges; otherwise it comes
  from the stored ``CalibrationReport`` for that judge config + dimension (none: uncalibrated).
* The pilot grounded-answer rate pools groundedness scores of the configured pilot datasets as
  successes / n and reports a Wilson score interval. It is a pilot-set target estimate, never a
  guarantee or an SLA.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Collection, Iterable, Sequence
from datetime import UTC, datetime

from neurosphere_contracts.evaluation.v1.evaluation_result import EvaluationResult, Judge, Score
from neurosphere_core.evaluation.calibration import (
    CalibrationReport,
    DriftAlert,
    proportion_interval,
)
from neurosphere_core.evaluation.store import SamplingCoverage, judge_config_key

from neurosphere_api.evaluation.models import (
    CoveragePoint,
    DriftAlertOut,
    JudgeOut,
    MissingLabels,
    PilotGroundedRate,
    QualityResponse,
    Trend,
    TrendPoint,
)

__all__ = ["PILOT_LEVEL", "compute_quality", "pilot_grounded_rate"]

PILOT_LEVEL = 0.95

type _JudgeId = tuple[str, str | None, str | None, str | None, str | None]


def _judge_id(judge: Judge) -> _JudgeId:
    return (
        judge.judge_kind,
        judge.judge_model_id.root if judge.judge_model_id else None,
        judge.judge_model_version.root if judge.judge_model_version else None,
        judge.judge_prompt_version.root if judge.judge_prompt_version else None,
        judge.program_version.root if judge.program_version else None,
    )


def _day_start(timestamp: str) -> str:
    parsed = datetime.fromisoformat(timestamp).astimezone(UTC)
    return parsed.strftime("%Y-%m-%dT00:00:00Z")


def _calibration_state(
    judge: Judge, dimension: str, reports: dict[tuple[str, str, str], CalibrationReport]
) -> str:
    if judge.judge_kind not in ("llm_judge", "hybrid"):
        return "not_applicable"
    key = judge_config_key(judge)
    if key is None:
        return "uncalibrated"
    report = reports.get((key[0], key[1], dimension))
    return "calibrated" if report is not None and report.state == "calibrated" else "uncalibrated"


def _point(bucket: str, judge: Judge, scores: Sequence[Score], state: str) -> TrendPoint:
    valued = [s for s in scores if s.value is not None]
    sample_size = sum(s.sample_size for s in scores)
    value = lower = upper = level = None
    if valued:
        weights = [float(s.sample_size) or 1.0 for s in valued]
        total = sum(weights)
        value = sum(w * (s.value or 0.0) for w, s in zip(weights, valued, strict=True)) / total
        bounded = [
            s.uncertainty.lower is not None
            and s.uncertainty.upper is not None
            and s.uncertainty.level is not None
            and s.uncertainty.method != "not_estimable"
            for s in valued
        ]
        levels = {s.uncertainty.level for s in valued}
        if all(bounded) and len(levels) == 1:
            lower = (
                sum(w * (s.uncertainty.lower or 0.0) for w, s in zip(weights, valued, strict=True))
                / total
            )
            upper = (
                sum(w * (s.uncertainty.upper or 0.0) for w, s in zip(weights, valued, strict=True))
                / total
            )
            level = next(iter(levels))
    return TrendPoint(
        bucket_start=bucket,
        value=value,
        lower=lower,
        upper=upper,
        level=level,
        sample_size=sample_size,
        judge=JudgeOut(
            judge_kind=judge.judge_kind,
            judge_model_id=judge.judge_model_id.root if judge.judge_model_id else None,
            judge_model_version=(
                judge.judge_model_version.root if judge.judge_model_version else None
            ),
            judge_prompt_version=(
                judge.judge_prompt_version.root if judge.judge_prompt_version else None
            ),
            program_version=judge.program_version.root if judge.program_version else None,
        ),
        calibration_state=state,  # type: ignore[arg-type]  # one of the three literals
    )


def _trends(
    results: Iterable[EvaluationResult],
    reports: dict[tuple[str, str, str], CalibrationReport],
) -> list[Trend]:
    buckets: dict[tuple[str, str, _JudgeId], tuple[Judge, list[Score]]] = {}
    for result in results:
        day = _day_start(result.completed_at.root)
        for score in result.scores:
            key = (score.dimension, day, _judge_id(result.judge))
            buckets.setdefault(key, (result.judge, []))[1].append(score)
    by_dimension: dict[str, list[TrendPoint]] = defaultdict(list)
    for (dimension, day, _), (judge, scores) in sorted(
        buckets.items(), key=lambda kv: (kv[0][0], kv[0][1], tuple(x or "" for x in kv[0][2]))
    ):
        state = _calibration_state(judge, dimension, reports)
        by_dimension[dimension].append(_point(day, judge, scores, state))
    return [Trend(dimension=d, points=pts) for d, pts in sorted(by_dimension.items())]


def pilot_grounded_rate(
    results: Iterable[EvaluationResult], pilot_dataset_ids: Collection[str]
) -> PilotGroundedRate:
    successes = 0
    n = 0
    if pilot_dataset_ids:
        for result in results:
            if result.dataset.dataset_id.root not in pilot_dataset_ids:
                continue
            for score in result.scores:
                span = score.scale.max - score.scale.min
                if (
                    score.dimension != "groundedness"
                    or score.value is None
                    or score.sample_size <= 0
                    or span <= 0
                ):
                    continue
                normalised = (score.value - score.scale.min) / span
                n += score.sample_size
                successes += min(score.sample_size, round(normalised * score.sample_size))
    if n == 0:
        return PilotGroundedRate(
            value=None, lower=None, upper=None, level=None, n=0, method="not_estimable"
        )
    interval = proportion_interval(successes, n, PILOT_LEVEL)
    return PilotGroundedRate(
        value=successes / n,
        lower=interval.lower,
        upper=interval.upper,
        level=interval.level,
        n=n,
        method="wilson_score",
    )


def _missing_labels(
    results: Sequence[EvaluationResult], reports: Iterable[CalibrationReport]
) -> MissingLabels:
    rows = [r.overall_coverage for r in reports]
    if rows:
        return MissingLabels(
            judged=sum(c.judged for c in rows),
            labelled=sum(c.labelled for c in rows),
            missing=sum(c.missing for c in rows),
        )
    judged = sum(
        s.sample_size
        for r in results
        if r.judge.judge_kind in ("llm_judge", "hybrid")
        for s in r.scores
        if s.value is not None
    )
    if judged == 0:
        return MissingLabels(judged=0, labelled=0, missing=0)
    return MissingLabels(judged=judged, labelled=None, missing=None)


def compute_quality(
    results: Sequence[EvaluationResult],
    calibrations: Sequence[CalibrationReport],
    coverage: Sequence[SamplingCoverage],
    drift_alerts: Sequence[DriftAlert],
    pilot_dataset_ids: Collection[str],
) -> QualityResponse:
    reports = {
        (r.judge_config_id, r.judge_config_version, r.dimension): r
        for r in calibrations
        if r.judge_config_id is not None and r.judge_config_version is not None
    }
    return QualityResponse(
        trends=_trends(results, reports),
        coverage=[
            CoveragePoint(
                stratum=c.stratum,
                sampled=c.sampled,
                population=c.population,
                coverage_fraction=c.coverage_fraction,
            )
            for c in coverage
        ],
        missing_labels=_missing_labels(results, calibrations),
        pilot_grounded_rate=pilot_grounded_rate(results, pilot_dataset_ids),
        drift_alerts=[
            DriftAlertOut(
                dimension=a.dimension,
                subject_id=a.subject_id,
                detected_at=a.detected_at,
                statistic=a.statistic,
                threshold=a.threshold,
            )
            for a in drift_alerts
        ],
    )
