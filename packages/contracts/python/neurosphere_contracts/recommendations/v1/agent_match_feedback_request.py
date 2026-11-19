# GENERATED - do not edit.
# Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
# Regenerate: python packages/contracts/scripts/generate.py
# Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
# pyright: reportAssignmentType=false, reportInvalidTypeForm=false

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictStr

from ...catalog.v1 import common


class AgentMatchFeedbackRequest(BaseModel):
    """
    A steward's accept or reject of one match candidate (PRP-70 item 3). Reason codes only: there is deliberately no free-text field, so no PII-bearing text is stored. reason_code is optional and defaults to null. Cloud, customer, domain and actor come from the server-derived IdentityScope, not the request.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    schema_version: common.SchemaVersion
    match_id: Annotated[StrictStr, Field(pattern="^[a-z0-9][a-z0-9._:/=-]{0,255}$")]
    entity_id: common.CanonicalId
    decision: Literal["accepted", "rejected"]
    reason_code: (
        Literal[
            "not_relevant", "missing_capability", "poor_quality", "unavailable", "policy", "other"
        ]
        | None
    ) = None
