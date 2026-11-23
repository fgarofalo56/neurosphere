# GENERATED - do not edit.
# Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
# Regenerate: python packages/contracts/scripts/generate.py
# Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
# pyright: reportAssignmentType=false, reportInvalidTypeForm=false

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr

from ...admin.v1 import common
from ...audit.v1 import audit_record
from ...catalog.v1 import common as common_1
from . import policy_definition


class PolicyDecisionMatch(BaseModel):
    """
    One rule that matched the request.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    policy_id: common.Slug
    policy_version: Annotated[StrictInt, Field(ge=1)]
    rule_id: common.Slug
    rule_kind: policy_definition.PolicyRuleKind
    effect: Literal["allow", "deny", "audit"]


class PolicyDecisionResponse(BaseModel):
    """
    The answer to a PolicyDecisionRequest (PRP-99). cache_ttl_seconds is 0 to 3600: how long the caller may reuse it. degraded is true when the engine answered from a stale or partial policy set.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    schema_version: common_1.SchemaVersion
    decision_id: audit_record.Uuid
    decided_at: common_1.Timestamp
    effect: Literal["allow", "deny", "audit"]
    mode: policy_definition.EnforcementMode
    matches: Annotated[list[PolicyDecisionMatch], Field(max_length=20)]
    reason_codes: Annotated[list[common.ReasonCode], Field(max_length=8)]
    cache_ttl_seconds: Annotated[StrictInt, Field(ge=0, le=3600)]
    policy_set_digest: Annotated[StrictStr, Field(pattern="^sha256:[a-f0-9]{64}$")]
    """
    Digest of the policy set evaluated.
    """
    degraded: StrictBool
