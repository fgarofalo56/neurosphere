# GENERATED - do not edit.
# Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
# Regenerate: python packages/contracts/scripts/generate.py
# Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
# pyright: reportAssignmentType=false, reportInvalidTypeForm=false

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel, StrictBool, StrictStr

from . import action_state, target_ref
from . import actor as actor_1


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
    """
    Lowercase hex SHA-256 digest with algorithm prefix.
    """


class CorrelationId(RootModel[StrictStr]):
    root: Annotated[StrictStr, Field(pattern="^[A-Za-z0-9._-]{1,128}$")]


class PatchOperation(BaseModel):
    """
    One RFC 6902 operation. add/replace/test require `value`; move/copy require `from`; remove takes neither.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    op: Literal["add", "remove", "replace", "move", "copy", "test"]
    path: Annotated[StrictStr, Field(max_length=1024, pattern="^(/([^~/]|~[01])*)*$")]
    """
    RFC 6901 JSON Pointer.
    """
    from_: Annotated[
        StrictStr | None,
        Field(alias="from", max_length=1024, pattern="^(/([^~/]|~[01])*)*$"),
    ] = None
    """
    RFC 6901 JSON Pointer source for move/copy.
    """
    value: Any | None = None
    """
    New value (any JSON) for add/replace/test.
    """


class EvidenceId(RootModel[StrictStr]):
    root: Annotated[StrictStr, Field(max_length=256, min_length=1)]


class PrerequisiteResult(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    check_id: Annotated[StrictStr, Field(pattern="^[a-z][a-z0-9_]{0,63}$")]
    """
    Prerequisite check name, lowercase snake_case (for example `actor_permission`, `write_connector_supported`).
    """
    status: Literal["passed", "failed", "warning", "not_applicable", "unknown"]
    """
    `unknown` when the check could not be evaluated; never coerced to passed.
    """
    detail: Annotated[StrictStr | None, Field(max_length=1024)]
    """
    Short human-readable explanation; null when none.
    """
    evaluated_at: UtcTimestamp
    evidence_ids: list[EvidenceId]


class EvidenceRef(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    evidence_id: Annotated[StrictStr, Field(max_length=256, min_length=1)]
    kind: Literal[
        "recommendation",
        "evaluation_result",
        "telemetry_query",
        "cost_record",
        "catalog_entity",
        "policy",
        "document",
    ]
    ref: Annotated[StrictStr, Field(max_length=512, min_length=1)]
    """
    Pointer to the evidence (canonical ID or stored-document ID). Never an inline body.
    """
    observed_at: UtcTimestamp | None
    """
    When the evidence was observed; null when unknown.
    """


class ProposedDiff(BaseModel):
    """
    RFC 6902 JSON Patch against the target document at target_version. `value` members are opaque target data validated by the write connector and must never hold secret material (use vault references).
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    format: Literal["json_patch"]
    """
    Diff encoding. Only RFC 6902 JSON Patch in v1.
    """
    operations: Annotated[list[PatchOperation], Field(max_length=256, min_length=1)]


class ActionIntent(BaseModel):
    """
    Durable intent executed by the single action executor shared by button, chat, REST and MCP (PRP.md section 3, PRD NS-06). The intent binds actor, target, target_version, proposed_diff and confirmation expiry into confirmation_hash, defined field-by-field in ./confirmation-hash.json, so every channel computes the same value. Legal state changes are the allowlist in ./transitions.json; enforcement belongs to PRP-17. Rules JSON Schema cannot express are checked by Python validators in tests/contracts/test_action_transitions.py: `validate_confirmation_hash` (confirmation_hash equals the recomputed hash), `validate_state_transition` (every state change is an allowlisted (from, to) pair) and `validate_intent_timestamps` (created_at <= state_changed_at, and confirmation_expires_at > created_at).
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    schema_version: Annotated[StrictStr, Field(pattern="^1\\.[0-9]+\\.[0-9]+$")]
    """
    Contract version of this document; major must match the v1 directory.
    """
    intent_id: Uuid
    """
    Server-assigned identifier of this intent (lowercase UUID).
    """
    action_kind: Annotated[StrictStr, Field(pattern="^[a-z][a-z0-9_]{0,63}$")]
    """
    Kind of governed action, lowercase snake_case (for example `model_swap`, `budget_cap_change`). Kinds the target has no supported write connector for are advisory and never reach `executing`.
    """
    actor: actor_1.Actor
    """
    Principal that requested the action. Hashed into confirmation_hash.
    """
    target: target_ref.TargetRef
    """
    Resource the action changes. Hashed into confirmation_hash.
    """
    target_version: Annotated[StrictStr, Field(max_length=256, min_length=1)]
    """
    Exact version or ETag of the target the diff was computed against. Rechecked at execution; a mismatch fails with error code `stale_version`. Hashed into confirmation_hash.
    """
    proposed_diff: ProposedDiff
    """
    Exact change shown to the user for confirmation. Hashed into confirmation_hash.
    """
    prerequisite_results: list[PrerequisiteResult]
    """
    Results of prerequisite checks evaluated during validation (permission, policy, connector support, target health, budget).
    """
    evidence: list[EvidenceRef]
    """
    Evidence the action is based on (recommendation, evaluation, telemetry or cost references). Not hashed.
    """
    confirmation_hash: Sha256Hash | None
    """
    SHA-256 over exactly these fields: target, target_version, proposed_diff, confirmation_expires_at, actor; canonicalized with RFC 8785 (JCS) as specified in ./confirmation-hash.json. Excludes channel, idempotency_key, state and evidence so button, chat, REST and MCP produce the same value. Null until the intent reaches awaiting_confirmation. Python validator: `validate_confirmation_hash`.
    """
    confirmation_expires_at: UtcTimestamp | None
    """
    Expiry of the confirmation; hashed. After this instant the intent may only move to `expired`. Null until the intent reaches awaiting_confirmation.
    """
    idempotency_key: Annotated[StrictStr, Field(pattern="^[A-Za-z0-9._:-]{16,128}$")]
    """
    Required on every intent. Replays with the same key return the original intent and result instead of executing twice.
    """
    channel: Literal["button", "chat", "rest", "mcp"]
    """
    Channel the intent arrived through. Not hashed: the same intent from any channel has the same confirmation_hash.
    """
    state: action_state.ActionState
    """
    Current lifecycle state.
    """
    status_reason: Annotated[StrictStr | None, Field(pattern="^[a-z][a-z0-9_]{0,63}$")]
    """
    Machine-readable reason for the current state, lowercase snake_case (for example `approval_rejected`, `stale_version`, `confirmation_expired`). Required non-null for failed, rolled_back and expired; null otherwise allowed.
    """
    dry_run: StrictBool
    """
    True when the executor must plan and verify prerequisites without applying the change.
    """
    correlation_id: CorrelationId
    """
    Correlation ID propagated to audit records and error responses.
    """
    created_at: UtcTimestamp
    """
    When the intent was drafted.
    """
    state_changed_at: UtcTimestamp
    """
    When `state` last changed. History lives in the append-only audit chain, not here.
    """
