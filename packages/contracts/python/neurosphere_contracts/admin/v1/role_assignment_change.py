# GENERATED - do not edit.
# Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
# Regenerate: python packages/contracts/scripts/generate.py
# Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
# pyright: reportAssignmentType=false, reportInvalidTypeForm=false

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from . import common


class RoleAssignmentChange(BaseModel):
    """
    Request to assign or remove one domain-scoped role for one pseudonymous principal (PRP-39 identity API). Maps onto PRP-06 PolicyRoleAssignment: assign upserts the assignment with assignment_id, remove deletes it. Privileged roles (admin, security_auditor) must carry expires_at, as PolicyRoleAssignment requires; there is no tenant-wide, wildcard or permanent privileged form. The caller's identity and permission come from the server-derived IdentityScope, never from this body. Rules JSON Schema cannot express (expires_at is in the future) are enforced by the PRP-39 handler.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    schema_version: common.SchemaVersion
    op: Literal["assign", "remove"]
    """
    assign: create or replace the assignment (role and domain_ids required). remove: delete it (role and domain_ids optional, echoed for audit).
    """
    principal_id: common.PrincipalId
    assignment_id: common.RecordId
    role: common.Role | None = None
    domain_ids: Annotated[list[common.DomainId] | None, Field(max_length=1024, min_length=1)] = None
    """
    Domains the role applies to. At least one; there is no tenant-wide form.
    """
    expires_at: common.Timestamp | None = None
    """
    When the assignment lapses. Required for admin and security_auditor.
    """
    reason: common.ReasonCode
