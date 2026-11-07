# GENERATED - do not edit.
# Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
# Regenerate: python packages/contracts/scripts/generate.py
# Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
# pyright: reportAssignmentType=false, reportInvalidTypeForm=false

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictStr


class ResourceSpec(BaseModel):
    """
    One resource the apply creates or reuses. Reused resources are only recorded in the ownership register, never modified.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    service: Annotated[StrictStr, Field(pattern="^[a-z][a-z0-9_]{1,63}$")]
    """
    Manifest service key, lowercase snake_case (for example `analytics_workspace`).
    """
    kind: Literal["fabric_capacity", "fabric_workspace", "arm_resource"]
    """
    Provisioning path: Fabric capacity (ARM), Fabric workspace (Fabric REST) or another ARM resource.
    """
    disposition: Literal["create", "reuse"]
    name: Annotated[StrictStr, Field(max_length=256, min_length=1)]
    """
    Resource or display name.
    """
    region: Annotated[StrictStr, Field(pattern="^[a-z][a-z0-9]{2,39}$")]
    """
    Lowercase ARM region name.
    """
    sku: Annotated[StrictStr | None, Field(max_length=128)]
    resource_id: Annotated[StrictStr | None, Field(max_length=1024)]
    """
    ARM resource id of the resource being reused; null when it is created.
    """
    subscription_id: Annotated[
        StrictStr | None,
        Field(
            pattern="^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
        ),
    ]
    resource_group: Annotated[StrictStr | None, Field(max_length=90)]
    consent_reference: Annotated[StrictStr | None, Field(max_length=200)]
    """
    Owner consent reference; required for a reused resource, null otherwise.
    """


class DeployActionPlan(BaseModel):
    """
    Executable snapshot of an approved deployment plan, carried by the `deploy_plan_apply` action kind (PRP-08 item 12). The API derives it from the approved plan; its resource list is written into the ActionIntent proposed_diff (`add /resources/<service>` operations next to `test /plan_hash` and `test /resources_digest`), so the maker confirms and the approver decides on the exact set of resources. plan_hash is the SHA-256 of the canonical plan the approver approved; the executor refuses an apply whose plan is not approved or whose hash differs. Uninstall (`deploy_uninstall`) is dry-run only and carries no resource list. Contains no credential, secret or principal e-mail.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    schema_version: Annotated[StrictStr, Field(pattern="^1\\.(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)$")]
    """
    Contract version of this document (semver within major 1).
    """
    plan_id: Annotated[StrictStr, Field(pattern="^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")]
    """
    Identifier of the approved plan.
    """
    plan_hash: Annotated[StrictStr, Field(pattern="^sha256:[0-9a-f]{64}$")]
    """
    Lowercase hex SHA-256 digest with algorithm prefix of the approved plan.
    """
    deployment_id: Annotated[StrictStr, Field(pattern="^[a-z0-9][a-z0-9-]{2,62}$")]
    """
    Deployment the plan belongs to (ownership register key).
    """
    cloud: Literal["commercial", "government"]
    """
    Azure cloud of the deployment. Never routed to the other cloud.
    """
    resources: Annotated[list[ResourceSpec], Field(max_length=64)]
    """
    Resources to create or reuse, in apply order.
    """
