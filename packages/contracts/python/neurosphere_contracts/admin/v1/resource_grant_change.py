# GENERATED - do not edit.
# Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
# Regenerate: python packages/contracts/scripts/generate.py
# Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
# pyright: reportAssignmentType=false, reportInvalidTypeForm=false

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from . import common


class ResourceGrantChange(BaseModel):
    """
    Request to create or replace one custom resource-scoped grant for one pseudonymous principal (PRP-39 identity API). Maps onto PRP-06 PolicyGrant: one named resource, time-bound (expires_at always required) and reason-bearing. Removing a grant is a delete of grant_id on the route, not a body. Rules JSON Schema cannot express (expires_at is in the future) are enforced by the PRP-39 handler.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    schema_version: common.SchemaVersion
    principal_id: common.PrincipalId
    grant_id: common.RecordId
    resource_id: common.CanonicalId
    permissions: Annotated[list[common.GrantPermission], Field(max_length=5, min_length=1)]
    expires_at: common.Timestamp
    reason: common.ReasonCode
