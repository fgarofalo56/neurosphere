# GENERATED - do not edit.
# Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
# Regenerate: python packages/contracts/scripts/generate.py
# Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
# pyright: reportAssignmentType=false, reportInvalidTypeForm=false

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from ...actions.v1 import target_ref
from ...admin.v1 import common as common_1
from ...audit.v1 import audit_record
from ...catalog.v1 import common


class PolicyException(BaseModel):
    """
    A time-boxed exception to one rule for one subject (PRP-99; container policy_exceptions). expires_at is required and at most 365 days after requested_at (Python validator check_policy_exception_window in tests/contracts/validators.py).
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    schema_version: common.SchemaVersion
    exception_id: audit_record.Uuid
    cloud: common.Cloud
    customer_id: common.CustomerId
    domain_id: common.DomainId
    policy_id: common_1.Slug
    rule_id: common_1.Slug
    subject: target_ref.TargetRef
    """
    The entity excepted.
    """
    violation_id: audit_record.Uuid | None = None
    """
    Violation it answers. Null when requested ahead of one.
    """
    status: Literal["requested", "approved", "rejected", "expired", "revoked"]
    reason_code: common_1.ReasonCode
    requested_by: common_1.PrincipalId
    requested_at: common.Timestamp
    review_item_id: common_1.RecordId | None = None
    """
    HITL review item that decides it.
    """
    decided_by: common_1.PrincipalId | None = None
    """
    Reviewer.
    """
    decided_at: common.Timestamp | None = None
    """
    When decided.
    """
    expires_at: common.Timestamp
    """
    When the exception ends. Required.
    """
    audit_id: audit_record.Uuid | None = None
    """
    Audit record of the decision.
    """
