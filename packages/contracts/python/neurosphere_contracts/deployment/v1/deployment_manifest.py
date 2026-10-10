# GENERATED - do not edit.
# Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
# Regenerate: python packages/contracts/scripts/generate.py
# Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
# pyright: reportAssignmentType=false, reportInvalidTypeForm=false

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel, StrictBool, StrictStr


class UtcTimestamp(RootModel[StrictStr]):
    root: Annotated[
        StrictStr,
        Field(
            pattern="^[0-9]{4}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])T([01][0-9]|2[0-3]):[0-5][0-9]:([0-5][0-9]|60)(\\.[0-9]{1,9})?Z$"
        ),
    ]


class Region(RootModel[StrictStr]):
    root: Annotated[StrictStr, Field(pattern="^[a-z][a-z0-9]{2,39}$")]
    """
    Concrete lowercase ARM region name; global is not a deployment region.
    """


class OwnerConsent(BaseModel):
    """
    Enterprise owner consent for using a (shared) resource. Always required for reuse.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    required: StrictBool
    """
    Whether owner consent is needed for this decision.
    """
    granted: StrictBool
    """
    Whether consent has been recorded.
    """
    owner_principal: Annotated[StrictStr | None, Field(pattern="^[a-z0-9][a-z0-9._:/=-]{0,255}$")]
    """
    Who granted consent: pseudonymous principal reference (principal pseudonym or canonical ID), no email or display name. Null until granted.
    """
    recorded_at: Annotated[
        StrictStr | None,
        Field(
            pattern="^[0-9]{4}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])T([01][0-9]|2[0-3]):[0-5][0-9]:([0-5][0-9]|60)(\\.[0-9]{1,9})?Z$"
        ),
    ]
    """
    When consent was recorded (RFC 3339 UTC); null until granted.
    """


class CostImplication(BaseModel):
    """
    Plan/cost implication of the decision. Unknown is null, never 0; an estimate cites its price version.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    basis: Literal["estimated", "no_incremental_cost", "unknown"]
    """
    estimated = priced estimate; no_incremental_cost = reuse/skip adds no new spend; unknown = not yet priced.
    """
    monthly_amount: Annotated[StrictStr | None, Field(pattern="^[0-9]{1,15}(\\.[0-9]{1,6})?$")]
    """
    Estimated monthly amount as a decimal string; null unless basis is estimated.
    """
    currency: Annotated[StrictStr | None, Field(pattern="^[A-Z]{3}$")]
    """
    ISO 4217 code; null unless basis is estimated.
    """
    price_version: Annotated[StrictStr | None, Field(max_length=128, min_length=1)]
    """
    Price sheet version the estimate cites; null unless basis is estimated.
    """
    summary: Annotated[StrictStr | None, Field(max_length=500)] = None
    """
    Short human-readable explanation shown in the plan.
    """


class ServicePlan(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    service: Literal[
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
    """
    Platform service this decision covers.
    """
    decision: Literal["reuse", "create", "skip"]
    """
    reuse an existing (possibly shared) resource, create a new one with IaC, or skip.
    """
    existing_resource_id: Annotated[
        StrictStr | None,
        Field(
            max_length=1024,
            pattern="^/subscriptions/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}/resourceGroups/[^/]+/providers/[^/]+/.+$",
        ),
    ] = None
    """
    ARM resource ID of the resource to reuse. Required for reuse, null otherwise. Shared resources are never modified or deleted on uninstall.
    """
    skip_reason: Annotated[StrictStr | None, Field(max_length=500, min_length=1)] = None
    """
    Why the service is skipped. Required for skip.
    """
    owner_consent: OwnerConsent
    cost_implication: CostImplication


class DeploymentManifest(BaseModel):
    """
    One customer-hosted NeuroSphere deployment plan (NS-07): a single cloud, approved regions, hosting profile, analytics backend and a reuse/create/skip decision per service with owner consent and cost implication. cloud is one scalar per manifest and no service, region or endpoint field can name another cloud, so routing Government data to Commercial is not expressible; Government manifests may list only usgov*/usdod* regions and Commercial manifests may not list them. Whether a backend, SKU or service is actually offered in the chosen cloud/region is decided by the capability matrix (CapabilityMatrixEntry, data in PRP-02), not by this schema. Rules JSON Schema cannot express are checked by the Python validator check_deployment_manifest in tests/contracts/test_deployment_manifest.py (PRP-01 item 7): each service appears at most once in services; existing_resource_id is not repeated across services.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    schema_version: Annotated[StrictStr, Field(pattern="^1\\.(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)$")]
    """
    Contract version of this document (semver within major 1).
    """
    deployment_id: Annotated[StrictStr, Field(pattern="^[a-z0-9][a-z0-9-]{2,62}$")]
    """
    Stable identifier of this deployment.
    """
    cloud: Literal["commercial", "government"]
    """
    The single Azure cloud for every service and every byte of data in this deployment. A scalar by design: there is no secondary or fallback cloud.
    """
    regions: Annotated[list[Region], Field(max_length=8, min_length=1)]
    """
    Approved Azure region names (lowercase ARM names, for example eastus2 or usgovvirginia). The first entry is the primary region. Must belong to cloud.
    """
    hosting_profile: Literal["aks", "appservice"]
    """
    aks = enterprise profile on AKS; appservice = smaller App Service profile.
    """
    analytics_backend: Literal["fabric", "synapse", "databricks"]
    """
    Analytics adapter chosen at deployment, behind the shared capability/query contract. Availability per cloud/region comes from the capability matrix.
    """
    status: Literal["draft", "planned", "approved", "applied"]
    """
    Plan lifecycle. Once approved or applied, every reused service must carry granted owner consent.
    """
    services: Annotated[list[ServicePlan], Field(max_length=64, min_length=1)]
    """
    Per-service decision. Uniqueness of service is checked by check_deployment_manifest.
    """
    created_at: UtcTimestamp
    """
    RFC 3339 UTC timestamp.
    """
