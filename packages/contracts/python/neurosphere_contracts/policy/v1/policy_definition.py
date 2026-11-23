# GENERATED - do not edit.
# Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
# Regenerate: python packages/contracts/scripts/generate.py
# Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
# pyright: reportAssignmentType=false, reportInvalidTypeForm=false

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    RootModel,
    StrictBool,
    StrictInt,
    StrictStr,
)

from ...admin.v1 import common as common_1
from ...audit.v1 import audit_record
from ...catalog.v1 import common
from ...interactions.v1 import detection_finding


class EnforcementMode(RootModel[Literal["off", "audit", "enforce"]]):
    root: Annotated[Literal["off", "audit", "enforce"], Field(title="EnforcementMode")] = "audit"
    """
    How a policy or enforcement point acts: off (not evaluated), audit (evaluated and recorded, never blocks; the default, GD-7) or enforce (blocks). Enforce is set only by an approved action.
    """


class PolicySeverity(RootModel[Literal["low", "medium", "high", "critical"]]):
    root: Annotated[Literal["low", "medium", "high", "critical"], Field(title="PolicySeverity")]
    """
    How serious a violation of the policy or rule is.
    """


class PolicyRuleKind(
    RootModel[
        Literal[
            "model_allow_list",
            "data_sensitivity_access",
            "residency",
            "budget",
            "required_owner",
            "required_attestation",
            "required_approval",
            "content_rule",
            "registration_required",
        ]
    ]
):
    root: Annotated[
        Literal[
            "model_allow_list",
            "data_sensitivity_access",
            "residency",
            "budget",
            "required_owner",
            "required_attestation",
            "required_approval",
            "content_rule",
            "registration_required",
        ],
        Field(title="PolicyRuleKind"),
    ]
    """
    Closed typed rule kind that selects the parameter object; open-ended: readers must tolerate unknown values (PRP-110 adds identity_entitlement).
    """


class EntityType(RootModel[StrictStr]):
    root: Annotated[StrictStr, Field(max_length=64, pattern="^[a-z][a-z0-9_]{0,63}$")]


class PolicyAppliesTo(BaseModel):
    """
    Which entities a rule covers inside the domain. Every list defaults to empty, and all-empty means every entity in the domain.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    entity_types: Annotated[
        list[EntityType] | None, Field(max_length=8, validate_default=True)
    ] = []
    """
    Catalog entity types.
    """
    tags: Annotated[list[common.Tag] | None, Field(max_length=16, validate_default=True)] = []
    """
    Catalog tags.
    """
    environments: Annotated[
        list[common.Environment] | None, Field(max_length=6, validate_default=True)
    ] = []
    """
    Deployment environments.
    """
    entity_ids: Annotated[
        list[common.CanonicalId] | None, Field(max_length=64, validate_default=True)
    ] = []
    """
    Specific entities by canonical id.
    """


class AllowedModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    model_name: Annotated[StrictStr, Field(max_length=128, min_length=1)]
    model_version: Annotated[StrictStr | None, Field(max_length=128, min_length=1)] = None
    """
    Null means any version.
    """


class ModelAllowListParams(BaseModel):
    """
    Only the listed models or deployments may be used.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    allowed_models: Annotated[
        list[AllowedModel] | None, Field(max_length=64, validate_default=True)
    ] = []
    """
    Allowed model names and versions.
    """
    allowed_deployment_ids: Annotated[
        list[common.CanonicalId] | None, Field(max_length=64, validate_default=True)
    ] = []
    """
    Allowed model deployments by canonical id.
    """


class DataSensitivityAccessParams(BaseModel):
    """
    Access to data of the listed sensitivity categories needs an approved agent version or an exception.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    sensitivity_categories: Annotated[
        list[common.SensitivityCategory], Field(max_length=10, min_length=1)
    ]
    access: Literal["read", "write", "read_or_write"]
    allowed_when: Literal["agent_version_approved", "exception_only"]


class ResidencyParams(BaseModel):
    """
    Data and calls stay inside the listed geographies and regions.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    allowed_geographies: Annotated[
        list[common.ResidencyGeography] | None,
        Field(max_length=16, validate_default=True),
    ] = []
    """
    Coarse geographies.
    """
    allowed_regions: Annotated[
        list[common.Token] | None, Field(max_length=64, validate_default=True)
    ] = []
    """
    Provider region tokens.
    """


class BudgetRuleParams(BaseModel):
    """
    A budget record crossing a percentage of its limit.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    budget_record_id: common_1.RecordId
    threshold_percent: Annotated[StrictInt, Field(ge=1, le=1000)]
    on_breach: Literal["alert", "propose_cap_change"]


class RequiredOwnerParams(BaseModel):
    """
    The entity needs owners.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    min_owners: Annotated[StrictInt | None, Field(ge=1, le=5)] = 1
    require_active_owner: StrictBool | None = True


class RequiredAttestationParams(BaseModel):
    """
    A recent attestation of the given kind is required.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    attestation_kind: Literal["owner_recertification", "agent_attestation"]
    max_age_days: Annotated[StrictInt, Field(ge=1, le=730)]


class RequiredApprovalParams(BaseModel):
    """
    The entity version needs an approval before it is active.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    entity_types: Annotated[
        list[EntityType] | None,
        Field(max_length=8, min_length=1, validate_default=True),
    ] = ["agent_version"]
    """
    Entity types that need approval: `agent_version` today. Open-ended: readers must tolerate unknown values.
    """
    block_activation: StrictBool | None = True


class ContentRuleParams(BaseModel):
    """
    Captured interactions whose findings include the listed categories, counted from interaction metadata (never content).
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    detected_categories: Annotated[
        list[detection_finding.DetectedCategory], Field(max_length=16, min_length=1)
    ]
    min_count: Annotated[StrictInt | None, Field(ge=1, le=100000)] = 1
    parts: Annotated[
        list[detection_finding.ContentPartKind] | None,
        Field(max_length=5, validate_default=True),
    ] = []
    """
    Content parts to count; empty means all.
    """
    window_minutes: Annotated[StrictInt | None, Field(ge=1, le=10080)] = 60


class RegistrationRequiredParams(BaseModel):
    """
    Entities seen in telemetry must be registered in the catalog within the grace period.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    entity_types: Annotated[
        list[Literal["agent", "tool", "model_deployment", "mcp_server", "service"]],
        Field(max_length=5, min_length=1),
    ]
    grace_period_hours: Annotated[StrictInt | None, Field(ge=0, le=720)] = 24


class PolicyRule(BaseModel):
    """
    One typed rule. params is pinned by kind (anyOf plus allOf if/then, the AdminConfigDocument pattern); core validates it again because the generated Pydantic model cannot express the per-kind rule (ADR-0004). There is no expression, code, query or free-text condition field.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    rule_id: common_1.Slug
    kind: PolicyRuleKind
    severity: PolicySeverity | None = None
    """
    Overrides the policy severity. Null uses the policy's.
    """
    applies_to: Annotated[PolicyAppliesTo | None, Field(validate_default=True)] = {}
    params: (
        ModelAllowListParams
        | DataSensitivityAccessParams
        | ResidencyParams
        | BudgetRuleParams
        | RequiredOwnerParams
        | RequiredAttestationParams
        | RequiredApprovalParams
        | ContentRuleParams
        | RegistrationRequiredParams
    )
    """
    The kind's parameter object; allOf below pins which one.
    """


class PolicyDefinition(BaseModel):
    """
    A governance policy as typed rules (PRP-99; container policy_definitions, declared by PRP-102). Rules are closed typed kinds with parameter objects: no expression, code, query or free-text condition exists, by decision (PRP-99 clarification 4). Mode defaults to audit (GD-7). The kind-to-params pin and the published-requires-publish-evidence rule are JSON Schema if/then that Pydantic ignores (ADR-0004), so consumers validate against the JSON Schema.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    schema_version: common.SchemaVersion
    policy_id: common_1.Slug
    """
    Policy id (slug).
    """
    policy_version: Annotated[StrictInt, Field(ge=1)]
    """
    Increments on every change.
    """
    previous_version: Annotated[StrictInt | None, Field(ge=1)] = None
    """
    Version this one replaces. Null for the first.
    """
    cloud: common.Cloud
    customer_id: common.CustomerId
    domain_id: common.DomainId
    display_name: common_1.DisplayName
    document_url: common_1.HttpsUrl | None = None
    """
    Link to the source policy document. Null when none.
    """
    status: Literal["draft", "published", "retired"]
    mode: Annotated[EnforcementMode | None, Field(validate_default=True)] = "audit"
    severity: PolicySeverity
    rules: Annotated[list[PolicyRule], Field(max_length=32, min_length=1)]
    """
    One to 32 typed rules.
    """
    content_sha256: Annotated[StrictStr, Field(pattern="^sha256:[a-f0-9]{64}$")]
    """
    Digest of the canonical rules, so a published version cannot change silently.
    """
    created_by: common_1.PrincipalId
    created_at: common.Timestamp
    published_at: common.Timestamp | None = None
    """
    When published. Required when status is published.
    """
    published_intent_id: audit_record.Uuid | None = None
    """
    Approved publish intent.
    """
    published_audit_id: audit_record.Uuid | None = None
    """
    Audit record of the publish.
    """
