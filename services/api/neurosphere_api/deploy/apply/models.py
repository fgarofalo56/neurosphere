"""Request and response models for plan approval, apply and uninstall preview (PRP-08 item 12).

Bodies carry only what the surface decides. Identity, customer, domain, timestamps and ids are
server-side; ``extra="forbid"`` makes a smuggled ``actor`` or ``customer_id`` a 422. Nothing here
can express a delete: the uninstall body has no ``dry_run`` field and the response is always a
dry-run preview.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from neurosphere_api.actions.models import ActionView
from neurosphere_api.deploy.plan.models import DeploymentPlan

__all__ = [
    "ApplyBody",
    "ApplyTarget",
    "ApplyView",
    "ApprovePlanBody",
    "ApprovedPlanView",
    "PlannedResource",
    "UninstallEntry",
    "UninstallPreviewBody",
    "UninstallPreviewView",
]

_GUID = r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
PLAN_ID_PATTERN = r"^plan-[0-9a-f]{32}$"
PLAN_HASH_PATTERN = r"^sha256:[0-9a-f]{64}$"
DEPLOYMENT_ID_PATTERN = r"^[a-z0-9][a-z0-9-]{2,62}$"
_IDEMPOTENCY = r"^[A-Za-z0-9._:-]{16,128}$"

PlanId = Annotated[str, StringConstraints(pattern=PLAN_ID_PATTERN)]
PlanHash = Annotated[str, StringConstraints(pattern=PLAN_HASH_PATTERN)]
DeploymentId = Annotated[str, StringConstraints(pattern=DEPLOYMENT_ID_PATTERN)]
IdempotencyKey = Annotated[str, StringConstraints(pattern=_IDEMPOTENCY)]
Channel = Literal["button", "chat", "rest", "mcp"]


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ApplyTarget(_Body):
    """Where the plan's new resources go. Chosen by the approver, never inferred."""

    subscription_id: Annotated[str, StringConstraints(pattern=_GUID)]
    resource_group: Annotated[str, StringConstraints(pattern=r"^[\w.()-]{1,90}$")]
    #: Must be one of the plan profile's regions.
    region: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9]{2,39}$")]
    capacity_sku: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9]{1,32}$")] = "F2"


class ApprovePlanBody(_Body):
    """``POST .../plans/approve``: the approver attests to exactly this plan and target."""

    plan: DeploymentPlan
    target: ApplyTarget


class PlannedResource(_Body):
    """One resource the apply will create or reuse (what the approver and maker confirm)."""

    service: str
    kind: Literal["fabric_capacity", "fabric_workspace", "arm_resource"]
    disposition: Literal["create", "reuse"]
    name: str
    region: str
    sku: str | None
    resource_id: str | None


class ApprovedPlanView(_Body):
    plan_id: str
    plan_hash: str
    resources_digest: str
    deployment_id: str
    cloud: Literal["commercial", "government"]
    resources: list[PlannedResource]
    approved_at: datetime
    expires_at: datetime


class ApplyBody(_Body):
    """``POST .../plans/apply``: drafts the apply intent for an approved plan."""

    plan_id: PlanId
    #: The hash the caller was shown; must equal the approved one.
    plan_hash: PlanHash
    idempotency_key: IdempotencyKey
    channel: Channel = "rest"


class ApplyView(_Body):
    plan_id: str
    plan_hash: str
    resources: list[PlannedResource]
    #: The drafted intent. It still needs validation, confirmation and approval through the
    #: action routes; the executor worker applies it.
    action: ActionView


class UninstallPreviewBody(_Body):
    """``POST .../uninstall/preview``. There is deliberately no ``dry_run`` field: always one."""

    deployment_id: DeploymentId
    idempotency_key: IdempotencyKey
    channel: Channel = "rest"
    #: List each registered resource group's live contents (read-only ARM) before classifying.
    verify_live: bool = False


class UninstallEntry(_Body):
    resource_id: str
    service: str | None
    ownership: str | None
    reason: str | None


class UninstallPreviewView(_Body):
    deployment_id: str
    dry_run: Literal[True] = True
    register_digest: str
    #: What a guarded, operator-run uninstall would remove (nothing is removed here).
    removable: list[UninstallEntry] = Field(default_factory=list[UninstallEntry])
    #: Everything else, including every ``reused``/``shared`` resource, with the reason.
    untouched: list[UninstallEntry] = Field(default_factory=list[UninstallEntry])
    action: ActionView
