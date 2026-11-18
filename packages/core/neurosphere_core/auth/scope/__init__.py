"""Server-side scope derivation (PRP-06 item 2): policy store, roles, grants, pseudonyms.

``ScopeDeriver.from_verified_claims`` is the derivation entry point. The PRP-05 ``IdentityScope``
holder is not edited here, so the classmethod spelling ``IdentityScope.from_verified_claims`` is
provided by the deriver (it needs the injected policy store, pseudonym key and clock).
"""

from neurosphere_core.auth.scope.cache import TtlCache
from neurosphere_core.auth.scope.claim_mapping import (
    MAPPABLE_ROLES,
    MAPPED_ISSUER_KINDS,
    MAX_MAPPING_ENTRIES,
    ClaimGrant,
    ClaimGrantObserver,
    ClaimKind,
    ClaimRoleEntry,
    ClaimRoleMapping,
    ClaimRoleMappingError,
    DomainDirectory,
    matching_entries,
    parse_claim_role_mapping,
)
from neurosphere_core.auth.scope.cosmos_repository import (
    DEFAULT_POLICY_CONTAINER,
    CosmosPolicyRepository,
)
from neurosphere_core.auth.scope.derivation import (
    DEFAULT_POLICY_CACHE_TTL_SECONDS,
    DEFAULT_SCOPE_TTL_SECONDS,
    DEFAULT_STORE_TIMEOUT_SECONDS,
    MAPPED_ASSIGNMENT_PREFIX,
    MAX_ALL_DOMAINS,
    ScopeDerivation,
    ScopeDerivationConfig,
    ScopeDeriver,
)
from neurosphere_core.auth.scope.hashing import canonical_json, compute_scope_hash
from neurosphere_core.auth.scope.memory import InMemoryPolicyRepository
from neurosphere_core.auth.scope.permissions import (
    CUSTOMER_CONTROL_DOMAIN_NAME,
    CUSTOMER_CONTROL_SOURCE,
    GRANT_PERMISSIONS,
    PRIVILEGED_ROLES,
    ROLE_PERMISSIONS,
    GrantPermission,
    Permission,
    Role,
    customer_control_domain_id,
    domains_with_permission,
    permits,
    permits_customer_wide,
    role_permissions,
)
from neurosphere_core.auth.scope.policy import (
    NO_POLICY_VERSION,
    POLICY_HEAD_ID,
    PolicyGrant,
    PolicyHead,
    PolicyRepository,
    PolicyRoleAssignment,
    PrincipalPolicy,
    principal_document_id,
)
from neurosphere_core.auth.scope.pseudonym import (
    PrincipalKind,
    PrincipalPseudonymizer,
    PseudonymKey,
)
from neurosphere_core.auth.scope.revocation_hook import NoRevocationCheck, RevocationChecker

__all__ = [
    "CUSTOMER_CONTROL_DOMAIN_NAME",
    "CUSTOMER_CONTROL_SOURCE",
    "DEFAULT_POLICY_CACHE_TTL_SECONDS",
    "DEFAULT_POLICY_CONTAINER",
    "DEFAULT_SCOPE_TTL_SECONDS",
    "DEFAULT_STORE_TIMEOUT_SECONDS",
    "GRANT_PERMISSIONS",
    "MAPPABLE_ROLES",
    "MAPPED_ASSIGNMENT_PREFIX",
    "MAPPED_ISSUER_KINDS",
    "MAX_ALL_DOMAINS",
    "MAX_MAPPING_ENTRIES",
    "NO_POLICY_VERSION",
    "POLICY_HEAD_ID",
    "PRIVILEGED_ROLES",
    "ROLE_PERMISSIONS",
    "ClaimGrant",
    "ClaimGrantObserver",
    "ClaimKind",
    "ClaimRoleEntry",
    "ClaimRoleMapping",
    "ClaimRoleMappingError",
    "CosmosPolicyRepository",
    "DomainDirectory",
    "GrantPermission",
    "InMemoryPolicyRepository",
    "NoRevocationCheck",
    "Permission",
    "PolicyGrant",
    "PolicyHead",
    "PolicyRepository",
    "PolicyRoleAssignment",
    "PrincipalKind",
    "PrincipalPolicy",
    "PrincipalPseudonymizer",
    "PseudonymKey",
    "RevocationChecker",
    "Role",
    "ScopeDerivation",
    "ScopeDerivationConfig",
    "ScopeDeriver",
    "TtlCache",
    "canonical_json",
    "compute_scope_hash",
    "customer_control_domain_id",
    "domains_with_permission",
    "matching_entries",
    "parse_claim_role_mapping",
    "permits",
    "permits_customer_wide",
    "principal_document_id",
    "role_permissions",
]
