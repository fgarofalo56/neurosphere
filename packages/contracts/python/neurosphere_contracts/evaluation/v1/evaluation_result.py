# GENERATED - do not edit.
# Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
# Regenerate: python packages/contracts/scripts/generate.py
# Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
# pyright: reportAssignmentType=false, reportInvalidTypeForm=false

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    RootModel,
    StrictFloat,
    StrictInt,
    StrictStr,
)


class DataHandling(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    data_state: Literal["redacted", "approved", "synthetic"]
    boundary_cloud: Literal["commercial", "government"]
    """
    Cloud boundary the evaluation (including any judge model) ran in; must equal cloud.
    """


class SchemaVersion(RootModel[StrictStr]):
    root: Annotated[StrictStr, Field(pattern="^1\\.(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)$")]
    """
    Semantic version of this document within major 1. Within v1 only additive, optional changes are allowed (ADR-0004).
    """


class Timestamp(RootModel[StrictStr]):
    root: Annotated[
        StrictStr,
        Field(
            pattern="^[0-9]{4}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])T([01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9](\\.[0-9]{1,9})?Z$"
        ),
    ]
    """
    RFC 3339 timestamp in UTC (Z suffix required).
    """


class CanonicalId(RootModel[StrictStr]):
    root: Annotated[
        StrictStr,
        Field(
            max_length=512,
            pattern="^(commercial|government):[a-z0-9._-]+:[a-z0-9._-]+:[a-z0-9._-]+:[a-z0-9._/=-]+$",
        ),
    ]
    """
    Canonical ID cloud:customer:source:type:id (PRP-01 clarification 7). Grammar owned by schemas/catalog/v1; duplicated here as a pattern.
    """


class OpaqueId(RootModel[StrictStr]):
    root: Annotated[StrictStr, Field(pattern="^[a-z0-9][a-z0-9._:/=-]{0,255}$")]


class Version(RootModel[StrictStr]):
    root: Annotated[StrictStr, Field(pattern="^[A-Za-z0-9._+-]{1,64}$")]


class Decimal(RootModel[StrictStr]):
    root: Annotated[StrictStr, Field(pattern="^-?(0|[1-9][0-9]*)(\\.[0-9]{1,12})?$")]
    """
    Money amount as a decimal string (no floats).
    """


class NullableCount1(RootModel[StrictInt]):
    root: Annotated[StrictInt, Field(ge=0)]
    """
    Non-negative count; null means unknown, never 0.
    """


class NullableCount(RootModel[NullableCount1 | None]):
    root: NullableCount1 | None
    """
    Non-negative count; null means unknown, never 0.
    """


class Judge(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    judge_kind: Literal["llm_judge", "human", "programmatic", "hybrid"]
    judge_model_id: CanonicalId | None = None
    """
    Model deployment canonical ID of the LLM judge.
    """
    judge_model_version: Version | None = None
    judge_prompt_version: Version | None = None
    program_version: Version | None = None
    """
    Version of the programmatic scorer.
    """


class Scale(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    min: StrictFloat
    max: StrictFloat


class Uncertainty(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    method: Literal["confidence_interval", "credible_interval", "bootstrap", "not_estimable"]
    lower: StrictFloat | None = None
    upper: StrictFloat | None = None
    level: Annotated[StrictFloat | None, Field(gt=0.0, lt=1.0)] = None
    standard_error: Annotated[StrictFloat | None, Field(ge=0.0)] = None


class CoverageFraction(RootModel[StrictFloat]):
    root: Annotated[StrictFloat, Field(ge=0.0, le=1.0)]


class Window(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    start: Timestamp
    end: Timestamp


class Sampling(BaseModel):
    """
    Sampling coverage. coverage_fraction null means unknown.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    method: Literal["full", "uniform_random", "stratified", "targeted"]
    rate: Annotated[StrictFloat | None, Field(gt=0.0, le=1.0)] = None
    sample_size: Annotated[StrictInt, Field(ge=0)]
    population_size: NullableCount | None
    coverage_fraction: CoverageFraction | None
    window: Window


class Agreement(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    metric: Literal["cohen_kappa", "krippendorff_alpha", "spearman", "accuracy"]
    value: Annotated[StrictFloat, Field(ge=-1.0, le=1.0)]
    sample_size: Annotated[StrictInt, Field(ge=1)]


class BiasCheck(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    check: Literal["position_bias", "verbosity_bias", "self_preference_bias", "length_bias"]
    result: Literal["passed", "failed", "not_run"]
    value: StrictFloat | None = None


class Calibration(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    calibration_ref: OpaqueId
    """
    ID of the calibration run against human labels.
    """
    human_label_set_version: Version
    agreement: Agreement
    bias_checks: Annotated[list[BiasCheck] | None, Field(max_length=10)] = None
    calibrated_at: Timestamp


class EstimatedCost(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    amount: Decimal
    currency: Annotated[StrictStr, Field(pattern="^[A-Z]{3}$")]
    price_version: Version


class EvaluatorUsage(BaseModel):
    """
    Evaluator token and cost consumption against its budget. Estimated cost always cites price_version.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    judge_input_tokens: NullableCount | None
    judge_output_tokens: NullableCount | None
    estimated_cost: EstimatedCost | None = None


class Dataset(BaseModel):
    """
    Versioned dataset; for online_sampled this is the versioned sampling frame definition.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    dataset_id: OpaqueId
    dataset_version: Version


class Rubric(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    rubric_id: OpaqueId
    rubric_version: Version


class Score(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    dimension: Literal[
        "task_success", "groundedness", "safety", "tool_correctness", "user_feedback", "drift"
    ]
    value: StrictFloat | None
    """
    Null when the dimension could not be scored; never 0 by default.
    """
    scale: Scale
    uncertainty: Uncertainty
    sample_size: Annotated[StrictInt, Field(ge=0)]
    """
    Items scored for this dimension.
    """
    abstained_count: NullableCount | None = None


class EvaluationResult(BaseModel):
    """
    Result of an offline benchmark or a sampled online evaluation of one subject (NS-03). Datasets, rubrics and judges are versioned; every score reports uncertainty and sample size; sampling coverage is explicit; an LLM judge requires a calibration reference against human labels. Quality is not inferred from feedback alone: a run whose only dimension is user_feedback is rejected. Unknown values are null, never 0. Evaluation runs on approved, redacted or synthetic data inside the selected cloud boundary (data_handling). Rules JSON Schema cannot express: started_at <= completed_at and sampling.window.start < sampling.window.end (tests/contracts/validators.py::check_evaluation_times); score.value and uncertainty bounds within score.scale (tests/contracts/validators.py::check_evaluation_score_scale); sampling.sample_size <= sampling.population_size when known (tests/contracts/validators.py::check_evaluation_sampling_counts).
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    schema_version: SchemaVersion
    evaluation_id: OpaqueId
    cloud: Literal["commercial", "government"]
    customer_id: Annotated[StrictStr, Field(pattern="^[a-z0-9._-]{1,128}$")]
    domain_id: CanonicalId
    """
    Canonical Domain ID used for scope filtering against the server-derived IdentityScope.
    """
    subject_id: CanonicalId
    """
    Canonical ID of the evaluated AgentVersion or ModelDeployment.
    """
    mode: Literal["offline_benchmark", "online_sampled"]
    status: Literal["completed", "partial", "failed"]
    """
    partial means some items were not scored (budget exhausted, abstentions); coverage shows how many.
    """
    dataset: Dataset
    """
    Versioned dataset; for online_sampled this is the versioned sampling frame definition.
    """
    rubric: Rubric
    judge: Judge
    scores: Annotated[list[Score], Field(max_length=32, min_length=1)]
    sampling: Sampling
    calibration: Calibration | None
    """
    Calibration of the judge against human labels. Required (non-null) when judge.judge_kind is llm_judge or hybrid; null otherwise allowed.
    """
    data_handling: DataHandling
    evaluator_usage: EvaluatorUsage | None = None
    evidence_ids: Annotated[list[OpaqueId] | None, Field(max_length=200)] = None
    started_at: Timestamp
    completed_at: Timestamp
