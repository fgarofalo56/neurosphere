"""Score drift detection (PRP-16 item 3). Pure: the caller supplies ``detected_at``.

Method: **Population Stability Index** between a baseline window and the current window of judge
scores for one dimension.

    bins   = ``BINS`` equal-width bins over ``score_range`` (default 10 bins over [0, 1])
    e_i, a_i = baseline and current share of scores in bin i, floored at ``EPSILON`` so an empty
               bin does not produce an infinite term
    PSI    = sum_i (a_i - e_i) * ln(a_i / e_i)

PSI works for both binary pass/fail scores and continuous scores, is symmetric and has a
conventional reading (< 0.1 stable, 0.1-0.25 moderate, > 0.25 major shift). ``threshold`` is the
PSI at or above which an alert fires. PSI is noisy on small samples, so fewer than ``min_n``
scored items in either window returns ``insufficient_evidence`` explicitly (never ``stable``).
Abstained items (``score is None``) are excluded, not counted as 0.
"""

from __future__ import annotations

from collections.abc import Sequence
from math import log
from typing import Final, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from neurosphere_core.errors import InvalidSchemaError
from neurosphere_core.evaluation.calibration.calibration import JudgedItem, format_timestamp
from neurosphere_core.evaluation.calibration.labels import Dimension

__all__ = ["BINS", "DriftAlert", "DriftResult", "detect_drift", "population_stability_index"]

BINS: Final = 10
EPSILON: Final = 1e-4
_ID_PATTERN: Final = r"^[A-Za-z0-9][A-Za-z0-9._:/=-]{0,255}$"


class DriftAlert(BaseModel):
    """The alert payload of the quality API wire contract."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    dimension: Dimension
    subject_id: str
    detected_at: str
    statistic: float
    threshold: float


class DriftResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    state: Literal["drift", "stable", "insufficient_evidence"]
    dimension: Dimension
    subject_id: str
    statistic: float | None
    threshold: float
    baseline_n: int = Field(ge=0)
    current_n: int = Field(ge=0)
    min_n: int = Field(ge=1)
    alert: DriftAlert | None = None


def population_stability_index(
    baseline: Sequence[float],
    current: Sequence[float],
    *,
    score_range: tuple[float, float] = (0.0, 1.0),
    bins: int = BINS,
) -> float:
    """PSI of two non-empty score samples; scores outside ``score_range`` are rejected."""
    lo, hi = score_range
    if not hi > lo or bins < 2:
        raise InvalidSchemaError("invalid score_range or bins", reason="invalid_bins")
    if not baseline or not current:
        raise InvalidSchemaError("PSI needs two non-empty samples", reason="empty_sample")

    def shares(values: Sequence[float]) -> list[float]:
        counts = [0] * bins
        for v in values:
            if not lo <= v <= hi:
                raise InvalidSchemaError("score outside score_range", reason="score_out_of_range")
            counts[min(int((v - lo) / (hi - lo) * bins), bins - 1)] += 1
        return [max(c / len(values), EPSILON) for c in counts]

    expected, actual = shares(baseline), shares(current)
    return sum((a - e) * log(a / e) for e, a in zip(expected, actual, strict=True))


def detect_drift(
    baseline: Sequence[JudgedItem],
    current: Sequence[JudgedItem],
    *,
    dimension: Dimension,
    subject_id: str,
    threshold: float,
    min_n: int,
    detected_at: AwareDatetime,
    score_range: tuple[float, float] = (0.0, 1.0),
) -> DriftResult:
    """Compare ``current`` to ``baseline`` scores of ``dimension`` (see the module docstring)."""
    if threshold <= 0.0 or min_n < 1:
        raise InvalidSchemaError("threshold must be > 0 and min_n >= 1", reason="invalid_params")
    if not subject_id or len(subject_id) > 256:
        raise InvalidSchemaError("invalid subject_id", reason="invalid_subject_id")
    base = [j.score for j in baseline if j.dimension == dimension and j.score is not None]
    curr = [j.score for j in current if j.dimension == dimension and j.score is not None]
    common = {
        "dimension": dimension,
        "subject_id": subject_id,
        "threshold": threshold,
        "baseline_n": len(base),
        "current_n": len(curr),
        "min_n": min_n,
    }
    if len(base) < min_n or len(curr) < min_n:
        return DriftResult(state="insufficient_evidence", statistic=None, **common)  # type: ignore[arg-type]
    psi = population_stability_index(base, curr, score_range=score_range)
    if psi >= threshold:
        alert = DriftAlert(
            dimension=dimension,
            subject_id=subject_id,
            detected_at=format_timestamp(detected_at),
            statistic=psi,
            threshold=threshold,
        )
        return DriftResult(state="drift", statistic=psi, alert=alert, **common)  # type: ignore[arg-type]
    return DriftResult(state="stable", statistic=psi, **common)  # type: ignore[arg-type]
