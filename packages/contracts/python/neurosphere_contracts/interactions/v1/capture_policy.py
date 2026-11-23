# GENERATED - do not edit.
# Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
# Regenerate: python packages/contracts/scripts/generate.py
# Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
# pyright: reportAssignmentType=false, reportInvalidTypeForm=false

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt, StrictStr

from ...admin.v1 import common
from ...audit.v1 import audit_record
from ...catalog.v1 import common as common_1
from . import detection_finding


class Sampling(BaseModel):
    """
    Sampling limits.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    rate: Annotated[StrictFloat, Field(gt=0.0, le=1.0)]
    """
    Fraction of interactions captured, above 0 up to 1.
    """
    max_per_minute: Annotated[StrictInt, Field(ge=1, le=6000)]


class CapturePolicy(BaseModel):
    """
    Opt-in capture policy per domain and source (PRP-99; container interaction_capture_policies, declared by PRP-102). Capture is off unless an active policy exists. kept_categories can never hold a credential category and an active policy requires approved_intent_id and approved_audit_id; both rules are JSON Schema (`not`, if/then) that Pydantic ignores (ADR-0004), so consumers validate against the JSON Schema.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    schema_version: Annotated[StrictStr, Field(pattern="^1\\.(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)$")]
    """
    Contract version of this document, major 1 with additive minor revisions.
    """
    capture_policy_id: common.Slug
    """
    Capture policy id (slug).
    """
    version: Annotated[StrictInt, Field(ge=1)]
    """
    Policy version, increments on every change.
    """
    previous_version: Annotated[StrictInt | None, Field(ge=1)] = None
    """
    Version this one replaces. Null for the first.
    """
    display_name: common.DisplayName
    """
    Console label.
    """
    cloud: common_1.Cloud
    """
    Sovereign cloud boundary.
    """
    customer_id: common_1.CustomerId
    """
    Customer segment.
    """
    domain_id: common_1.DomainId
    """
    Domain the policy applies to.
    """
    source_ids: Annotated[list[common_1.Token], Field(max_length=64, min_length=1)]
    """
    Sources capture is turned on for.
    """
    parts: Annotated[list[detection_finding.ContentPartKind], Field(max_length=5, min_length=1)]
    """
    Parts that may be captured.
    """
    detector_set_version: Annotated[StrictStr, Field(pattern="^[a-z0-9][a-z0-9._-]{0,63}$")]
    """
    Deterministic detector set that redacts.
    """
    customer_dictionary_ids: Annotated[
        list[common.Slug] | None, Field(max_length=16, validate_default=True)
    ] = []
    """
    Customer dictionaries applied.
    """
    redaction_mode: Literal["redact_all_detections", "redact_listed"] | None = (
        "redact_all_detections"
    )
    """
    `redact_all_detections` (default, GD-4) or `redact_listed`.
    """
    kept_categories: Annotated[
        list[detection_finding.DetectedCategory] | None, Field(validate_default=True)
    ] = []
    """
    Non-credential categories kept as written. Never a credential category (CredentialCategory): credentials are always redacted.
    """
    sampling: Sampling
    """
    Sampling limits.
    """
    max_part_chars: Annotated[StrictInt | None, Field(ge=1, le=32768)] = 8192
    """
    Characters kept per part; the rest is truncated.
    """
    retention_class: Annotated[StrictStr, Field(pattern="^[a-z0-9][a-z0-9._-]{0,63}$")]
    """
    Retention class (slug).
    """
    retention_days: Annotated[StrictInt | None, Field(ge=1, le=365)] = 90
    """
    Days captured content is kept (GD-5); legal hold overrides.
    """
    state: Literal["proposed", "active", "suspended", "retired"]
    """
    `proposed` until an approved capture_policy_change activates it.
    """
    approved_intent_id: audit_record.Uuid | None = None
    """
    Approved action intent. Required (non-null) when active.
    """
    approved_audit_id: audit_record.Uuid | None = None
    """
    Audit record of the approval. Required (non-null) when active.
    """
    effective_from: common_1.Timestamp | None = None
    """
    When the policy took effect. Null until activated.
    """
