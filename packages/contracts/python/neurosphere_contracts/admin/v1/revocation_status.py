# GENERATED - do not edit.
# Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
# Regenerate: python packages/contracts/scripts/generate.py
# Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
# pyright: reportAssignmentType=false, reportInvalidTypeForm=false

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt

from . import common


class RevocationStatus(BaseModel):
    """
    OUTPUT-ONLY. Current revocation state of one principal (PRP-39; PRP-06 RevocationEntry). When revoked is false every revocation member is null. propagation_bound_seconds is the documented worst-case delay before every API replica denies (NS_REVOCATION_TTL_SECONDS); revocation is never claimed to be instant.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    schema_version: common.SchemaVersion
    principal_id: common.PrincipalId
    revoked: StrictBool
    mode: Literal["issued_before", "until_lifted"] | None
    revoked_at: common.Timestamp | None
    reason: common.ReasonCode | None
    revoked_by: common.PrincipalId | None
    propagation_bound_seconds: Annotated[StrictInt, Field(ge=1, le=900)]
