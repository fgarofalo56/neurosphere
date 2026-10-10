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
    StrictBool,
    StrictFloat,
    StrictStr,
)


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


class Date(RootModel[StrictStr]):
    root: Annotated[StrictStr, Field(pattern="^[0-9]{4}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])$")]
    """
    RFC 3339 full-date (UTC calendar date).
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


class Currency(RootModel[StrictStr]):
    root: Annotated[StrictStr, Field(pattern="^[A-Z]{3}$")]
    """
    ISO 4217 alphabetic code.
    """


class TimeRange(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    start: Timestamp
    end: Timestamp


class ObservedFraction(RootModel[StrictFloat]):
    root: Annotated[StrictFloat, Field(ge=0.0, le=1.0)]


class SamplingRate(RootModel[StrictFloat]):
    root: Annotated[StrictFloat, Field(gt=0.0, le=1.0)]


class Coverage(BaseModel):
    """
    How much of the relevant population the evidence observed. observed_fraction null means unknown, never 0.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    method: Literal["full", "sampled", "partial", "unknown"]
    observed_fraction: ObservedFraction | None
    sampling_rate: SamplingRate | None = None
    missing_source_ids: Annotated[list[CanonicalId] | None, Field(max_length=100)] = None


class Uncertainty(BaseModel):
    """
    Uncertainty of the score or estimate. not_estimable is the honest value on cold start; it carries no bounds.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    method: Literal[
        "confidence_interval", "credible_interval", "bootstrap", "rule_bound", "not_estimable"
    ]
    lower: StrictFloat | None = None
    upper: StrictFloat | None = None
    level: Annotated[StrictFloat | None, Field(gt=0.0, lt=1.0)] = None


class Prerequisite(BaseModel):
    """
    A precondition for acting on the recommendation (NS-03: compatibility, quality regression, cost comparison, staged rollout, rollback).
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    kind: Literal[
        "capability_compatibility",
        "context_compatibility",
        "tool_compatibility",
        "quality_regression_test",
        "cost_comparison",
        "staged_rollout_plan",
        "rollback_plan",
        "owner_consent",
        "approval",
        "write_connector_available",
    ]
    status: Literal["met", "unmet", "unknown"]
    evidence_ids: Annotated[list[OpaqueId] | None, Field(max_length=50)] = None


class ProjectedEstimate(BaseModel):
    """
    Projected cost effect. Always an estimate, always cites price_version (estimated spend without a price version is invalid, matching CostRecord).
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    estimate_kind: Literal["estimated"]
    period: Literal["monthly", "annual", "evidence_window"]
    baseline_amount: Decimal
    projected_amount: Decimal
    lower_amount: Decimal | None = None
    upper_amount: Decimal | None = None
    currency: Currency
    price_version: Version
    price_effective_date: Date | None = None


class Owner(BaseModel):
    """
    Owner of the subject. resolution unresolved means owner_id is null (owner unknown, routed to stewards).
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    resolution: Literal["assigned", "inferred", "unresolved"]
    owner_id: CanonicalId | None


class Generator(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    generator_id: OpaqueId
    generator_version: Version


class Recommendation(BaseModel):
    """
    An evidence-backed suggestion (NS-03): kind, evidence window, coverage, uncertainty, prerequisites, projected estimate and owner. Recommendations are insights, not actions: executing one goes through the shared action executor (schemas/actions/v1). Cold start uses bounded rules rather than fabricated scores: when evidence_status is insufficient_evidence, score must be absent; when score is absent, evidence_status must be insufficient_evidence. A projected_estimate always cites price_version. candidate_duplicate is always advisory (consolidation review, never an automatic merge). Unknown numeric values are null, never 0. Rules JSON Schema cannot express: evidence_window.start < evidence_window.end (tests/contracts/validators.py::check_time_range_order); uncertainty.lower <= score <= uncertainty.upper when both present (tests/contracts/validators.py::check_recommendation_score_interval); every subject_ids and owner_id belongs to the same cloud and customer as the document (tests/contracts/validators.py::check_recommendation_same_boundary).
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    schema_version: SchemaVersion
    recommendation_id: CanonicalId
    cloud: Literal["commercial", "government"]
    customer_id: Annotated[StrictStr, Field(pattern="^[a-z0-9._-]{1,128}$")]
    domain_id: CanonicalId
    """
    Canonical Domain ID used for scope filtering against the server-derived IdentityScope.
    """
    kind: Literal[
        "cost_spike",
        "latency_degradation",
        "error_rate_degradation",
        "unused_agent",
        "candidate_duplicate",
        "model_right_sizing",
    ]
    subject_ids: Annotated[list[CanonicalId], Field(max_length=50, min_length=1)]
    """
    Canonical IDs of the agents, versions or deployments the recommendation is about.
    """
    method: Literal["rule", "statistical", "ml"]
    """
    rule for cold-start bounded rules; statistical or ml when enough history exists.
    """
    generator: Generator | None = None
    evidence_status: Literal["sufficient", "insufficient_evidence"]
    score: Annotated[StrictFloat | None, Field(ge=0.0, le=1.0)] = None
    """
    Confidence in [0, 1]. Absent on cold start (insufficient_evidence); never fabricated.
    """
    evidence_window: TimeRange
    evidence_ids: Annotated[list[OpaqueId], Field(max_length=200)]
    coverage: Coverage
    uncertainty: Uncertainty
    prerequisites: Annotated[list[Prerequisite], Field(max_length=20)]
    projected_estimate: ProjectedEstimate | None = None
    owner: Owner
    advisory: StrictBool
    """
    True when no supported write connector can execute the change; the recommendation is then advisory only and never a catalog-only pretend change.
    """
    created_at: Timestamp
    expires_at: Timestamp | None = None
