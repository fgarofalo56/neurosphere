"""Models for the sampling worker (PRP-16 item 2): candidates, outcomes, coverage, the run report.

Every model is frozen with extra fields forbidden. Unknown is ``None``, never 0.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Final, Literal

from neurosphere_contracts.evaluation.v1.evaluation_result import EvaluationResult
from neurosphere_core.evaluation.calibration import JudgedItem
from neurosphere_core.evaluation.registry import Cloud, Dimension, JudgeConfig, RubricVersion
from neurosphere_core.evaluation.registry import normalize_classification as _normalize
from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "NO_AGENT",
    "NO_DOMAIN",
    "REASON_BODY_FIELDS",
    "REASON_CLOUD_MISMATCH",
    "REASON_FIXTURE_MISSING",
    "REASON_INVALID_VALUE",
    "REASON_JUDGE_CLOUD_MISMATCH",
    "REASON_JUDGE_ERROR",
    "REASON_JUDGE_NOT_APPROVED",
    "REASON_JUDGE_UNAVAILABLE",
    "REASON_NOT_SCORABLE",
    "REASON_NO_JUDGE",
    "REASON_PRICE_UNKNOWN",
    "Candidate",
    "GroupPopulation",
    "ItemOutcome",
    "JudgeUsage",
    "RunReport",
    "RunStatus",
    "SamplingCoverage",
    "stratum_label",
]

NO_DOMAIN: Final = "_none"
NO_AGENT: Final = "_unknown"

REASON_BODY_FIELDS: Final = "body_fields_present"
REASON_CLOUD_MISMATCH: Final = "cloud_mismatch"
REASON_NOT_SCORABLE: Final = "not_scorable_span"
REASON_NO_JUDGE: Final = "no_judge_for_dimension"
REASON_JUDGE_CLOUD_MISMATCH: Final = "judge_cloud_mismatch"
REASON_JUDGE_UNAVAILABLE: Final = "judge_unavailable"
REASON_JUDGE_NOT_APPROVED: Final = "judge_not_approved"
REASON_PRICE_UNKNOWN: Final = "price_unknown"
REASON_FIXTURE_MISSING: Final = "fixture_missing"
REASON_JUDGE_ERROR: Final = "judge_error"
REASON_INVALID_VALUE: Final = "invalid_judge_value"

RunStatus = Literal["completed", "partial", "budget_exhausted"]
OutcomeStatus = Literal["scored", "abstained", "skipped", "unevaluated"]
Mode = Literal["offline_benchmark", "online_sampled"]

_Frozen = ConfigDict(extra="forbid", frozen=True)


def stratum_label(domain: str, agent: str, classification: str) -> str:
    """The stratum key rendered as a bounded string (<= 128 chars, as ``JudgedItem`` requires)."""
    label = f"{domain}/{agent}/{classification}"
    if len(label) <= 128:
        return label
    return f"{label[:110]}~{hashlib.sha256(label.encode()).hexdigest()[:8]}"


class Candidate(BaseModel):
    """One redacted item eligible for sampling. ``payload`` is exactly what a judge may see.

    ``classification`` is the raw telemetry value (null stays null so the request and the audit
    trail show what was recorded); ``effective_classification`` fails closed to restricted.
    """

    model_config = _Frozen

    item_id: str
    domain: str = NO_DOMAIN
    agent: str = NO_AGENT
    classification: str | None
    dimension: Dimension
    payload: dict[str, Any]
    customer_id: str | None = None
    domain_id: str | None = None  # canonical domain id for the contract, when it can be built
    subject_id: str | None = None  # canonical agent id, when resolved
    raw_body_fields: int = Field(default=0, ge=0)
    event_time: datetime | None = None

    @property
    def effective_classification(self) -> str:
        return _normalize(self.classification)

    @property
    def stratum(self) -> str:
        return stratum_label(self.domain, self.agent, self.effective_classification)


class ItemOutcome(BaseModel):
    """What happened to one selected item. A skip always carries its reason."""

    model_config = _Frozen

    item_id: str
    stratum: str
    domain: str
    customer_id: str | None
    domain_id: str | None
    subject_id: str | None
    dimension: Dimension
    status: OutcomeStatus
    reason: str | None = None
    detail: str | None = None
    judge_config_id: str | None = None
    judge_config_version: str | None = None
    value: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost: Decimal | None = None
    response_length: int | None = None
    event_time: datetime | None = None


class SamplingCoverage(BaseModel):
    """Per-stratum coverage: ``sampled / population`` and what was actually evaluated."""

    model_config = _Frozen

    stratum: str
    population: Annotated[int, Field(ge=0)]
    sampled: Annotated[int, Field(ge=0)]
    evaluated: Annotated[int, Field(ge=0)]
    skipped: Annotated[int, Field(ge=0)]
    sampled_fraction: float | None
    evaluated_fraction: float | None


class GroupPopulation(BaseModel):
    """Population behind one result group (domain, subject, dimension)."""

    model_config = _Frozen

    customer_id: str | None
    domain_id: str | None
    subject_id: str | None
    dimension: Dimension
    population: Annotated[int, Field(ge=0)]


class JudgeUsage(BaseModel):
    """Evaluator consumption for one judge config; cost cites the config's price version."""

    model_config = _Frozen

    judge_config_id: str
    judge_config_version: str
    calls: Annotated[int, Field(ge=0)]
    input_tokens: Annotated[int, Field(ge=0)]
    output_tokens: Annotated[int, Field(ge=0)]
    estimated_cost: Decimal
    price_version: str | None


class RunReport(BaseModel):
    """Everything a run produced. ``results`` holds only validated contract documents."""

    model_config = _Frozen

    run_id: str
    mode: Mode
    cloud: Cloud
    status: RunStatus
    started_at: datetime
    completed_at: datetime
    seed: int | None
    rate: float | None
    dataset_id: str
    dataset_version: str
    data_state: Literal["synthetic", "redacted", "approved"]
    rubric: RubricVersion
    judge_configs: tuple[JudgeConfig, ...]
    population_total: int
    sampled_total: int
    evaluated_total: int
    unevaluated_total: int
    budget_exhausted_reason: str | None
    skip_counts: dict[str, int]
    excluded_counts: dict[str, int]
    coverage: tuple[SamplingCoverage, ...]
    group_populations: tuple[GroupPopulation, ...]
    outcomes: tuple[ItemOutcome, ...]
    judged_items: tuple[JudgedItem, ...]
    usage: tuple[JudgeUsage, ...]
    limited_dimensions: dict[str, str]
    uncalibrated_judges: tuple[str, ...] = ()
    unemitted: dict[str, int] = Field(default_factory=dict)
    results: tuple[EvaluationResult, ...] = ()
