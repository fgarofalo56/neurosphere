"""Authorization dependencies for the API (PRP-06 item 3).

Public API:

* :func:`configure_authz` -- install the token validator and scope deriver on ``app.state``.
* :func:`current_scope` / :func:`current_derivation` -- the caller's server-derived scope.
* :func:`require` -- per-route permission dependency (403 / 503, never allow on error).
* :func:`route_inventory`, :func:`undeclared_routes`, :func:`verify_route_permissions` --
  every non-public route must declare a permission.
* :func:`scope_cache_key` -- cache keys from the scope hash, never from token material.
* :func:`audit_require_permission` -- mounts item 4's audit router behind ``require``.
"""

from neurosphere_api.authz.audit_mount import (
    AUDIT_PERMISSIONS,
    ChainDomainMapper,
    audit_require_permission,
)
from neurosphere_api.authz.cache_key import cache_key_prefix, scope_cache_key
from neurosphere_api.authz.dependencies import (
    PERMISSION_MARKER,
    AuthzTarget,
    PermissionDependency,
    ResourceResolver,
    current_derivation,
    current_scope,
    domain_from_path,
    require,
    resource_from_path,
)
from neurosphere_api.authz.recorder import SAFE_METHODS, DenialRecorder, DeniedAttempt
from neurosphere_api.authz.routes import (
    PUBLIC_PATHS,
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
    "DEFAULT_AUTHZ_TIMEOUT_SECONDS",
    "PERMISSION_MARKER",
    "PUBLIC_PATHS",
    "SAFE_METHODS",
    "AuthzState",
    "AuthzTarget",
    "ChainDomainMapper",
    "DenialRecorder",
    "DeniedAttempt",
    "PermissionDependency",
    "ResourceResolver",
    "RouteEntry",
    "ScopeSource",
    "TokenAuthenticator",
    "audit_require_permission",
    "cache_key_prefix",
    "configure_authz",
    "current_derivation",
    "current_scope",
    "domain_from_path",
    "get_authz_state",
    "public_paths_for",
    "require",
    "resource_from_path",
    "route_inventory",
    "scope_cache_key",
    "undeclared_routes",
    "verify_route_permissions",
]
