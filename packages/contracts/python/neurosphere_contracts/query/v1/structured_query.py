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

from . import budget as budget_1
from . import page


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


class Keyword(RootModel[StrictStr]):
    root: Annotated[StrictStr, Field(pattern="^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")]
    """
    Enumerated-style value: no whitespace, quotes, brackets, operators or control characters, so it cannot carry query text.
    """


class Decimal(RootModel[StrictStr]):
    root: Annotated[StrictStr, Field(pattern="^-?(0|[1-9][0-9]*)(\\.[0-9]{1,12})?$")]
    """
    Money amount as a decimal string (no floats).
    """


class CatalogEntity(
    RootModel[
        Literal[
            "person",
            "agent",
            "agent_version",
            "model_deployment",
            "grounding_source",
            "tool",
            "service",
            "domain",
            "owner",
            "policy",
            "recommendation",
            "run_reference",
        ]
    ]
):
    root: Literal[
        "person",
        "agent",
        "agent_version",
        "model_deployment",
        "grounding_source",
        "tool",
        "service",
        "domain",
        "owner",
        "policy",
        "recommendation",
        "run_reference",
    ]


class Entity(
    RootModel[CatalogEntity | Literal["telemetry_event", "cost_record", "evaluation_result"]]
):
    root: CatalogEntity | Literal["telemetry_event", "cost_record", "evaluation_result"]


class IdField(
    RootModel[
        Literal[
            "id",
            "agent_id",
            "agent_version_id",
            "model_deployment_id",
            "owner_id",
            "domain_id",
            "source_id",
            "tool_id",
            "service_id",
            "policy_id",
            "subject_id",
            "principal_id",
        ]
    ]
):
    root: Literal[
        "id",
        "agent_id",
        "agent_version_id",
        "model_deployment_id",
        "owner_id",
        "domain_id",
        "source_id",
        "tool_id",
        "service_id",
        "policy_id",
        "subject_id",
        "principal_id",
    ]


class KeywordField(
    RootModel[
        Literal[
            "cloud",
            "environment",
            "provider",
            "model_name",
            "model_version",
            "lifecycle_status",
            "outcome",
            "status",
            "kind",
            "classification",
            "span_kind",
            "relation_status",
            "observation_source",
            "currency",
        ]
    ]
):
    root: Literal[
        "cloud",
        "environment",
        "provider",
        "model_name",
        "model_version",
        "lifecycle_status",
        "outcome",
        "status",
        "kind",
        "classification",
        "span_kind",
        "relation_status",
        "observation_source",
        "currency",
    ]


class NumberField(
    RootModel[
        Literal[
            "confidence",
            "duration_ms",
            "input_tokens",
            "output_tokens",
            "cached_tokens",
            "reasoning_tokens",
            "total_tokens",
            "retries",
            "error_rate",
            "latency_p50_ms",
            "latency_p95_ms",
            "request_count",
            "score",
        ]
    ]
):
    root: Literal[
        "confidence",
        "duration_ms",
        "input_tokens",
        "output_tokens",
        "cached_tokens",
        "reasoning_tokens",
        "total_tokens",
        "retries",
        "error_rate",
        "latency_p50_ms",
        "latency_p95_ms",
        "request_count",
        "score",
    ]


class MoneyField(RootModel[Literal["amount", "baseline_amount", "projected_amount"]]):
    root: Literal["amount", "baseline_amount", "projected_amount"]


class TimeField(
    RootModel[
        Literal[
            "event_time",
            "ingestion_time",
            "first_observed",
            "last_observed",
            "created_at",
            "updated_at",
            "completed_at",
        ]
    ]
):
    root: Literal[
        "event_time",
        "ingestion_time",
        "first_observed",
        "last_observed",
        "created_at",
        "updated_at",
        "completed_at",
    ]


class BooleanField(RootModel[Literal["advisory", "locked", "has_owner"]]):
    root: Literal["advisory", "locked", "has_owner"]


class AnyField(
    RootModel[IdField | KeywordField | NumberField | MoneyField | TimeField | BooleanField]
):
    root: IdField | KeywordField | NumberField | MoneyField | TimeField | BooleanField


class GroupField(RootModel[IdField | KeywordField]):
    root: IdField | KeywordField


class Alias(RootModel[StrictStr]):
    root: Annotated[StrictStr, Field(pattern="^[a-z][a-z0-9_]{0,63}$")]


class TimeRange(BaseModel):
    """
    Half-open interval [start, end). start < end is checked by tests/contracts/validators.py::check_time_range_order.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    start: Timestamp
    end: Timestamp


class IdFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    field: IdField
    op: Literal["eq", "ne", "in", "not_in"]
    value: CanonicalId | None = None
    values: Annotated[list[CanonicalId] | None, Field(max_length=100, min_length=1)] = None


class KeywordFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    field: KeywordField
    op: Literal["eq", "ne", "in", "not_in", "prefix"]
    value: Keyword | None = None
    values: Annotated[list[Keyword] | None, Field(max_length=100, min_length=1)] = None


class NumberFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    field: NumberField
    op: Literal["eq", "ne", "gt", "gte", "lt", "lte", "between"]
    value: StrictFloat | None = None
    values: Annotated[list[StrictFloat] | None, Field(max_length=2, min_length=2)] = None


class MoneyFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    field: MoneyField
    op: Literal["gt", "gte", "lt", "lte", "between"]
    value: Decimal | None = None
    values: Annotated[list[Decimal] | None, Field(max_length=2, min_length=2)] = None


class TimeFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    field: TimeField
    op: Literal["gt", "gte", "lt", "lte", "between"]
    value: Timestamp | None = None
    values: Annotated[list[Timestamp] | None, Field(max_length=2, min_length=2)] = None


class BooleanFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    field: BooleanField
    op: Literal["eq"]
    value: StrictBool


class Aggregation(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    op: Literal["count", "count_distinct", "sum", "avg", "min", "max", "p50", "p95", "p99"]
    field: AnyField | None = None
    as_: Annotated[Alias, Field(alias="as")]


class Traversal(BaseModel):
    """
    Bounded traversal; depth and node/edge caps come from budget.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    start_ids: Annotated[list[CanonicalId], Field(max_length=50, min_length=1)]
    relations: Annotated[
        list[
            Literal[
                "invokes",
                "delegates_to",
                "uses_model",
                "reads",
                "writes",
                "grounded_by",
                "owned_by",
                "depends_on",
                "supersedes",
            ]
        ],
        Field(max_length=9, min_length=1),
    ]
    """
    NS-02 relation names in lowercase snake_case.
    """
    direction: Literal["outgoing", "incoming", "both"]


class SortKey(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    field: IdField | KeywordField | NumberField | MoneyField | TimeField | Alias
    direction: Literal["asc", "desc"]


class Filter(
    RootModel[IdFilter | KeywordFilter | NumberFilter | MoneyFilter | TimeFilter | BooleanFilter]
):
    root: IdFilter | KeywordFilter | NumberFilter | MoneyFilter | TimeFilter | BooleanFilter


class StructuredQuery(BaseModel):
    """
    Request-side structured query used by REST, copilot tools and MCP (PRP.md section 3, NS-06). It carries structured allowlisted filters only, never executable query text: there is no free-text field, every field name is an allowlisted enum, every operator is typed per field kind, and string values are charset-restricted keywords or canonical IDs that the server binds as parameters (never concatenated into SQL/Cypher/KQL). Budgets (timeout_ms, limit, max_depth) are mandatory. Authorization comes only from the server-derived IdentityScope, which this schema never references: a domain_id or customer filter can only narrow results inside that scope. Rules JSON Schema cannot express: field applicability per entity is checked by tests/contracts/validators.py::check_structured_query_field_applicability; time_range.start < time_range.end by tests/contracts/validators.py::check_time_range_order; between bounds lo <= hi by tests/contracts/validators.py::check_between_order.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    schema_version: SchemaVersion
    operation: Literal["list", "aggregate", "neighbors", "impact_paths"]
    """
    list and aggregate return rows; neighbors and impact_paths are bounded graph traversals from traversal.start_ids.
    """
    entity: Entity
    """
    Entity type returned (list, aggregate) or of the start nodes (neighbors, impact_paths).
    """
    filters: Annotated[list[Filter] | None, Field(max_length=32)] = None
    """
    Conjunction (AND) of typed filters.
    """
    fields: Annotated[list[AnyField] | None, Field(max_length=32)] = None
    """
    Optional projection; allowlisted field names only.
    """
    sort: Annotated[list[SortKey] | None, Field(max_length=3)] = None
    time_range: TimeRange | None = None
    group_by: Annotated[list[GroupField] | None, Field(max_length=3)] = None
    time_bucket: Literal["minute", "five_minutes", "hour", "day", "week"] | None = None
    aggregations: Annotated[list[Aggregation] | None, Field(max_length=8, min_length=1)] = None
    traversal: Traversal | None = None
    budget: budget_1.Budget
    cursor: page.Cursor | None = None
