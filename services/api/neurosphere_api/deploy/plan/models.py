"""Request and response models for the reuse/create/skip deployment planner (PRP-08 item 4)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Self

from neurosphere_contracts.deployment.v1.deployment_manifest import DeploymentManifest
from neurosphere_core.capabilities import DeploymentProfile
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from neurosphere_api.deploy.scan import ScanResponse

#: Manifest service names (the ``service_plan.service`` enum of the PRP-01 contract).
ManifestService = Literal[
    "api_management",
    "model_endpoint",
    "key_vault",
    "monitoring",
    "event_hubs",
    "storage",
    "analytics_workspace",
    "cosmos_db",
    "ai_search",
    "container_registry",
    "kubernetes",
    "app_service",
]

PlanStatus = Literal["reuse", "create", "skip", "needs_consent", "disabled"]
CheckName = Literal["sku", "network_reachability", "quota", "permission", "residency", "lifecycle"]
CheckOutcome = Literal["pass", "fail", "unknown"]

#: Pseudonymous principal reference, same shape the manifest contract accepts (no email).
PRINCIPAL_PATTERN = r"^[a-z0-9][a-z0-9._:/=-]{0,255}$"
_AMOUNT_PATTERN = r"^[0-9]{1,15}(\.[0-9]{1,6})?$"


class OwnerConsentRecord(BaseModel):
    """Enterprise-owner consent to reuse specific shared resources.

    A *granted* record must name a pseudonymous owner principal; it only ever covers the
    resource ids it lists (ARM ids compare case-insensitively).
    """

    model_config = ConfigDict(extra="forbid")

    consent_id: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    granted: bool
    owner_principal: Annotated[str, StringConstraints(pattern=PRINCIPAL_PATTERN)] | None = None
    resource_ids: list[Annotated[str, StringConstraints(min_length=1, max_length=1024)]] = Field(
        min_length=1, max_length=1000
    )
    recorded_at: datetime

    @model_validator(mode="after")
    def _granted_names_principal(self) -> Self:
        if self.granted and not self.owner_principal:
            raise ValueError("a granted consent record must name an owner_principal")
        return self

    def covers(self, resource_id: str) -> bool:
        wanted = resource_id.casefold()
        return any(r.casefold() == wanted for r in self.resource_ids)


class PriceEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    service: ManifestService
    sku: str | None = None
    monthly_amount: Annotated[str, StringConstraints(pattern=_AMOUNT_PATTERN)]


class PriceTable(BaseModel):
    """Versioned static price input. No live pricing call is ever made."""

    model_config = ConfigDict(extra="forbid")

    price_version: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    currency: Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")] = "USD"
    entries: list[PriceEntry] = Field(default_factory=list, max_length=1000)


class ServiceChoice(BaseModel):
    """Operator choice for one service. ``fallback`` applies when reuse is not possible."""

    model_config = ConfigDict(extra="forbid")

    decision: Literal["reuse", "create", "skip"]
    resource_id: Annotated[str, StringConstraints(min_length=1, max_length=1024)] | None = None
    sku: Annotated[str, StringConstraints(min_length=1, max_length=128)] | None = None
    fallback: Literal["create", "skip"] = "create"


class PlanRequest(BaseModel):
    """Everything the planner needs; the planner itself makes no ARM or HTTP call.

    ``scan`` is the :class:`ScanResponse` of a prior consented scan (passed in rather than
    re-fetched, so the plan is a pure function of its inputs). Services without a choice
    default to ``reuse`` when a discovered candidate exists, else ``create``.
    """

    model_config = ConfigDict(extra="forbid")

    profile: DeploymentProfile
    scan: ScanResponse | None = None
    choices: dict[ManifestService, ServiceChoice] = Field(default_factory=dict)
    consents: list[OwnerConsentRecord] = Field(default_factory=list, max_length=1000)
    price_table: PriceTable | None = None
    deployment_id: (
        Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]{2,62}$")] | None
    ) = None


class PlanCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: CheckName
    outcome: CheckOutcome
    reason: str


class PlanCost(BaseModel):
    """Mirrors the manifest ``cost_implication``; unknown is ``None``, never ``0``."""

    model_config = ConfigDict(extra="forbid")

    basis: Literal["estimated", "no_incremental_cost", "unknown"]
    monthly_amount: str | None = None
    currency: str | None = None
    price_version: str | None = None
    summary: str | None = None


class PlanItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    service: str
    #: ``service`` items project to the manifest; ``feature`` items (disabled optional
    #: capabilities) are plan-only.
    kind: Literal["service", "feature"] = "service"
    status: PlanStatus
    existing_resource_id: str | None = None
    #: A discovered resource not carrying the NeuroSphere-created marker tag.
    shared: bool = False
    #: The reused resource carries the NeuroSphere-created marker tag.
    neurosphere_created: bool = False
    checks: list[PlanCheck] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    disabled_reason: str | None = None
    reason_code: str | None = None
    source_url: str | None = None
    owner_consent: OwnerConsentRecord | None = None
    cost_implication: PlanCost


class DeploymentPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_id: str
    deployment_id: str
    profile: DeploymentProfile
    items: list[PlanItem]
    capability_warnings: list[str] = Field(default_factory=list)
    #: Consent records the plan relied on (granted and covering a reused resource).
    consents: list[OwnerConsentRecord] = Field(default_factory=list)
    created_at: datetime


class PlanResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan: DeploymentPlan
    manifest: DeploymentManifest
