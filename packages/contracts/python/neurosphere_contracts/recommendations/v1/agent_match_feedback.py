# GENERATED - do not edit.
# Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
# Regenerate: python packages/contracts/scripts/generate.py
# Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
# pyright: reportAssignmentType=false, reportInvalidTypeForm=false

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt, StrictStr

from ...catalog.v1 import common


class Ranker(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    ranker_id: common.Token
    ranker_version: Annotated[StrictStr, Field(pattern="^[A-Za-z0-9._+-]{1,64}$")]


class AgentMatchFeedback(BaseModel):
    """
    Stored feedback on one match candidate (PRP-70 item 3). It never carries task text: task_digest is the SHA-256 of the normalized task text. Reason codes only, no free text. Nullable fields are optional and default to null.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    schema_version: common.SchemaVersion
    feedback_id: Annotated[StrictStr, Field(pattern="^[a-z0-9][a-z0-9._:/=-]{0,255}$")]
    cloud: common.Cloud
    customer_id: common.CustomerId
    domain_id: common.DomainId
    match_id: Annotated[StrictStr, Field(pattern="^[a-z0-9][a-z0-9._:/=-]{0,255}$")]
    entity_id: common.CanonicalId
    entity_type: Literal["agent", "tool"]
    decision: Literal["accepted", "rejected"]
    reason_code: (
        Literal[
            "not_relevant", "missing_capability", "poor_quality", "unavailable", "policy", "other"
        ]
        | None
    ) = None
    rank_at_decision: Annotated[StrictInt, Field(ge=1, le=50)]
    score_at_decision: Annotated[StrictFloat, Field(ge=0.0, le=1.0)]
    task_digest: Annotated[StrictStr, Field(pattern="^sha256:[a-f0-9]{64}$")]
    """
    SHA-256 of the normalized task text; the text itself is never stored.
    """
    required_capabilities: Annotated[list[common.Capability], Field(max_length=16)]
    ranker: Ranker
    decided_by: common.PersonId
    decided_at: common.Timestamp
    expires_at: common.Timestamp | None = None
