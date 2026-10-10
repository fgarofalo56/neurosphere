# GENERATED - do not edit.
# Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
# Regenerate: python packages/contracts/scripts/generate.py
# Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
# pyright: reportAssignmentType=false, reportInvalidTypeForm=false

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    RootModel,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    constr,
)

from . import canonical_id


class CatalogCommon(RootModel[Any]):
    root: Annotated[Any, Field(title="CatalogCommon")]
    """
    Shared definitions for catalog v1. Definition library only: it declares no root instance shape and is never validated against directly, so it has no examples.
    """


class SchemaVersion(RootModel[StrictStr]):
    root: Annotated[StrictStr, Field(pattern="^1\\.(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)$")]
    """
    Contract version of the document; major 1 for every catalog v1 schema.
    """


class CanonicalId(RootModel[canonical_id.CanonicalId]):
    root: canonical_id.CanonicalId


class Timestamp(RootModel[StrictStr]):
    root: Annotated[
        StrictStr,
        Field(pattern="^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\\.[0-9]{1,9})?Z$"),
    ]
    """
    RFC 3339 timestamp in UTC (Z suffix required; no offsets).
    """


class Date(RootModel[StrictStr]):
    root: Annotated[StrictStr, Field(pattern="^[0-9]{4}-[0-9]{2}-[0-9]{2}$")]
    """
    RFC 3339 full-date.
    """


class EntityVersion(RootModel[StrictInt]):
    root: Annotated[StrictInt, Field(ge=1)]
    """
    Monotonic document version, incremented on every accepted write.
    """


class Etag(RootModel[StrictStr]):
    root: Annotated[StrictStr, Field(max_length=256, min_length=1)]
    """
    Opaque optimistic-concurrency token. A mismatch on write returns the stale_version error.
    """


class Cloud(RootModel[Literal["commercial", "government"]]):
    root: Literal["commercial", "government"]
    """
    Sovereign cloud boundary. Government data is never bridged to Commercial.
    """


class CustomerId(RootModel[StrictStr]):
    root: Annotated[StrictStr, Field(max_length=128, pattern="^[a-z0-9._-]+$")]
    """
    Customer segment of the canonical ID grammar.
    """


class Token(RootModel[StrictStr]):
    root: Annotated[StrictStr, Field(max_length=128, pattern="^[a-z0-9][a-z0-9._-]*$")]
    """
    Lowercase identifier token (source IDs, platforms, providers, kinds).
    """


class LifecycleStatus(RootModel[Literal["draft", "active", "deprecated", "retired"]]):
    root: Literal["draft", "active", "deprecated", "retired"]
    """
    Entity lifecycle state.
    """


class Classification(
    RootModel[Literal["public", "internal", "confidential", "restricted", "unknown"]]
):
    root: Literal["public", "internal", "confidential", "restricted", "unknown"] = "unknown"
    """
    Data classification label; unknown when not yet classified.
    """


class DisplayName(RootModel[StrictStr]):
    root: Annotated[
        StrictStr,
        Field(max_length=256, min_length=1, pattern="^[^\\u0000-\\u001f\\u007f]+$"),
    ]
    """
    Human-readable label for a non-person entity. Never a person's name.
    """


class Attributes(
    RootModel[
        dict[
            constr(pattern=r"^[a-z][a-z0-9_]{0,63}$", strict=True),
            constr(max_length=1024, strict=True) | StrictFloat | StrictBool | None,
        ]
    ]
):
    root: dict[
        constr(pattern=r"^[a-z][a-z0-9_]{0,63}$", strict=True),
        constr(max_length=1024, strict=True) | StrictFloat | StrictBool | None,
    ]
    """
    Extension point: scalar values only (string, number, boolean, null); keys are lowercase snake_case. Nested objects and arrays are rejected.
    """


class EvidenceId(RootModel[StrictStr]):
    root: Annotated[StrictStr, Field(pattern="^[A-Za-z0-9][A-Za-z0-9._:/=-]{0,255}$")]
    """
    Reference to an evidence record (trace, span, access log, audit record or steward decision). A pointer, never the evidence payload.
    """


class RelationType(
    RootModel[
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
    ]
):
    root: Literal[
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
    """
    Relation name in wire form (lowercase snake_case of INVOKES, DELEGATES_TO, USES_MODEL, READS, WRITES, GROUNDED_BY, OWNED_BY, DEPENDS_ON, SUPERSEDES).
    """


class EntityType(
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
    """
    Catalog entity type; equals the type segment of the entity's canonical ID.
    """


class RelationStatus(RootModel[Literal["asserted", "inferred", "curated"]]):
    root: Literal["asserted", "inferred", "curated"]
    """
    asserted = declared by an authorized source; inferred = derived from telemetry or similarity; curated = accepted, overridden or locked by a domain steward.
    """


class PersonId(RootModel[StrictStr]):
    root: Annotated[
        StrictStr,
        Field(
            max_length=512,
            pattern="^(commercial|government):[a-z0-9._-]+:[a-z0-9._-]+:person:[a-z0-9._/=-]+$",
        ),
    ]
    """
    Pseudonymous principal reference. Canonical ID (canonical_id.schema.json) whose type segment is 'person'.
    """


class DomainId(RootModel[StrictStr]):
    root: Annotated[
        StrictStr,
        Field(
            max_length=512,
            pattern="^(commercial|government):[a-z0-9._-]+:[a-z0-9._-]+:domain:[a-z0-9._/=-]+$",
        ),
    ]
    """
    Owning domain; authorization scope anchor. Canonical ID (canonical_id.schema.json) whose type segment is 'domain'.
    """


class ConnectorVersion(RootModel[StrictStr]):
    root: Annotated[StrictStr, Field(max_length=64)] = None


class InferenceVersion(RootModel[StrictStr]):
    root: Annotated[StrictStr, Field(max_length=64)] = None
    """
    Version of the inference rule or model when method is inferred.
    """


class Provenance(BaseModel):
    """
    Where an edge or alias came from.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    method: Literal[
        "trace_observation",
        "observed_access",
        "declared",
        "embedding_similarity",
        "steward_curation",
        "import",
        "unknown",
    ]
    source_id: Token
    """
    Connector or source that produced the observation.
    """
    connector_version: ConnectorVersion | None = None
    inference_version: InferenceVersion | None = None
    """
    Version of the inference rule or model when method is inferred.
    """
    recorded_at: Timestamp


class Validity(BaseModel):
    """
    Validity interval. valid_to null means open-ended. Python validator validate_validity_interval enforces valid_from < valid_to.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    valid_from: Timestamp
    valid_to: Timestamp | None = None


class Reason(RootModel[StrictStr]):
    root: Annotated[StrictStr, Field(max_length=2000, min_length=1)] = None


class Lock(BaseModel):
    """
    Steward lock. Locks change presented lineage, never retained observations; re-inference must respect them. A lock (locked=true) requires reason, expiry and actor. Python validator validate_lock_expiry_after_decision enforces expiry later than the decision time.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    locked: StrictBool
    reason: Reason | None = None
    expiry: Timestamp | None = None
    actor: PersonId | None = None


class OverrideId(RootModel[StrictStr]):
    root: Annotated[
        StrictStr,
        Field(
            max_length=512,
            pattern="^(commercial|government):[a-z0-9._-]+:[a-z0-9._-]+:edge_override:[a-z0-9._/=-]+$",
        ),
    ] = None
    """
    Override document that produced this state. Canonical ID (canonical_id.schema.json) whose type segment is 'edge_override'.
    """


class Curation(BaseModel):
    """
    Latest steward decision on an edge (full history lives in the audit log).
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    decision: Literal["accepted", "rejected", "overridden"]
    decided_by: PersonId
    decided_at: Timestamp
    reason: Annotated[StrictStr, Field(max_length=2000, min_length=1)]
    override_id: OverrideId | None = None
    review_item_id: EvidenceId | None = None
