# GENERATED - do not edit.
# Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
# Regenerate: python packages/contracts/scripts/generate.py
# Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
# pyright: reportAssignmentType=false, reportInvalidTypeForm=false

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from . import common


class DomainMembershipChange(BaseModel):
    """
    Request to add or remove one pseudonymous principal's membership of one domain (PRP-39 identity API). Maps onto PRP-06 PrincipalPolicy.domain_memberships. Membership alone grants no permission; roles and grants do.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    schema_version: common.SchemaVersion
    op: Literal["add", "remove"]
    principal_id: common.PrincipalId
    domain_id: common.DomainId
    reason: common.ReasonCode
