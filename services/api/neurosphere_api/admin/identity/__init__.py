"""Identity admin API (PRP-39), mounted at ``/api/v1/admin/identity``.

Who has access and changing it: principals (pseudonymous ids only), role assignments, domain
memberships and resource-scoped grants (``policy.manage``), and principal revocation
(``revocation.manage``). See ``router`` for the route table, ``service`` for the order of checks
and ``revocation`` for the revoke / lift routes. The first admin is still bootstrapped by
``make grant-operator``; this API needs an existing admin (Clarification 6).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from neurosphere_api.admin.identity.plane import (
    STATE_ATTRIBUTE,
    IdentityAdminPlane,
    configure_identity_admin,
)

if TYPE_CHECKING:
    from neurosphere_api.routers import RouterRegistry

__all__ = [
    "PREFIX",
    "STATE_ATTRIBUTE",
    "IdentityAdminPlane",
    "configure_identity_admin",
    "register",
]

PREFIX = "/api/v1/admin/identity"


def register(registry: RouterRegistry) -> None:
    """Router-registry hook: the policy and revocation routes share one prefix."""
    from neurosphere_api.admin.identity.revocation import build_router as revocation_router
    from neurosphere_api.admin.identity.router import build_router

    router = build_router()
    router.include_router(revocation_router())
    registry.register(PREFIX, router)
