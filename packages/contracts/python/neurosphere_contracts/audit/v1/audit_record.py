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
    StrictInt,
    StrictStr,
)

from ...actions.v1 import actor as actor_1
from ...actions.v1 import target_ref


class Uuid(RootModel[StrictStr]):
    root: Annotated[
        StrictStr,
        Field(pattern="^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"),
    ]


class UtcTimestamp(RootModel[StrictStr]):
    root: Annotated[
        StrictStr,
        Field(pattern="^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\\.[0-9]{1,9})?Z$"),
    ]
    """
    RFC 3339 timestamp in UTC (`Z` suffix required).
    """


class Sha256Hash(RootModel[StrictStr]):
    root: Annotated[StrictStr, Field(pattern="^sha256:[0-9a-f]{64}$")]


class Outcome(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    result: Literal["succeeded", "failed", "rolled_back"]
    """
    Final ActionState the intent reached; mirrors the terminal states of ../../actions/v1/action-state.schema.json.
    """
    verified: StrictBool
    """
    True only when the actual change on the target was read back and matched (no catalog-only pretend changes).
    """
    detail: Annotated[StrictStr | None, Field(max_length=1024)]


class Denial(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    code: Literal[
        "unauthorized",
        "forbidden",
        "capability_unavailable",
        "stale_version",
        "rate_limited",
        "invalid_schema",
        "dependency_transient",
    ]
    """
    Error taxonomy code. Mirrors errors/v1 (authoritative); `validate_denial_codes_match_error_taxonomy` in tests/contracts/test_error_taxonomy.py keeps the two lists equal.
    """
    reason: Annotated[StrictStr, Field(pattern="^[a-z][a-z0-9_]{0,63}$")]
    """
    Machine-readable reason, lowercase snake_case (for example `domain_out_of_scope`, `self_approval_prohibited`).
    """


class Subject(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    target: target_ref.TargetRef
    target_version: Annotated[StrictStr | None, Field(max_length=256)]
    """
    Version or ETag observed; null when unknown.
    """
    state_digest: Sha256Hash | None
    """
    sha256 of the captured target state; null when the state could not be read.
    """
    snapshot_ref: Annotated[StrictStr | None, Field(max_length=512, min_length=1)]
    """
    Pointer to the stored, redacted snapshot used for rollback evidence; never an inline body. Null when none was stored.
    """


class AuditRecord(BaseModel):
    """
    Append-only, hash-chained audit evidence (PRP.md section 3, PRD NS-06 'audit before/after'). Kinds: `before` (target state captured before a change), `after` (outcome and target state after), `denied` (a query, tool, export, push or action that authorization or policy refused). There is no update-capable field: no updated_at, modified_by, etag, version, status or deleted flag; corrections are new records. previous_hash is required for every record except the chain head (sequence 0), where it is null. Rules JSON Schema cannot express are checked by `validate_audit_chain` in tests/contracts/test_schemas.py: record_hash equals sha256 over the RFC 8785 (JCS) canonical form of the record without record_hash; within a chain_id, sequence is contiguous from 0 and each previous_hash equals the preceding record's record_hash.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    schema_version: Annotated[StrictStr, Field(pattern="^1\\.[0-9]+\\.[0-9]+$")]
    audit_id: Uuid
    """
    Server-assigned identifier of this record (lowercase UUID).
    """
    chain_id: Annotated[StrictStr, Field(pattern="^[a-z0-9][a-z0-9._-]{0,127}$")]
    """
    Identifier of the hash chain this record belongs to (for example one chain per domain cell).
    """
    sequence: Annotated[StrictInt, Field(ge=0)]
    """
    Zero-based position in the chain. 0 is the chain head.
    """
    previous_hash: Sha256Hash | None
    """
    record_hash of the preceding record in the chain. Null only for the chain head (sequence 0); required otherwise.
    """
    record_hash: Sha256Hash
    """
    sha256 over the JCS-canonical record excluding this field.
    """
    kind: Literal["before", "after", "denied"]
    recorded_at: UtcTimestamp
    """
    Server-assigned, immutable instant the record was appended.
    """
    actor: actor_1.Actor
    """
    Principal whose request produced this record.
    """
    scope_hash: Sha256Hash
    """
    scope_hash of the server-derived IdentityScope the request was evaluated under.
    """
    correlation_id: Annotated[StrictStr, Field(pattern="^[A-Za-z0-9._-]{1,128}$")]
    operation: Annotated[
        StrictStr,
        Field(max_length=128, pattern="^[a-z][a-z0-9_]*(\\.[a-z][a-z0-9_]*){0,7}$"),
    ]
    """
    Dotted lowercase operation name (for example `action.execute`, `graph.query`, `report.export`, `mcp.tool_call`).
    """
    channel: Literal["button", "chat", "rest", "mcp", "websocket", "worker"] | None
    """
    Channel the request arrived through; null for internal workers.
    """
    intent_id: Uuid | None
    """
    ActionIntent this record belongs to; null for non-action operations.
    """
    subject: Subject | None
    """
    Target and captured state. Required for before and after; null allowed for denied when no target was resolved.
    """
    outcome: Outcome | None
    """
    Result of the change. Required for after; null for before and denied.
    """
    denial: Denial | None
    """
    Why the request was refused. Required for denied; null otherwise.
    """
