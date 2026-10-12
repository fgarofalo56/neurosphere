"""Admin revoke operation: permissioned, audited, then fanned out (PRP-06 item 5).

Permission and audit arrive through injected protocols (``RevocationAuthorizer``,
``RevocationAuditor``) so this package imports nothing from ``services/**`` or ``audit/``; the
API layer adapts them to ``require(permission)`` and the audit repository. Order of ``revoke``:

1. Input check: the target must be a canonical pseudonymous principal id and the reason a
   machine reason code (else ``invalid_schema``; raw values are never echoed or audited, they
   may hold a UPN or free text).
2. Authorization: the authorizer must return exactly ``True``. ``False``/anything else or
   ``forbidden`` -> a ``denied`` audit event, then ``forbidden``. ``dependency_transient``
   propagates; any other error becomes ``dependency_transient``. Never an allow on error.
3. ``intent`` audit event. If it cannot be written the revocation is not attempted.
4. Store write ("latest revocation wins"). Failure -> best-effort ``failed`` audit event, then
   ``dependency_transient``. The store is written BEFORE fan-out so a push session closed in
   step 5 cannot reconnect with its old token.
5. Fan-out to every cache invalidator and push registry (never raises; failures are reported).
6. ``outcome`` audit event; if it cannot be written the error propagates (the revocation has
   happened; the caller must surface the failure, as ``run_audited_mutation`` does).

Other replicas pick the revocation up within ``NS_REVOCATION_TTL_SECONDS`` (see ``model``):
revocation is bounded by that TTL, not instant.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Final, Literal, Protocol, runtime_checkable

from neurosphere_core.auth.jwt import Clock
from neurosphere_core.auth.revocation.fanout import FanoutReport, RevocationHookRegistry
from neurosphere_core.auth.revocation.model import (
    DEFAULT_REVOCATION_TTL_SECONDS,
    RevocationEntry,
    is_canonical_principal_id,
    is_reason_code,
)
from neurosphere_core.auth.revocation.store import RevocationStore
from neurosphere_core.auth.scope.permissions import Permission, domains_with_permission
from neurosphere_core.errors import (
    DependencyTransientError,
    ForbiddenError,
    InvalidSchemaError,
    NeuroSphereError,
    ValidationIssue,
)
from neurosphere_core.scope import IdentityScope

__all__ = [
    "REVOKE_ACTION",
    "AuditPhase",
    "RevocationAuditEvent",
    "RevocationAuditor",
    "RevocationAuthorizer",
    "RevocationOutcome",
    "RevocationService",
    "ScopePermissionRevocationAuthorizer",
]

_log = logging.getLogger(__name__)

REVOKE_ACTION: Final = "principal.revoke"
AuditPhase = Literal["denied", "intent", "outcome", "failed"]


@runtime_checkable
class RevocationAuthorizer(Protocol):
    async def authorize_revocation(self, actor: IdentityScope, target_principal_id: str) -> bool:
        """Return ``True`` to allow. Anything else, or ``forbidden``, denies."""
        ...


@dataclass(frozen=True, slots=True)
class RevocationAuditEvent:
    """Metadata only (C11): pseudonymous ids, codes, counts. No tokens, names or UPNs."""

    action: str
    phase: AuditPhase
    actor_principal_id: str
    actor_scope_hash: str
    target_principal_id: str
    reason: str
    revoked_at: datetime | None = None
    deny_reason: str | None = None
    error_code: str | None = None
    fanout: FanoutReport | None = None


@runtime_checkable
class RevocationAuditor(Protocol):
    async def record(self, event: RevocationAuditEvent) -> None:
        """Durably record ``event``; raise if it cannot be written (callers fail closed)."""
        ...


@dataclass(frozen=True, slots=True)
class RevocationOutcome:
    entry: RevocationEntry
    fanout: FanoutReport
    #: Other replicas deny within this many seconds of ``entry.revoked_at``.
    propagation_bound_seconds: float


def _actor_id(actor: IdentityScope) -> str:
    return actor.to_contract().principal.principal_id.root


def _same_tenancy(actor: IdentityScope, target_principal_id: str) -> bool:
    cloud, customer = target_principal_id.split(":", 2)[:2]
    return cloud == actor.cloud and customer == actor.customer_id


class ScopePermissionRevocationAuthorizer:
    """Default policy: ``revocation.manage`` (Admin role) in at least one unexpired domain
    assignment, and the target in the actor's own cloud and customer.

    A principal is customer-scoped, not domain-scoped, so a domain admin may revoke any principal
    of the same customer; revocation only removes access. Inject a stricter authorizer (for
    example, one requiring a shared domain) if a deployment needs it.
    """

    def __init__(self, *, clock: Clock = time.time) -> None:
        self._clock = clock

    async def authorize_revocation(self, actor: IdentityScope, target_principal_id: str) -> bool:
        if not _same_tenancy(actor, target_principal_id):
            raise ForbiddenError("target is outside the caller scope", reason="cross_scope_target")
        now = datetime.fromtimestamp(self._clock(), UTC)
        if not domains_with_permission(actor, Permission.REVOCATION_MANAGE, now=now):
            raise ForbiddenError("revocation.manage required", reason="missing_permission")
        return True


class RevocationService:
    def __init__(
        self,
        *,
        store: RevocationStore,
        authorizer: RevocationAuthorizer,
        auditor: RevocationAuditor,
        hooks: RevocationHookRegistry,
        ttl_seconds: float = DEFAULT_REVOCATION_TTL_SECONDS,
        clock: Clock = time.time,
    ) -> None:
        self._store = store
        self._authorizer = authorizer
        self._auditor = auditor
        self._hooks = hooks
        self._ttl = ttl_seconds
        self._clock = clock

    @property
    def hooks(self) -> RevocationHookRegistry:
        return self._hooks

    async def revoke(
        self, actor: IdentityScope, target_principal_id: str, *, reason: str
    ) -> RevocationOutcome:
        if not isinstance(actor, IdentityScope):
            raise TypeError("revoke requires a server-derived IdentityScope")
        issues: list[ValidationIssue] = []
        if not is_canonical_principal_id(target_principal_id):
            issues.append(ValidationIssue("/principal_id", "must be a canonical principal id"))
        if not is_reason_code(reason):
            issues.append(ValidationIssue("/reason", "must be a machine reason code"))
        if issues:
            raise InvalidSchemaError("invalid revocation request", errors=issues)
        actor_id = _actor_id(actor)
        base = RevocationAuditEvent(
            action=REVOKE_ACTION,
            phase="intent",
            actor_principal_id=actor_id,
            actor_scope_hash=actor.scope_hash,
            target_principal_id=target_principal_id,
            reason=reason,
        )
        await self._authorize(actor, target_principal_id, base)

        revoked_at = datetime.fromtimestamp(self._clock(), UTC)
        entry = RevocationEntry(
            principal_id=target_principal_id,
            revoked_at=revoked_at,
            reason=reason,
            revoked_by=actor_id,
        )
        await self._auditor.record(replace(base, phase="intent", revoked_at=revoked_at))
        try:
            effective = await self._store.put(entry)
        except NeuroSphereError as exc:
            await self._audit_failure(base, revoked_at, exc)
            raise
        except Exception as exc:
            error = DependencyTransientError(
                "revocation store unavailable", reason="revocation_store_unavailable"
            )
            await self._audit_failure(base, revoked_at, error)
            raise error from exc

        fanout = await self._hooks.fan_out(target_principal_id)
        await self._auditor.record(
            replace(base, phase="outcome", revoked_at=effective.revoked_at, fanout=fanout)
        )
        return RevocationOutcome(
            entry=effective, fanout=fanout, propagation_bound_seconds=self._ttl
        )

    async def _authorize(
        self, actor: IdentityScope, target: str, base: RevocationAuditEvent
    ) -> None:
        try:
            allowed = await self._authorizer.authorize_revocation(actor, target)
        except ForbiddenError as exc:
            await self._auditor.record(
                replace(base, phase="denied", deny_reason=exc.reason or "forbidden")
            )
            raise
        except NeuroSphereError:
            raise
        except Exception as exc:
            raise DependencyTransientError(
                "revocation authorization unavailable", reason="authorization_unavailable"
            ) from exc
        if allowed is not True:
            await self._auditor.record(replace(base, phase="denied", deny_reason="not_authorized"))
            raise ForbiddenError("revocation not authorized", reason="not_authorized")

    async def _audit_failure(
        self, base: RevocationAuditEvent, revoked_at: datetime, error: NeuroSphereError
    ) -> None:
        try:
            await self._auditor.record(
                replace(base, phase="failed", revoked_at=revoked_at, error_code=error.code)
            )
        except Exception as exc:  # the store error is what the caller must see
            _log.warning(
                "revocation failure audit not written",
                extra={"action": REVOKE_ACTION, "error_type": type(exc).__name__},
            )
