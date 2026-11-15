# GENERATED - do not edit.
# Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
# Regenerate: python packages/contracts/scripts/generate.py
# Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
# pyright: reportAssignmentType=false, reportInvalidTypeForm=false

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from . import common


class RevocationRequest(BaseModel):
    """
    Request to revoke one principal's sessions (PRP-39; PRP-06 revocation service). The target principal is named by the route, never by this body. issued_before: deny every token issued at or before the revocation (plus clock skew); the principal may sign in again. until_lifted: deny every token until an operator lifts the revocation. Revocation is bounded by NS_REVOCATION_TTL_SECONDS, not instant.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    schema_version: common.SchemaVersion
    reason: common.ReasonCode
    mode: Literal["issued_before", "until_lifted"]
