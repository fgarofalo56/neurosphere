"""Customer-level authorization for the execution kill switch (PRP-17 audit close-out).

The kill switch (``PUT /api/v1/actions/emergency-disable``) acts on the WHOLE customer, so
holding ``config.manage`` in some domain is not enough: a single-domain admin must not be able to
re-enable execution customer-wide.

Since PRP-48 item 3 (#114) the check is the shared deployment-scoped admin dependency
:func:`neurosphere_api.authz.deployment_scope.require_deployment_admin`, built on PRP-65's
``customer_control_domain_id`` / ``permits_customer_wide``: the permission held on ONE reserved
control domain per customer,

    ``<cloud>:<customer>:neurosphere:domain:customer-control``

granted like any other domain role (membership plus a time-bound ``admin`` assignment), so it is
explicit, audited in the policy store, time-bound (``admin`` is privileged, C7) and revocable, and
it inherits every derivation rule (cloud and customer binding, expiry, revocation).

:func:`require_customer_control` is kept as the name existing routers import (kill switch,
connectors, producers, lifecycle); it delegates and adds nothing. Order of checks, denial record
and the 503 ``audit_write_failed`` on a recorder failure are documented on
:mod:`neurosphere_api.authz.deployment_scope`. A miss is 403 ``forbidden`` reason
``customer_scope_required``. Disabling and re-enabling use the same route, hence the same check.
"""

from collections.abc import Awaitable, Callable

from neurosphere_core.auth.scope import (
    CUSTOMER_CONTROL_DOMAIN_NAME,
    CUSTOMER_CONTROL_SOURCE,
    Permission,
    customer_control_domain_id,
)
from neurosphere_core.scope import IdentityScope

from neurosphere_api.authz.deployment_scope import (
    CUSTOMER_SCOPE_REQUIRED,
    require_deployment_admin,
)

__all__ = [
    "CUSTOMER_CONTROL_DOMAIN_NAME",
    "CUSTOMER_CONTROL_SOURCE",
    "CUSTOMER_SCOPE_REQUIRED",
    "customer_control_domain",
    "require_customer_control",
]


def customer_control_domain(cloud: str, customer_id: str) -> str:
    """Canonical id of the reserved control domain of ``customer_id`` in ``cloud``."""
    return customer_control_domain_id(cloud, customer_id)


def require_customer_control(
    permission: Permission = Permission.CONFIG_MANAGE,
) -> Callable[..., Awaitable[IdentityScope]]:
    """Dependency: ``permission`` held on the caller's customer control domain.

    Delegates to :func:`~neurosphere_api.authz.deployment_scope.require_deployment_admin`.
    """
    return require_deployment_admin(permission)
