# GENERATED - do not edit.
# Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
# Regenerate: python packages/contracts/scripts/generate.py
# Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
# pyright: reportAssignmentType=false, reportInvalidTypeForm=false

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr

from ...actions.v1 import target_ref
from ...admin.v1 import common as common_1
from ...audit.v1 import audit_record
from ...catalog.v1 import common
from . import policy_definition


class Resolution(BaseModel):
    """
    How it was resolved. Null while open.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    resolved_at: common.Timestamp
    reason_code: common_1.ReasonCode
    intent_id: audit_record.Uuid | None
    """
    Action intent, when the fix went through one.
    """
    audit_id: audit_record.Uuid | None
    """
    Audit record of the resolution.
    """


class PolicyViolationEvidence(BaseModel):
    """
    A reference to what showed the breach.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    evidence_kind: Literal[
        "catalog_entity",
        "relation",
        "interaction_record",
        "aggregate_window",
        "audit_record",
        "telemetry_event",
        "budget_status",
    ]
    """
    What `ref` points at. Open-ended: readers must tolerate unknown values.
    """
    ref: Annotated[
        StrictStr,
        Field(max_length=512, min_length=1, pattern="^[A-Za-z0-9._:/=-]{1,512}$"),
    ]
    """
    Opaque reference id or canonical id.
    """
    observed_at: common.Timestamp


class PolicyViolation(BaseModel):
    """
    One deduplicated finding that an entity breaks a rule (PRP-99; container policy_violations). Evidence is references only: no content, no query text.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    schema_version: common.SchemaVersion
    violation_id: audit_record.Uuid
    cloud: common.Cloud
    customer_id: common.CustomerId
    domain_id: common.DomainId
    policy_id: common_1.Slug
    policy_version: Annotated[StrictInt, Field(ge=1)]
    rule_id: common_1.Slug
    rule_kind: policy_definition.PolicyRuleKind
    severity: policy_definition.PolicySeverity
    subject: target_ref.TargetRef
    """
    The entity in violation.
    """
    status: Literal["open", "excepted", "resolved", "superseded"]
    dedup_key: Annotated[StrictStr, Field(pattern="^sha256:[a-f0-9]{64}$")]
    """
    Digest of policy, rule and subject so one breach is one violation.
    """
    first_seen_at: common.Timestamp
    last_seen_at: common.Timestamp
    occurrence_count: Annotated[StrictInt, Field(ge=1)]
    evidence: Annotated[list[PolicyViolationEvidence], Field(max_length=50, min_length=1)]
    exception_id: audit_record.Uuid | None = None
    """
    Exception that covers it. Null when none.
    """
    resolution: Resolution | None = None
    """
    How it was resolved. Null while open.
    """
    correlation_id: Annotated[StrictStr, Field(pattern="^[A-Za-z0-9._-]{1,128}$")]
    evaluator_version: Annotated[
        StrictStr, Field(max_length=32, pattern="^[0-9]+\\.[0-9]+\\.[0-9]+$")
    ]
