# GENERATED - do not edit.
# Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
# Regenerate: python packages/contracts/scripts/generate.py
# Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
# pyright: reportAssignmentType=false, reportInvalidTypeForm=false

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel, StrictStr

from . import common, revocation_status


class AccessSummaryPrincipal(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    principal_id: common.PrincipalId
    principal_kind: Literal["user", "service_principal"]


class StoredReason(RootModel[StrictStr]):
    root: Annotated[StrictStr, Field(max_length=512, min_length=1)]
    """
    Reason as stored by PRP-06 (PolicyRoleAssignment.reason, PolicyGrant.reason: 1 to 512 characters). Writes made through admin v1 store reason codes.
    """


class AccessSummaryAssignment(BaseModel):
    """
    A stored role assignment. expires_at is null only for non-privileged roles.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    assignment_id: common.RecordId
    role: common.Role
    domain_ids: Annotated[list[common.CanonicalId], Field(max_length=1024, min_length=1)]
    expires_at: common.Timestamp | None
    reason: StoredReason | None


class AccessSummaryGrant(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    grant_id: common.RecordId
    resource_id: common.CanonicalId
    permissions: Annotated[list[common.GrantPermission], Field(max_length=5, min_length=1)]
    expires_at: common.Timestamp
    reason: StoredReason


class PrincipalAccessSummary(BaseModel):
    """
    OUTPUT-ONLY. Everything one pseudonymous principal can do, as stored in the PRP-06 policy store, for the PRP-39 identity console: domain memberships, role assignments with expiry, resource-scoped grants and the current revocation state. It is a view of stored policy, not a derived IdentityScope, and is never accepted as input. No name, email, UPN or raw directory object id appears; re-identification is a policy-store concern.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    schema_version: common.SchemaVersion
    principal: AccessSummaryPrincipal
    customer_id: common.CustomerId
    cloud: common.Cloud
    policy_version: Annotated[StrictStr, Field(pattern="^[A-Za-z0-9._+-]{1,64}$")]
    """
    Policy store version the summary was read at.
    """
    memberships: Annotated[list[common.CanonicalId], Field(max_length=1024)]
    assignments: Annotated[list[AccessSummaryAssignment], Field(max_length=64)]
    grants: Annotated[list[AccessSummaryGrant], Field(max_length=4096)]
    revocation: revocation_status.RevocationStatus
    generated_at: common.Timestamp
