"""Admin builder (PRP-39 item 2): the identity admin plane and the composed ``RevocationService``.

Components (both OPTIONAL; neither gates readiness):

* ``policy_admin``: the policy WRITE repository. ``backend("policy_admin_repository")`` (a
  ``PolicyAdminRepository``) wins; else, when the authz builder ran on an in-memory policy
  repository override (tests, local sandbox), an ``InMemoryPolicyAdminRepository`` over that
  same reader (so derivation sees admin writes); else ``CosmosPolicyAdminRepository`` on the ONE
  shared Cosmos client, container ``NS_AUTH_POLICY_CONTAINER`` (the container derivation reads).
* ``revocation_service``: the ``RevocationService`` PRP-06 built but nobody composed. Store =
  ``REVOCATION_STORE``; hooks = ``REVOCATION_HOOKS`` (the SAME registry object: the realtime
  builder's push-session closers and the checker/deriver invalidators are all on it);
  authorizer = the shipped ``ScopePermissionRevocationAuthorizer`` (Clarification 5); auditor =
  :class:`~neurosphere_api.admin.identity.plane.AuditRevocationAuditor` on ``AUDIT_REPOSITORY``
  (chain ``<customer>.identity-admin``); TTL = ``NS_REVOCATION_TTL_SECONDS``.

When authz did not publish the policy repository or the revocation store/hooks (authz disabled
or failed), the dependent component reports ``disabled`` and the reason code is logged
(``policy_repository_unavailable``, ``revocation_unavailable``). The plane is installed on
``app.state.identity_admin`` either way, so the routes fail closed with a 503 reason.

Runs LAST in ``default_builders``: it needs authz (policy, revocation) and data (audit).
"""

from __future__ import annotations

import logging
import time
from typing import Final

from neurosphere_core.auth.revocation import (
    RevocationService,
    ScopePermissionRevocationAuthorizer,
    load_revocation_settings,
)
from neurosphere_core.auth.scope import InMemoryPolicyRepository
from neurosphere_core.auth.scope.policy_admin import (
    CosmosPolicyAdminRepository,
    InMemoryPolicyAdminRepository,
    PolicyAdminRepository,
)
from pydantic import ValidationError

from neurosphere_api.admin.identity.plane import (
    AuditRevocationAuditor,
    CatalogResourceDomains,
    IdentityAdminPlane,
    ResourceDomainResolver,
    configure_identity_admin,
)
from neurosphere_api.runtime.builders import (
    AUDIT_REPOSITORY,
    CATALOG_REPOSITORY,
    POLICY_REPOSITORY,
    REVOCATION_HOOKS,
    REVOCATION_STORE,
    BuildContext,
    BuilderSpec,
    ComponentUnavailableError,
    SharedKey,
)

__all__ = [
    "BUILDER",
    "COMPONENTS",
    "POLICY_ADMIN_REPOSITORY",
    "REVOCATION_SERVICE",
    "build",
]

COMPONENTS: Final = ("policy_admin", "revocation_service")

#: The policy write repository (published for later admin builders, e.g. PRP-53 sandbox).
POLICY_ADMIN_REPOSITORY: Final[SharedKey[PolicyAdminRepository]] = SharedKey(
    "policy_admin_repository"
)
#: The ONE composed ``RevocationService`` (buttons, MCP and the admin API share it).
REVOCATION_SERVICE: Final[SharedKey[RevocationService]] = SharedKey("revocation_service")

_log = logging.getLogger("neurosphere_api.runtime")


def _policy_admin(ctx: BuildContext) -> PolicyAdminRepository:
    override = ctx.overrides.backend("policy_admin_repository")
    if override is not None:
        if not isinstance(override, PolicyAdminRepository):
            raise ComponentUnavailableError("policy_admin_override_invalid")
        return override
    reader = ctx.overrides.policy_repository
    if isinstance(reader, InMemoryPolicyRepository):
        return InMemoryPolicyAdminRepository(reader)
    return CosmosPolicyAdminRepository.from_client(
        ctx.cosmos_client(),
        database=ctx.store_settings().database,
        container=ctx.auth_settings().policy_container,
    )


def _revocation_service(ctx: BuildContext) -> RevocationService:
    try:
        settings = load_revocation_settings()
    except ValidationError:
        raise ComponentUnavailableError("revocation_settings_invalid") from None
    clock = ctx.overrides.clock or time.time
    return RevocationService(
        store=ctx.shared(REVOCATION_STORE),
        authorizer=ScopePermissionRevocationAuthorizer(clock=clock),
        auditor=AuditRevocationAuditor(lambda: ctx.maybe_shared(AUDIT_REPOSITORY)),
        hooks=ctx.shared(REVOCATION_HOOKS),
        ttl_seconds=settings.ttl_seconds,
        clock=clock,
    )


def _resource_domains(ctx: BuildContext) -> ResourceDomainResolver | None:
    override = ctx.overrides.backend("resource_domains")
    if isinstance(override, ResourceDomainResolver):
        return override
    catalog = ctx.maybe_shared(CATALOG_REPOSITORY)
    if catalog is None or not callable(getattr(catalog, "get_entity", None)):
        return None
    return CatalogResourceDomains(catalog)  # type: ignore[arg-type]


def build(ctx: BuildContext) -> None:
    policy_admin: PolicyAdminRepository | None = None
    if ctx.maybe_shared(POLICY_REPOSITORY) is None:
        _log.warning("component policy_admin disabled: policy_repository_unavailable")
        ctx.disabled("policy_admin")
    else:
        policy_admin = ctx.attempt("policy_admin", lambda: _policy_admin(ctx))
        if policy_admin is not None:
            ctx.publish(POLICY_ADMIN_REPOSITORY, policy_admin)

    revocation: RevocationService | None = None
    if ctx.maybe_shared(REVOCATION_STORE) is None or ctx.maybe_shared(REVOCATION_HOOKS) is None:
        _log.warning("component revocation_service disabled: revocation_unavailable")
        ctx.disabled("revocation_service")
    else:
        revocation = ctx.attempt("revocation_service", lambda: _revocation_service(ctx))
        if revocation is not None:
            ctx.publish(REVOCATION_SERVICE, revocation)

    configure_identity_admin(
        ctx.app,
        IdentityAdminPlane(
            policy_admin=policy_admin,
            policy_reader=ctx.maybe_shared(POLICY_REPOSITORY),
            revocation=revocation,
            audit=ctx.maybe_shared(AUDIT_REPOSITORY),
            resource_domains=_resource_domains(ctx),
            clock=ctx.overrides.clock or time.time,
        ),
    )


BUILDER: Final = BuilderSpec("admin", COMPONENTS, build)
