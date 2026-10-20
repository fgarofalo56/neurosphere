"""Judge-versus-human calibration statistics (PRP-16 item 3). Pure: no I/O, clock or registry.

A judge score is calibrated only when enough human labels back it. Below ``min_labels`` pairs (or
when the statistic is undefined, e.g. a constant series) the report is ``uncalibrated``: agreement
is ``None`` (never 0), the interval is ``not_estimable`` and no contract ``Calibration`` block is
produced.

Methods:
- Pairs: judged items of the dimension with a score, matched to the consensus human label
  (``LabelSet`` rule: strict majority; a tie is unlabelled).
- Agreement: ``cohen_kappa`` (binary/categorical, labels compared by equality), ``spearman``
  (ordinal/continuous, average ranks for ties) or ``accuracy`` (exact match).
- Agreement interval: ``accuracy`` uses the Wilson interval (see ``intervals``); the other metrics
  use a percentile bootstrap (1000 resamples of the pairs, ``random.Random(seed)``, so the result
  is deterministic for a given seed). Resamples where the statistic is undefined are dropped; if
  fewer than half remain the interval is not estimable.
- Bias: mean (judge - human) with a normal-approximation interval; it assumes judge and human use
  the same numeric scale. ``length_bias`` is Spearman rho between ``response_length`` and the
  signed error (judge - human), ``failed`` when ``|rho| >= LENGTH_BIAS_THRESHOLD``. It needs
  ``response_length`` on every pair and at least ``min_labels`` pairs, otherwise ``not_run``.
  ``position_bias``, ``verbosity_bias`` and ``self_preference_bias`` need inputs this module does
  not take (swapped-order runs, a verbosity probe, the generator identity), so they are always
  ``not_run``: ``passed`` is never reported without evidence.
- Coverage: per stratum, judged items (with a score), how many have a consensus label, how many
  are missing one, and ``label_fraction = labelled / judged`` (``None`` when nothing was judged).
"""

from __future__ import annotations

import random
from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime
from math import sqrt
from statistics import stdev
from typing import Final, Literal

from neurosphere_contracts.evaluation.v1.evaluation_result import (
    Agreement,
    BiasCheck,
    Calibration,
    OpaqueId,
    Timestamp,
    Uncertainty,
    Version,
)
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from neurosphere_core.errors import InvalidSchemaError
from neurosphere_core.evaluation.calibration.intervals import (
    Interval,
    mean_difference_interval,
    proportion_interval,
)
from neurosphere_core.evaluation.calibration.labels import (
    VERSION_PATTERN,
    Dimension,
    LabelSet,
)

__all__ = [
    "DEFAULT_MIN_LABELS",
    "LENGTH_BIAS_THRESHOLD",
    "BiasEstimate",
    "CalibrationReport",
    "JudgedItem",
    "StratumCoverage",
    "calibrate",
    "format_timestamp",
    "to_contract_calibration",
    "to_contract_uncertainty",
]

Metric = Literal["cohen_kappa", "spearman", "accuracy"]

DEFAULT_MIN_LABELS: Final = 20
LENGTH_BIAS_THRESHOLD: Final = 0.3
_BOOTSTRAP_RESAMPLES: Final = 1000
_ID_PATTERN: Final = r"^[A-Za-z0-9][A-Za-z0-9._:/=-]{0,255}$"


def format_timestamp(value: datetime) -> str:
    """RFC 3339 UTC with a Z suffix, as the contract requires."""
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class JudgedItem(BaseModel):
    """One judge verdict. ``score`` is ``None`` when the judge abstained or failed (not 0)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    item_id: str = Field(pattern=_ID_PATTERN)
    stratum: str = Field(min_length=1, max_length=128)
    dimension: Dimension
    judge_config_id: str = Field(pattern=_ID_PATTERN)
    judge_config_version: str = Field(pattern=VERSION_PATTERN)
    score: float | None = Field(default=None, allow_inf_nan=False)
    response_length: int | None = Field(default=None, ge=0)


class StratumCoverage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    stratum: str
    judged: int = Field(ge=0)
    labelled: int = Field(ge=0)
    missing: int = Field(ge=0)
    label_fraction: float | None = Field(default=None, ge=0.0, le=1.0)


class BiasEstimate(BaseModel):
    """Mean judge-minus-human difference; ``mean_difference`` is ``None`` with no pairs."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    mean_difference: float | None
    interval: Interval
    sample_size: int = Field(ge=0)


class BiasCheckResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    check: Literal["position_bias", "verbosity_bias", "self_preference_bias", "length_bias"]
    result: Literal["passed", "failed", "not_run"]
    value: float | None = None


class CalibrationReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    calibration_ref: str
    dimension: Dimension
    judge_config_id: str | None
    judge_config_version: str | None
    label_set_version: str
    calibrated_at: AwareDatetime
    state: Literal["calibrated", "uncalibrated"]
    uncalibrated_reason: str | None
    metric: Metric
    agreement: float | None
    agreement_sample_size: int = Field(ge=0)
    agreement_interval: Interval
    bias: BiasEstimate
    bias_checks: tuple[BiasCheckResult, ...]
    coverage: tuple[StratumCoverage, ...]
    overall_coverage: StratumCoverage
    min_labels: int = Field(ge=1)


# --- statistics -------------------------------------------------------------------------------


def _cohen_kappa(a: Sequence[float], b: Sequence[float]) -> float | None:
    n = len(a)
    if n == 0:
        return None
    po = sum(x == y for x, y in zip(a, b, strict=True)) / n
    pe = sum((a.count(c) / n) * (b.count(c) / n) for c in set(a) | set(b))
    if pe >= 1.0:
        return None  # both raters constant: chance agreement is total, kappa undefined
    return (po - pe) / (1.0 - pe)


def _ranks(values: Sequence[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def _spearman(a: Sequence[float], b: Sequence[float]) -> float | None:
    n = len(a)
    if n < 2:
        return None
    ra, rb = _ranks(a), _ranks(b)
    ma, mb = sum(ra) / n, sum(rb) / n
    cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb, strict=True))
    va = sum((x - ma) ** 2 for x in ra)
    vb = sum((y - mb) ** 2 for y in rb)
    if va == 0.0 or vb == 0.0:
        return None
    return max(-1.0, min(1.0, cov / sqrt(va * vb)))


def _accuracy(a: Sequence[float], b: Sequence[float]) -> float | None:
    if not a:
        return None
    return sum(x == y for x, y in zip(a, b, strict=True)) / len(a)


def _statistic(metric: Metric, a: Sequence[float], b: Sequence[float]) -> float | None:
    if metric == "cohen_kappa":
        return _cohen_kappa(a, b)
    if metric == "spearman":
        return _spearman(a, b)
    return _accuracy(a, b)


def _bootstrap_interval(
    metric: Metric,
    judge: Sequence[float],
    human: Sequence[float],
    *,
    level: float,
    seed: int,
) -> Interval:
    rng = random.Random(seed)  # noqa: S311 - deterministic resampling, not security
    n = len(judge)
    stats: list[float] = []
    for _ in range(_BOOTSTRAP_RESAMPLES):
        idx = [rng.randrange(n) for _ in range(n)]
        value = _statistic(metric, [judge[i] for i in idx], [human[i] for i in idx])
        if value is not None:
            stats.append(value)
    if len(stats) < _BOOTSTRAP_RESAMPLES // 2 or len(stats) < 2:
        return Interval.not_estimable()
    stats.sort()
    tail = (1.0 - level) / 2.0
    lo = stats[int(tail * (len(stats) - 1))]
    hi = stats[round((1.0 - tail) * (len(stats) - 1))]
    return Interval(
        method="bootstrap", lower=lo, upper=hi, level=level, standard_error=stdev(stats)
    )


# --- calibrate --------------------------------------------------------------------------------


def _coverage(stratum: str, judged: int, labelled: int) -> StratumCoverage:
    return StratumCoverage(
        stratum=stratum,
        judged=judged,
        labelled=labelled,
        missing=judged - labelled,
        label_fraction=(labelled / judged) if judged else None,
    )


def calibrate(
    judged: Sequence[JudgedItem],
    labels: LabelSet,
    *,
    dimension: Dimension,
    label_set_version: str,
    metric: Metric,
    calibration_ref: str,
    calibrated_at: AwareDatetime,
    min_labels: int = DEFAULT_MIN_LABELS,
    level: float = 0.95,
    seed: int = 0,
) -> CalibrationReport:
    """Calibrate the judge verdicts of ``dimension`` against the human ``labels``."""
    if labels.label_set_version != label_set_version:
        raise InvalidSchemaError(
            "label_set_version does not match the label set", reason="label_set_version_mismatch"
        )
    if min_labels < 1:
        raise InvalidSchemaError("min_labels must be >= 1", reason="invalid_min_labels")
    items = [j for j in judged if j.dimension == dimension]
    ids = [j.item_id for j in items]
    if len(set(ids)) != len(ids):
        raise InvalidSchemaError("duplicate judged item", reason="duplicate_judged_item")
    configs = {(j.judge_config_id, j.judge_config_version) for j in items}
    if len(configs) > 1:
        raise InvalidSchemaError("judged items span several judge configs", reason="mixed_judges")
    config_id, config_version = next(iter(configs)) if configs else (None, None)

    consensus = labels.consensus_map(dimension)
    scored = [j for j in items if j.score is not None]
    pairs = [(j, consensus[j.item_id]) for j in scored if j.item_id in consensus]

    per_stratum: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for j in scored:
        per_stratum[j.stratum][0] += 1
        per_stratum[j.stratum][1] += j.item_id in consensus
    coverage = tuple(_coverage(s, c[0], c[1]) for s, c in sorted(per_stratum.items()))
    overall = _coverage("all", len(scored), len(pairs))

    judge = [float(j.score) for j, _ in pairs if j.score is not None]
    human = [h for _, h in pairs]
    n = len(pairs)

    agreement: float | None = None
    interval = Interval.not_estimable()
    reason: str | None = None
    if n < min_labels:
        reason = "insufficient_labels"
    else:
        agreement = _statistic(metric, judge, human)
        if agreement is None:
            reason = "statistic_undefined"
        elif metric == "accuracy":
            interval = proportion_interval(round(agreement * n), n, level)
        else:
            interval = _bootstrap_interval(metric, judge, human, level=level, seed=seed)

    diffs = [j - h for j, h in zip(judge, human, strict=True)]
    bias = BiasEstimate(
        mean_difference=(sum(diffs) / n) if n else None,
        interval=mean_difference_interval(diffs, level),
        sample_size=n,
    )

    length_value: float | None = None
    lengths = [j.response_length for j, _ in pairs]
    if n >= min_labels and all(x is not None for x in lengths):
        length_value = _spearman([float(x) for x in lengths if x is not None], diffs)
    if length_value is None:
        length_check = BiasCheckResult(check="length_bias", result="not_run")
    else:
        failed = abs(length_value) >= LENGTH_BIAS_THRESHOLD
        length_check = BiasCheckResult(
            check="length_bias", result="failed" if failed else "passed", value=length_value
        )
    checks = (
        BiasCheckResult(check="position_bias", result="not_run"),
        BiasCheckResult(check="verbosity_bias", result="not_run"),
        BiasCheckResult(check="self_preference_bias", result="not_run"),
        length_check,
    )

    return CalibrationReport(
        calibration_ref=calibration_ref,
        dimension=dimension,
        judge_config_id=config_id,
        judge_config_version=config_version,
        label_set_version=label_set_version,
        calibrated_at=calibrated_at,
        state="calibrated" if agreement is not None else "uncalibrated",
        uncalibrated_reason=reason,
        metric=metric,
        agreement=agreement,
        agreement_sample_size=n,
        agreement_interval=interval,
        bias=bias,
        bias_checks=checks,
        coverage=coverage,
        overall_coverage=overall,
        min_labels=min_labels,
    )


# --- contract mapping -------------------------------------------------------------------------


def to_contract_uncertainty(interval: Interval) -> Uncertainty:
    return Uncertainty(
        method=interval.method,
        lower=interval.lower,
        upper=interval.upper,
        level=interval.level,
        standard_error=interval.standard_error,
    )


def to_contract_calibration(report: CalibrationReport) -> Calibration | None:
    """The contract ``Calibration`` block, or ``None`` when the report is uncalibrated."""
    if report.state != "calibrated" or report.agreement is None:
        return None
    return Calibration(
        calibration_ref=OpaqueId(report.calibration_ref),
        human_label_set_version=Version(report.label_set_version),
        agreement=Agreement(
            metric=report.metric,
            value=report.agreement,
            sample_size=report.agreement_sample_size,
        ),
        bias_checks=[
            BiasCheck(check=c.check, result=c.result, value=c.value) for c in report.bias_checks
        ],
        calibrated_at=Timestamp(format_timestamp(report.calibrated_at)),
    )
