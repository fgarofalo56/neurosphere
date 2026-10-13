"""Server-side scope derivation (PRP-06 item 2): policy store, roles, grants, pseudonyms.

``ScopeDeriver.from_verified_claims`` is the derivation entry point. The PRP-05 ``IdentityScope``
holder is not edited here, so the classmethod spelling ``IdentityScope.from_verified_claims`` is
provided by the deriver (it needs the injected policy store, pseudonym key and clock).
"""

from neurosphere_core.auth.scope.cache import TtlCache
from neurosphere_core.auth.scope.cosmos_repository import (
    DEFAULT_POLICY_CONTAINER,
    CosmosPolicyRepository,
)
from neurosphere_core.auth.scope.derivation import (
    DEFAULT_POLICY_CACHE_TTL_SECONDS,
    DEFAULT_SCOPE_TTL_SECONDS,
    DEFAULT_STORE_TIMEOUT_SECONDS,
    ScopeDerivation,
    ScopeDerivationConfig,
    ScopeDeriver,
)
from neurosphere_core.auth.scope.hashing import canonical_json, compute_scope_hash
from neurosphere_core.auth.scope.memory import InMemoryPolicyRepository
from neurosphere_core.auth.scope.permissions import (
    GRANT_PERMISSIONS,
    PRIVILEGED_ROLES,
    ROLE_PERMISSIONS,
    GrantPermission,
    Permission,
    Role,
    domains_with_permission,
    permits,
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
from neurosphere_core.auth.scope.revocation_hook import RevocationChecker

__all__ = [
    "DEFAULT_POLICY_CACHE_TTL_SECONDS",
    "DEFAULT_POLICY_CONTAINER",
    "DEFAULT_SCOPE_TTL_SECONDS",
    "DEFAULT_STORE_TIMEOUT_SECONDS",
    "GRANT_PERMISSIONS",
    "NO_POLICY_VERSION",
    "POLICY_HEAD_ID",
    "PRIVILEGED_ROLES",
    "ROLE_PERMISSIONS",
    "CosmosPolicyRepository",
    "GrantPermission",
    "InMemoryPolicyRepository",
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
    "domains_with_permission",
    "permits",
    "principal_document_id",
    "role_permissions",
]
