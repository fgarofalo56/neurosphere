"""Governance policy engine (PRP-105).

A policy is a versioned, declarative document of typed rules from a closed list (PRP-99
``policy/v1``). There is no expression language and no generated code: nothing in this package
compiles, evaluates or templates rule text (``tests/governance_policy/test_no_generated_code.py``).

Modules: :mod:`.models` (contract re-exports and core tables), :mod:`.validation` (draft
validation), :mod:`.ids` (dedup keys, canonical ids, chain id), :mod:`.capabilities` (what each
enforcement point can block), :mod:`.store` (store protocols, typed errors and the shared store
logic), :mod:`.memory_store` and :mod:`.cosmos_store` (the two backends).
"""

from neurosphere_core.governance.policy.capabilities import (
    DETECTIVE_EVALUATION_CAN_BLOCK,
    ENFORCEMENT_POINT_CAPABILITIES,
    PointCapability,
)
from neurosphere_core.governance.policy.cosmos_store import (
    CosmosBindingStore,
    CosmosEvaluationStatusStore,
    CosmosExceptionStore,
    CosmosPolicyDefinitionStore,
    CosmosViolationStore,
    create_policy_containers,
)
from neurosphere_core.governance.policy.ids import (
    binding_id_for,
    dedup_key,
    exception_canonical_id,
    governance_policy_canonical_id,
    governance_policy_chain_id,
    policy_entity_canonical_id,
    violation_canonical_id,
    violation_id_for,
)
from neurosphere_core.governance.policy.memory_store import (
    InMemoryBindingStore,
    InMemoryDocumentBackend,
    InMemoryEvaluationStatusStore,
    InMemoryExceptionStore,
    InMemoryPolicyDefinitionStore,
    InMemoryViolationStore,
)
from neurosphere_core.governance.policy.models import (
    EVALUATED_KINDS,
    PARAMS_MODEL_BY_KIND,
    POINTS_BY_RULE_KIND,
    POLICY_SCHEMA_VERSION,
    RULE_KINDS,
    EvaluationStatus,
    RuleRunStatus,
)
from neurosphere_core.governance.policy.store import (
    BindingStore,
    EvaluationStatusStore,
    ExceptionFilters,
    ExceptionStore,
    GovernancePolicyNotFoundError,
    GovernancePolicyStaleError,
    ObservedViolation,
    PolicyDefinitionStore,
    PolicyPublishedError,
    StoredBinding,
    StoredEvaluationStatus,
    StoredException,
    StoredPolicy,
    StoredViolation,
    ViolationFilters,
    ViolationObservation,
    ViolationStore,
)
from neurosphere_core.governance.policy.validation import (
    PolicyValidationError,
    rules_digest,
    validate_draft,
    validate_policy,
)

__all__ = [
    "DETECTIVE_EVALUATION_CAN_BLOCK",
    "ENFORCEMENT_POINT_CAPABILITIES",
    "EVALUATED_KINDS",
    "PARAMS_MODEL_BY_KIND",
    "POINTS_BY_RULE_KIND",
    "POLICY_SCHEMA_VERSION",
    "RULE_KINDS",
    "BindingStore",
    "CosmosBindingStore",
    "CosmosEvaluationStatusStore",
    "CosmosExceptionStore",
    "CosmosPolicyDefinitionStore",
    "CosmosViolationStore",
    "EvaluationStatus",
    "EvaluationStatusStore",
    "ExceptionFilters",
    "ExceptionStore",
    "GovernancePolicyNotFoundError",
    "GovernancePolicyStaleError",
    "InMemoryBindingStore",
    "InMemoryDocumentBackend",
    "InMemoryEvaluationStatusStore",
    "InMemoryExceptionStore",
    "InMemoryPolicyDefinitionStore",
    "InMemoryViolationStore",
    "ObservedViolation",
    "PointCapability",
    "PolicyDefinitionStore",
    "PolicyPublishedError",
    "PolicyValidationError",
    "RuleRunStatus",
    "StoredBinding",
    "StoredEvaluationStatus",
    "StoredException",
    "StoredPolicy",
    "StoredViolation",
    "ViolationFilters",
    "ViolationObservation",
    "ViolationStore",
    "binding_id_for",
    "create_policy_containers",
    "dedup_key",
    "exception_canonical_id",
    "governance_policy_canonical_id",
    "governance_policy_chain_id",
    "policy_entity_canonical_id",
    "rules_digest",
    "validate_draft",
    "validate_policy",
    "violation_canonical_id",
    "violation_id_for",
]
