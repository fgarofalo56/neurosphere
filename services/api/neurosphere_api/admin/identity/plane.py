"""Composed dependencies of the identity admin API (PRP-39 item 2).

``runtime/builders/admin.py`` builds one :class:`IdentityAdminPlane` and installs it on
``app.state.identity_admin``. Members are optional so the two components fail independently:
the policy routes answer 503 ``policy_admin_unconfigured`` without a policy write repository,
the revocation routes 503 ``revocation_service_unconfigured`` without a revocation service.

:class:`AuditRevocationAuditor` adapts the core ``RevocationAuditor`` port onto the append-only
``AuditRepository``: every revocation event lands on the customer chain
``<customer>.identity-admin`` (derived from the actor's pseudonymous id, never from input).
"""

from __future__ import annotations

import contextvars
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final, Protocol, runtime_checkable

from fastapi import FastAPI, Request
from neurosphere_core.audit import (
    AuditContext,
    AuditDraft,
    AuditRepository,
    build_after,
    build_before,
    build_denied,
    make_subject,
)
from neurosphere_core.auth.revocation import (
    RevocationAuditEvent,
    RevocationHookRegistry,
    RevocationService,
)
from neurosphere_core.auth.scope import PolicyRepository
from neurosphere_core.auth.scope.policy_admin import PolicyAdminRepository
from neurosphere_core.errors import DependencyTransientError
from neurosphere_core.scope import IdentityScope

__all__ = [
    "IDENTITY_ADMIN_CHAIN_NAME",
    "STATE_ATTRIBUTE",
    "AuditRevocationAuditor",
    "CatalogResourceDomains",
    "IdentityAdminPlane",
    "ResourceDomainResolver",
    "bind_correlation",
    "configure_identity_admin",
    "get_plane",
    "identity_admin_chain",
]

STATE_ATTRIBUTE: Final = "identity_admin"
#: Customer-level chain for revocation records (``<customer>.identity-admin``).
IDENTITY_ADMIN_CHAIN_NAME: Final = "identity-admin"

_CORRELATION: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "identity_admin_correlation", default=None
)


@runtime_checkable
class ResourceDomainResolver(Protocol):
    """The domain that owns a catalog resource, as visible to ``scope`` (``None`` if not)."""

    async def domain_of(self, scope: IdentityScope, resource_id: str) -> str | None: ...


class _EntityReader(Protocol):
    async def get_entity(self, scope: IdentityScope, entity_id: str) -> object | None: ...


class CatalogResourceDomains:
    """:class:`ResourceDomainResolver` over the catalog repository (scope-filtered reads)."""

    def __init__(self, catalog: _EntityReader) -> None:
        self._catalog = catalog

    async def domain_of(self, scope: IdentityScope, resource_id: str) -> str | None:
        entity = await self._catalog.get_entity(scope, resource_id)
        if entity is None:
            return None
        domain = getattr(entity, "domain_id", None)
        value = getattr(domain, "root", domain)
        return value if isinstance(value, str) else None


def identity_admin_chain(customer_id: str) -> str:
    return f"{customer_id}.{IDENTITY_ADMIN_CHAIN_NAME}"


def bind_correlation(correlation_id: str) -> contextvars.Token[str | None]:
    """Bind the request's audit correlation id for revocation records written in this task."""
    return _CORRELATION.set(correlation_id)


def _correlation() -> str:
    return _CORRELATION.get() or f"corr-{uuid.uuid4().hex}"


class AuditRevocationAuditor:
    """``RevocationAuditor`` writing metadata-only records (C11) to the audit repository.

    ``denied`` -> a denied record; ``intent`` -> a before record; ``outcome`` -> an after record
    (``verified`` when every fan-out hook succeeded, detail ``mode=<mode>``); ``failed`` -> an
    after record with result ``failed`` and the error code. A write failure raises, so the
    service fails closed exactly as ``run_audited_mutation`` does.
    """

    def __init__(self, repository: Callable[[], AuditRepository | None]) -> None:
        self._repository = repository

    async def record(self, event: RevocationAuditEvent) -> None:
        repository = self._repository()
        if repository is None:
            raise DependencyTransientError(
                "audit store is not configured", reason="audit_store_unconfigured"
            )
        customer = event.actor_principal_id.split(":")[1]
        await repository.append(identity_admin_chain(customer), _draft(event))


def _draft(event: RevocationAuditEvent) -> AuditDraft:
    principal_kind = "user" if ":person:" in event.actor_principal_id else "service_principal"
    ctx = AuditContext.model_validate(
        {
            "actor": {
                "principal_pseudonym": event.actor_principal_id.rsplit(":", 1)[-1],
                "principal_kind": principal_kind,
                "on_behalf_of": None,
            },
            "scope_hash": event.actor_scope_hash,
            "correlation_id": _correlation(),
            "operation": event.action,
            "channel": "rest",
        }
    )
    target_type = event.target_principal_id.split(":")[3]
    state = {
        "mode": event.mode,
        "revoked_at": None if event.revoked_at is None else event.revoked_at.isoformat(),
        "reason": event.reason,
    }
    subject = make_subject(event.target_principal_id, target_type, state=state)
    if event.phase == "denied":
        return build_denied(
            ctx, code="forbidden", reason=event.deny_reason or "forbidden", subject=subject
        )
    if event.phase == "intent":
        return build_before(ctx, subject)
    if event.phase == "failed":
        return build_after(
            ctx,
            subject,
            result="failed",
            verified=False,
            detail=event.error_code or "dependency_transient",
        )
    verified = event.fanout.complete if event.fanout is not None else False
    detail = f"mode={event.mode}" if event.mode is not None else None
    return build_after(ctx, subject, result="succeeded", verified=verified, detail=detail)


@dataclass(frozen=True, slots=True)
class IdentityAdminPlane:
    """What the identity admin routes need. ``None`` members fail their routes closed (503)."""

    policy_admin: PolicyAdminRepository | None
    policy_reader: PolicyRepository | None
    revocation: RevocationService | None
    audit: AuditRepository | None
    resource_domains: ResourceDomainResolver | None
    clock: Callable[[], float]
    #: ``REVOCATION_HOOKS``: a policy write calls its cache invalidators for the target.
    cache_hooks: RevocationHookRegistry | None = None


def configure_identity_admin(app: FastAPI, plane: IdentityAdminPlane) -> None:
    setattr(app.state, STATE_ATTRIBUTE, plane)


def get_plane(request: Request) -> IdentityAdminPlane:
    plane = getattr(request.app.state, STATE_ATTRIBUTE, None)
    if not isinstance(plane, IdentityAdminPlane):
        raise DependencyTransientError(
            "identity administration is not configured", reason="identity_admin_unconfigured"
        )
    return plane
