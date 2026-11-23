# GENERATED - do not edit.
# Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
# Regenerate: python packages/contracts/scripts/generate.py
# Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
# pyright: reportAssignmentType=false, reportInvalidTypeForm=false

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel

from ...actions.v1 import target_ref
from ...admin.v1 import common as common_1
from ...audit.v1 import audit_record
from ...catalog.v1 import common
from . import policy_definition


class EnforcementPoint(
    RootModel[
        Literal["gateway", "tool_call", "mcp_server", "mcp_client", "sdk", "budget", "registration"]
    ]
):
    root: Annotated[
        Literal[
            "gateway", "tool_call", "mcp_server", "mcp_client", "sdk", "budget", "registration"
        ],
        Field(title="EnforcementPoint"),
    ]
    """
    Where a decision is enforced; open-ended: readers must tolerate unknown values.
    """


class EnforcementBinding(BaseModel):
    """
    Binds a policy to an enforcement point and a mode (PRP-99; body of admin_kind enforcement_binding). mode defaults to audit (GD-7); enforce is set only by an approved enforcement_mode_change action. A null target means every target of that point in the domain.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    schema_version: common.SchemaVersion
    binding_id: common_1.Slug
    """
    Binding id (slug).
    """
    cloud: common.Cloud
    customer_id: common.CustomerId
    domain_id: common.DomainId
    policy_id: common_1.Slug
    point: EnforcementPoint
    target: target_ref.TargetRef | None = None
    """
    Specific target; null = every target of the point in the domain.
    """
    mode: Annotated[policy_definition.EnforcementMode | None, Field(validate_default=True)] = (
        "audit"
    )
    state: Literal["pending", "applied", "failed", "drifted", "not_supported"]
    """
    pending: not yet applied. applied: verified. failed: apply failed. drifted: verified state changed. not_supported: the point cannot enforce here.
    """
    last_intent_id: audit_record.Uuid | None = None
    """
    Last action intent that changed this binding.
    """
    last_audit_id: audit_record.Uuid | None = None
    """
    Audit record of that change.
    """
    last_verified_at: common.Timestamp | None = None
    """
    When the applied state was last read back.
    """
