"""The durable plan-approval record (PRP-55 item 1).

One record per ``(customer_id, plan_id)``: the hash of the plan exactly as approved, the digest of
its executable resources, the resources themselves, the deployment id and cloud, a pseudonymous
approver and the approval window. No secret and no principal e-mail is ever stored: the approver
is the scope's pseudonym and a value that looks like an e-mail address is refused.
"""

from __future__ import annotations

from datetime import datetime
from typing import Final, Self

from neurosphere_contracts.deployment.v1.deploy_action_plan import ResourceSpec
from pydantic import BaseModel, ConfigDict, Field, model_validator

from neurosphere_core.errors import InvalidSchemaError

__all__ = ["PLAN_ID_CONFLICT", "PlanApprovalRecord", "decide"]

#: Reason of a second approval under the same plan id with a different plan hash.
PLAN_ID_CONFLICT: Final = "plan_id_conflict"

_PLAN_ID: Final = r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$"
_HASH: Final = r"^sha256:[0-9a-f]{64}$"


class PlanApprovalRecord(BaseModel):
    """What the approver approved, and until when (identifiers and digests only)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    customer_id: str = Field(min_length=1, max_length=128)
    plan_id: str = Field(pattern=_PLAN_ID)
    plan_hash: str = Field(pattern=_HASH)
    resources_digest: str = Field(pattern=_HASH)
    deployment_id: str = Field(min_length=1, max_length=128)
    cloud: str = Field(pattern=r"^(commercial|government)$")
    resources: tuple[ResourceSpec, ...] = ()
    #: Pseudonymous approver (never a real principal id or e-mail).
    approver: str = Field(min_length=1, max_length=256)
    approved_at: datetime
    expires_at: datetime

    @model_validator(mode="after")
    def _no_email_and_ordered_window(self) -> Self:
        if "@" in self.approver:
            raise ValueError("the approver must be a pseudonym, never an e-mail address")
        if self.expires_at <= self.approved_at:
            raise ValueError("an approval must expire after it was granted")
        return self

    def live_at(self, now: datetime) -> bool:
        return self.expires_at > now


def decide(
    existing: PlanApprovalRecord | None, new: PlanApprovalRecord, now: datetime
) -> PlanApprovalRecord | None:
    """The create-only rule shared by every store.

    Returns the record to keep when nothing must be written (a live approval of the same hash:
    idempotent), ``None`` when ``new`` must be written (no record, or only an expired one), and
    raises ``InvalidSchemaError`` ``plan_id_conflict`` for a live approval of another hash.
    """
    if existing is None or not existing.live_at(now):
        return None
    if existing.plan_hash != new.plan_hash:
        raise InvalidSchemaError(
            "another plan was already approved under this plan id", reason=PLAN_ID_CONFLICT
        )
    return existing
