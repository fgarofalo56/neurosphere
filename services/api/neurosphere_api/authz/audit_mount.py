"""Adapter that mounts item 4's audit router behind :func:`require` (PRP-06 item 3).

Item 4's ``neurosphere_api.audit.register(registry, require_permission=...)`` expects a factory
``(permission: str) -> dependency``. :func:`audit_require_permission` returns one:

* Permission strings map to platform permissions. ``audit.read`` and ``audit.verify`` both map to
  ``Permission.AUDIT_READ`` (the fixed role table has no separate verify permission; verifying a
  chain is reading it). An unknown string fails at mount time, never at request time.
* Chain confinement: the ``chain_id`` path parameter must be ``<customer_id>.<rest>`` with the
  caller's ``customer_id`` as the first ``.``-separated segment and a non-empty rest (no
  customer-wide chain); anything else is 403 ``audit_chain_out_of_scope``. A customer id that
  itself contains ``.`` therefore matches no chain (fails closed, never wider).
* Domain confinement is mandatory: ``chain_domain`` is a required function mapping
  ``(scope, chain_id)`` to the canonical domain id the chain belongs to (or ``None`` = deny), and
  the permission is checked on that domain with :func:`permits`. There is deliberately no
  customer-level fallback: a caller holding ``audit.read`` in one domain must never read another
  domain's chain. :func:`domain_from_chain_id` inverts the shared chain encoding
  (``neurosphere_core.audit.chains``): ``<customer_id>.<name>`` is the ``catalog`` domain
  ``<name>``, ``<customer_id>._<n>.<source>.<name>`` is that source's domain; chains that are not
  an exact encoding map to ``None`` and are denied.

The route inventory sees these dependencies as permission declarations (same marker).
"""

# No ``from __future__ import annotations`` here: FastAPI resolves string annotations against
# module globals, and the dependency below closes over a local (``base``) in its annotation.

from collections.abc import Callable, Mapping
from types import MappingProxyType
from typing import Final

from fastapi import Request
from neurosphere_core.audit.chains import domain_from_audit_chain
from neurosphere_core.auth.scope import Permission
from neurosphere_core.errors import ForbiddenError, InvalidSchemaError
from neurosphere_core.scope import IdentityScope

from neurosphere_api.authz.dependencies import (
    AuthzTarget,
    PermissionDependency,
    ResourceResolver,
    require,
)

__all__ = [
    "AUDIT_PERMISSIONS",
    "ChainDomainMapper",
    "audit_require_permission",
    "domain_from_chain_id",
]

#: Item 4 permission strings -> platform permissions.
AUDIT_PERMISSIONS: Final[Mapping[str, Permission]] = MappingProxyType(
    {
        "audit.read": Permission.AUDIT_READ,
        "audit.verify": Permission.AUDIT_READ,
    }
)

ChainDomainMapper = Callable[[IdentityScope, str], str | None]
_CHAIN_PARAM: Final = "chain_id"


def _chain_id(request: Request, scope: IdentityScope) -> str:
    value = request.path_params.get(_CHAIN_PARAM)
    chain_id = value if isinstance(value, str) else ""
    head, dot, rest = chain_id.partition(".")
    if head != scope.customer_id or not dot or not rest:
        raise ForbiddenError(
            "audit chain is outside the caller's scope", reason="audit_chain_out_of_scope"
        )
    return chain_id


def _chain_target(mapper: ChainDomainMapper) -> ResourceResolver:
    def resolve(request: Request, scope: IdentityScope) -> AuthzTarget | None:
        domain_id = mapper(scope, _chain_id(request, scope))
        return AuthzTarget(domain_id=domain_id) if domain_id else None

    return resolve


def domain_from_chain_id(scope: IdentityScope, chain_id: str) -> str | None:
    """The one domain id whose audit chain is exactly ``chain_id`` (PRP-31 item 14b).

    Delegates to :func:`neurosphere_core.audit.domain_from_audit_chain` with the scope's own cloud
    and customer. The mapping never consults the caller's grants: ``<customer>.<name>`` is the
    ``catalog`` domain ``<name>``, ``<customer>._<n>.<source>.<name>`` is that source's domain, and
    anything else is ``None`` (deny). The ``audit.read`` check on the returned domain decides.

    Legacy limitation: records written before item 14b for a non-catalog domain sit on its old
    ``<customer>.<name>`` chain, which maps to the catalog domain ``<name>``. A holder of only the
    non-catalog domain cannot read them through these routes (as before item 14b).
    """
    return domain_from_audit_chain(str(scope.cloud), scope.customer_id, chain_id)


def audit_require_permission(
    *, chain_domain: ChainDomainMapper
) -> Callable[[str], PermissionDependency]:
    """Factory for ``neurosphere_api.audit.register(..., require_permission=<this result>)``."""

    def factory(permission: str) -> PermissionDependency:
        perm = AUDIT_PERMISSIONS.get(permission)
        if perm is None:
            raise InvalidSchemaError("unknown audit permission", reason="config")
        return require(perm, resource=_chain_target(chain_domain))

    return factory
