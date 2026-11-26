"""Policy engine model vocabulary (PRP-105 item 1): the PRP-99 ``policy/v1`` types and core tables.

The contract types are re-exported unchanged; PRP-99 owns them and wins on any naming question.
This module adds what the generated models cannot say:

* :data:`RULE_KINDS` - the closed rule-kind list (PRP-99 ``PolicyRuleKind``), in contract order;
* :data:`EVALUATED_KINDS` - the seven kinds this PRP evaluates (clarification 2); ``budget``
  (PRP-115) and ``required_attestation`` (PRP-130) register their evaluators later;
* :data:`PARAMS_MODEL_BY_KIND` - the kind-to-parameter-model pin the JSON Schema states with
  ``if/then`` and Pydantic ignores (ADR-0004);
* :data:`POINTS_BY_RULE_KIND` - which enforcement points a rule kind can bind to (ASSUMPTION
  table, documented in the runbook); a kind with no point is detective only;
* :class:`EvaluationStatus` - the run-status document (``doc_kind: evaluation_status`` in the
  ``policy_definitions`` container, clarification 9). It carries ids, counts and reason codes,
  never content.

Nothing here (or anywhere in the package) compiles, evaluates or templates rule text: a rule is
a typed parameter object, and there is no expression field to execute.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Annotated, Final, Literal

from neurosphere_contracts.actions.v1.target_ref import TargetRef
from neurosphere_contracts.policy.v1.enforcement_binding import (
    EnforcementBinding,
    EnforcementPoint,
)
from neurosphere_contracts.policy.v1.policy_decision_request import PolicyDecisionRequest
from neurosphere_contracts.policy.v1.policy_decision_response import (
    PolicyDecisionMatch,
    PolicyDecisionResponse,
)
from neurosphere_contracts.policy.v1.policy_definition import (
    AllowedModel,
    BudgetRuleParams,
    ContentRuleParams,
    DataSensitivityAccessParams,
    EnforcementMode,
    ModelAllowListParams,
    PolicyAppliesTo,
    PolicyDefinition,
    PolicyRule,
    PolicyRuleKind,
    PolicySeverity,
    RegistrationRequiredParams,
    RequiredApprovalParams,
    RequiredAttestationParams,
    RequiredOwnerParams,
    ResidencyParams,
)
from neurosphere_contracts.policy.v1.policy_exception import PolicyException
from neurosphere_contracts.policy.v1.policy_violation import (
    PolicyViolation,
    PolicyViolationEvidence,
    Resolution,
)
from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "EVALUATED_KINDS",
    "LATER_KIND_OWNERS",
    "MAX_RULE_STATUSES",
    "MAX_SKIPPED_DOMAINS",
    "PARAMS_MODEL_BY_KIND",
    "POINTS_BY_RULE_KIND",
    "POLICY_SCHEMA_VERSION",
    "RULE_KINDS",
    "AllowedModel",
    "BudgetRuleParams",
    "ContentRuleParams",
    "DataSensitivityAccessParams",
    "EnforcementBinding",
    "EnforcementMode",
    "EnforcementModeName",
    "EnforcementPoint",
    "EnforcementPointName",
    "EvaluationRunState",
    "EvaluationStatus",
    "EvaluationTrigger",
    "ExceptionStatusName",
    "ModelAllowListParams",
    "PolicyAppliesTo",
    "PolicyDecisionMatch",
    "PolicyDecisionRequest",
    "PolicyDecisionResponse",
    "PolicyDefinition",
    "PolicyException",
    "PolicyRule",
    "PolicyRuleKind",
    "PolicySeverity",
    "PolicyStatusName",
    "PolicyViolation",
    "PolicyViolationEvidence",
    "RegistrationRequiredParams",
    "RequiredApprovalParams",
    "RequiredAttestationParams",
    "RequiredOwnerParams",
    "ResidencyParams",
    "Resolution",
    "RuleKindName",
    "RuleOutcomeName",
    "RuleParams",
    "RuleRunStatus",
    "TargetRef",
    "ViolationStatusName",
]

#: ``schema_version`` stamped on policy/v1 documents this engine writes.
POLICY_SCHEMA_VERSION: Final = "1.2.0"

RuleKindName = Literal[
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
EnforcementPointName = Literal[
    "gateway", "tool_call", "mcp_server", "mcp_client", "sdk", "budget", "registration"
]
EnforcementModeName = Literal["off", "audit", "enforce"]
PolicyStatusName = Literal["draft", "published", "retired"]
ViolationStatusName = Literal["open", "excepted", "resolved", "superseded"]
ExceptionStatusName = Literal["requested", "approved", "rejected", "expired", "revoked"]

RuleParams = (
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

#: The closed rule-kind list, in contract order (PRP-99 ``PolicyRuleKind``; a test pins it).
RULE_KINDS: Final[tuple[RuleKindName, ...]] = (
    "model_allow_list",
    "data_sensitivity_access",
    "residency",
    "budget",
    "required_owner",
    "required_attestation",
    "required_approval",
    "content_rule",
    "registration_required",
)

#: The seven kinds PRP-105 evaluates (clarification 2).
EVALUATED_KINDS: Final[frozenset[RuleKindName]] = frozenset(
    {
        "model_allow_list",
        "data_sensitivity_access",
        "residency",
        "required_owner",
        "required_approval",
        "registration_required",
        "content_rule",
    }
)

#: Kinds in the contract whose evaluator a later PRP registers through ``rule_plugins``.
LATER_KIND_OWNERS: Final[Mapping[str, str]] = MappingProxyType(
    {"budget": "PRP-115", "required_attestation": "PRP-130"}
)

#: kind -> the parameter model its ``params`` must validate against (the schema's allOf).
PARAMS_MODEL_BY_KIND: Final[Mapping[str, type[BaseModel]]] = MappingProxyType(
    {
        "model_allow_list": ModelAllowListParams,
        "data_sensitivity_access": DataSensitivityAccessParams,
        "residency": ResidencyParams,
        "budget": BudgetRuleParams,
        "required_owner": RequiredOwnerParams,
        "required_attestation": RequiredAttestationParams,
        "required_approval": RequiredApprovalParams,
        "content_rule": ContentRuleParams,
        "registration_required": RegistrationRequiredParams,
    }
)

#: Rule kind -> the enforcement points a binding for it may name (ASSUMPTION, runbook table).
#: An empty tuple means detective only: the worker records violations and nothing can block.
POINTS_BY_RULE_KIND: Final[Mapping[str, tuple[EnforcementPointName, ...]]] = MappingProxyType(
    {
        "model_allow_list": ("gateway", "sdk"),
        "data_sensitivity_access": ("tool_call", "mcp_server", "mcp_client", "sdk"),
        "residency": ("gateway", "sdk"),
        "budget": ("budget",),
        "required_owner": ("registration",),
        "required_attestation": ("registration",),
        "required_approval": ("registration",),
        "content_rule": (),
        "registration_required": ("registration",),
    }
)

EvaluationTrigger = Literal["interval", "due", "manual"]
EvaluationRunState = Literal["running", "completed", "truncated", "failed"]
RuleOutcomeName = Literal["complete", "truncated", "evaluator_unavailable", "failed", "skipped"]

_ReasonCode = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
_Slug = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")]
_Uuid = Annotated[
    str, Field(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
]
_Timestamp = Annotated[
    str, Field(pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,9})?Z$")
]
_DomainId = Annotated[str, Field(min_length=1, max_length=512, pattern=r"^[a-z0-9._:/=-]+$")]
_Count = Annotated[int, Field(ge=0, le=10_000_000)]

#: Bounds of one run-status document (a status that would exceed them is truncated by item 3).
MAX_RULE_STATUSES: Final = 2000
MAX_SKIPPED_DOMAINS: Final = 500


class RuleRunStatus(BaseModel):
    """Outcome of one rule in one run: ids, counts and a reason code, never content."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    policy_id: _Slug
    policy_version: Annotated[int, Field(ge=1)]
    rule_id: _Slug
    rule_kind: RuleKindName
    outcome: RuleOutcomeName
    reason_code: _ReasonCode | None = None
    subjects_evaluated: _Count = 0
    findings: _Count = 0
    violations_opened: _Count = 0
    violations_resolved: _Count = 0


class EvaluationStatus(BaseModel):
    """One policy evaluation run (``doc_kind: evaluation_status`` in ``policy_definitions``).

    ``domain_id`` is the partition the run status is filed under (the customer-control domain
    for a customer-wide run). ``state`` is ``truncated`` when any rule hit the subject or time
    budget: a truncated rule never resolves violations.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0.0"] = "1.0.0"
    run_id: _Uuid
    cloud: Literal["commercial", "government"]
    customer_id: Annotated[str, Field(max_length=128, pattern=r"^[a-z0-9._-]+$")]
    domain_id: _DomainId
    trigger: EvaluationTrigger
    state: EvaluationRunState
    started_at: _Timestamp
    finished_at: _Timestamp | None = None
    reason_code: _ReasonCode | None = None
    correlation_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9._-]{1,128}$")]
    rules: Annotated[tuple[RuleRunStatus, ...], Field(max_length=MAX_RULE_STATUSES)] = ()
    domains_evaluated: Annotated[tuple[_DomainId, ...], Field(max_length=MAX_SKIPPED_DOMAINS)] = ()
    domains_skipped: Annotated[tuple[_DomainId, ...], Field(max_length=MAX_SKIPPED_DOMAINS)] = ()
    subjects_evaluated: _Count = 0
    violations_opened: _Count = 0
    violations_resolved: _Count = 0
