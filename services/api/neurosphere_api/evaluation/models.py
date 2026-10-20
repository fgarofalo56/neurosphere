"""Wire models for the evaluation quality API (PRP-16 item 4).

``EvaluationResult`` is the PRP-01 generated document verbatim. Unknown is ``None`` (serialized
as null) everywhere below; it is never rendered as 0. Nothing here states or implies a guarantee
or an SLA: the grounded-answer figure is a pilot-set target estimate with an interval.

No ``from __future__ import annotations``: FastAPI inspects these models.
"""

from typing import Final, Literal

from neurosphere_contracts.evaluation.v1.evaluation_result import EvaluationResult
from pydantic import BaseModel, ConfigDict

__all__ = [
    "PILOT_TARGET",
    "PILOT_TARGET_LABEL",
    "CoveragePoint",
    "DriftAlertOut",
    "JudgeOut",
    "MissingLabels",
    "PilotGroundedRate",
    "QualityResponse",
    "ResultsList",
    "Trend",
    "TrendPoint",
]

PILOT_TARGET: Final = 0.9
PILOT_TARGET_LABEL: Final = "pilot-set target: at least 90%"


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ResultsList(_Model):
    items: list[EvaluationResult]
    next_cursor: str | None


class JudgeOut(_Model):
    judge_kind: Literal["llm_judge", "human", "programmatic", "hybrid"]
    judge_model_id: str | None
    judge_model_version: str | None
    judge_prompt_version: str | None
    program_version: str | None


class TrendPoint(_Model):
    bucket_start: str
    value: float | None
    lower: float | None
    upper: float | None
    level: float | None
    sample_size: int
    judge: JudgeOut
    calibration_state: Literal["calibrated", "uncalibrated", "not_applicable"]


class Trend(_Model):
    dimension: str
    points: list[TrendPoint]


class CoveragePoint(_Model):
    stratum: str
    sampled: int
    population: int | None
    coverage_fraction: float | None


class MissingLabels(_Model):
    """Counts of judged items, items with a consensus human label, and items missing one.

    ``labelled``/``missing`` are null when judged items exist but no calibration report says how
    many are labelled (unknown, not 0).
    """

    judged: int | None
    labelled: int | None
    missing: int | None


class PilotGroundedRate(_Model):
    value: float | None
    lower: float | None
    upper: float | None
    level: float | None
    n: int
    method: Literal["wilson_score", "not_estimable"]
    target: float = PILOT_TARGET
    target_label: str = PILOT_TARGET_LABEL


class DriftAlertOut(_Model):
    dimension: str
    subject_id: str
    detected_at: str
    statistic: float
    threshold: float


class QualityResponse(_Model):
    trends: list[Trend]
    coverage: list[CoveragePoint]
    missing_labels: MissingLabels
    pilot_grounded_rate: PilotGroundedRate
    drift_alerts: list[DriftAlertOut]
