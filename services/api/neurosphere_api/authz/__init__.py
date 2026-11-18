"""Authorization dependencies for the API (PRP-06 item 3).

Public API:

* :func:`configure_authz` -- install the token validator and scope deriver on ``app.state``.
* :func:`current_scope` / :func:`current_derivation` -- the caller's server-derived scope.
* :func:`require` -- per-route permission dependency (403 / 503, never allow on error).
* :func:`require_role` -- role-gated route dependency (PRP-48 item 1; ``ROLE_GATED_PATHS``).
* :func:`require_authenticated` -- authenticated-self route dependency (PRP-138;
  ``AUTHENTICATED_SELF_PATHS``): a valid token and a derived scope, no permission.
* :class:`ClaimGrantAuditObserver` -- audits roles applied from the Entra claim mapping.
* :func:`route_inventory`, :func:`undeclared_routes`, :func:`verify_route_permissions` --
  every non-public route must declare a permission.
* :func:`scope_cache_key` -- cache keys from the scope hash, never from token material.
* :func:`audit_require_permission` -- mounts item 4's audit router behind ``require``.
"""

from neurosphere_api.authz.audit_mount import (
    AUDIT_PERMISSIONS,
    ChainDomainMapper,
    audit_require_permission,
    domain_from_chain_id,
)
from neurosphere_api.authz.cache_key import cache_key_prefix, scope_cache_key
from neurosphere_api.authz.claim_audit import (
    CLAIM_ROLE_APPLIED_OPERATION,
    ClaimGrantAuditObserver,
    ClaimMappingStats,
    claim_mapping_stats,
)
from neurosphere_api.authz.dependencies import (
    AUTHENTICATED_MARKER,
    GROUPS_OVERAGE_ATTRIBUTE,
    PERMISSION_MARKER,
    ROLE_MARKER,
    ROLE_NOT_HELD,
    AuthzTarget,
    PermissionDependency,
    ResourceResolver,
    RoleResolver,
    current_derivation,
    current_scope,
    domain_from_path,
    groups_overage_of,
    holds_role,
    require,
    require_authenticated,
    require_role,
    resource_from_path,
)
from neurosphere_api.authz.deployment_scope import (
    CUSTOMER_SCOPE_REQUIRED,
    DEPLOYMENT_ADMIN_MARKER,
    require_deployment_admin,
)
from neurosphere_api.authz.recorder import SAFE_METHODS, DenialRecorder, DeniedAttempt
from neurosphere_api.authz.routes import (
    AUTHENTICATED_SELF_PATHS,
    PRODUCER_AUTHENTICATED_PATHS,
    PUBLIC_PATHS,
    ROLE_GATED_PATHS,
    RouteEntry,
    public_paths_for,
    route_inventory,
    undeclared_routes,
    verify_route_permissions,
)
from neurosphere_api.authz.state import (
    DEFAULT_AUTHZ_TIMEOUT_SECONDS,
    AuthzState,
    ScopeSource,
    TokenAuthenticator,
    configure_authz,
    get_authz_state,
)

__all__ = [
    "AUDIT_PERMISSIONS",
    "AUTHENTICATED_MARKER",
    "AUTHENTICATED_SELF_PATHS",
    "CLAIM_ROLE_APPLIED_OPERATION",
    "CUSTOMER_SCOPE_REQUIRED",
    "DEFAULT_AUTHZ_TIMEOUT_SECONDS",
    "DEPLOYMENT_ADMIN_MARKER",
    "GROUPS_OVERAGE_ATTRIBUTE",
    "PERMISSION_MARKER",
    "PRODUCER_AUTHENTICATED_PATHS",
    "PUBLIC_PATHS",
    "ROLE_GATED_PATHS",
    "ROLE_MARKER",
    "ROLE_NOT_HELD",
    "SAFE_METHODS",
    "AuthzState",
    "AuthzTarget",
    "ChainDomainMapper",
    "ClaimGrantAuditObserver",
    "ClaimMappingStats",
    "DenialRecorder",
    "DeniedAttempt",
    "PermissionDependency",
    "ResourceResolver",
    "RoleResolver",
    "RouteEntry",
    "ScopeSource",
    "TokenAuthenticator",
    "audit_require_permission",
    "cache_key_prefix",
    "claim_mapping_stats",
    "configure_authz",
    "current_derivation",
    "current_scope",
    "domain_from_chain_id",
    "domain_from_path",
    "get_authz_state",
    "groups_overage_of",
    "holds_role",
    "public_paths_for",
    "require",
    "require_authenticated",
    "require_deployment_admin",
    "require_role",
    "resource_from_path",
    "route_inventory",
    "scope_cache_key",
    "undeclared_routes",
    "verify_route_permissions",
]
