"""Allowed-read audit for search and analytics reads (PRP-48 item 4, #69).

Denials are audited by ``require``'s denial recorder; until this module, an ALLOWED catalog search
or dashboard read left no record. :func:`audited_read` is a dependency that runs
:func:`~neurosphere_api.authz.require` (so the route inventory still sees the permission) and
hands the route a :class:`ReadAudit`; after the route computed its answer it calls
:meth:`ReadAudit.allowed` with the domains read and the result count.

What is recorded (one ``allow`` record per read, ``build_allowed``):

* actor pseudonym, principal kind and scope hash from the server-derived scope;
* the operation (for example ``catalog.search``) and the ``rest`` channel;
* the subject: the one domain read (entity type ``domain``), or for a read over several domains
  the customer's read-audit service target; its ``state_digest`` is the SHA-256 of
  ``{"domain_ids": [...], "result_count": n}``. The ``AuditRecord`` contract has no count field,
  so the count is bound by that digest (a verifier recomputes it from the response size);
* never the query text, filters other than domains, or any returned row.

Chain: the domain's chain (``domain_audit_chain_id``) for a single-domain read; otherwise, or when
that domain cannot be encoded, the customer-level chain ``<customer>.read-audit`` (a reserved name
in ``neurosphere_core.audit.chains``).

Failure rule (PRP-48 decision 3): a read is not a mutation, so a failed or unconfigured audit
write is logged (no domain ids, no query) and counted in :class:`ReadAuditStats` on
``app.state.read_audit_stats``; it never blocks or alters the read. Mutations keep failing closed
through their own audited paths.
"""

# No ``from __future__ import annotations``: FastAPI inspects the dependency signature, and it
# closes over a local (``base``) in its annotation.

import re
import threading
import uuid
from collections import Counter
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Annotated, Final

from fastapi import Depends, Request
from neurosphere_core.audit import (
    AuditContext,
    AuditRepository,
    build_allowed,
    domain_audit_chain_id,
    make_subject,
)
from neurosphere_core.auth.scope import Permission
from neurosphere_core.errors import InvalidSchemaError
from neurosphere_core.observability import get_logger
from neurosphere_core.scope import IdentityScope

from neurosphere_api.authz.dependencies import ResourceResolver, require
from neurosphere_api.middleware import correlation_id_of

__all__ = [
    "READ_AUDIT_CHAIN_NAME",
    "STATS_ATTRIBUTE",
    "ReadAudit",
    "ReadAuditStats",
    "audited_read",
    "read_audit_chain_id",
    "read_audit_stats",
]

#: Customer-level chain ``<customer>.read-audit`` for reads spanning several domains.
READ_AUDIT_CHAIN_NAME: Final = "read-audit"
#: ``app.state`` attribute of the :class:`ReadAuditStats` failure counters.
STATS_ATTRIBUTE: Final = "read_audit_stats"
_AUDIT_REPOSITORY_ATTRIBUTE: Final = "audit_repository"
_CORRELATION: Final = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_LOG = get_logger("neurosphere_api.authz.read_audit")


def read_audit_chain_id(customer_id: str) -> str:
    """``<customer>.read-audit``: the chain of multi-domain allowed reads."""
    return f"{customer_id}.{READ_AUDIT_CHAIN_NAME}"


class ReadAuditStats:
    """Thread-safe failure counters by reason code (``audit_store_unconfigured``, ...)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counts: Counter[str] = Counter()

    def add(self, reason: str) -> None:
        with self._lock:
            self._counts[reason] += 1

    def snapshot(self) -> Mapping[str, int]:
        with self._lock:
            return dict(self._counts)


def read_audit_stats(app_state: object) -> ReadAuditStats:
    """The app's :class:`ReadAuditStats`, created on first use."""
    stats = getattr(app_state, STATS_ATTRIBUTE, None)
    if not isinstance(stats, ReadAuditStats):
        stats = ReadAuditStats()
        setattr(app_state, STATS_ATTRIBUTE, stats)
    return stats


def _correlation_id(request_id: str | None) -> str:
    """Audit-safe correlation id (``corr-`` + the request id without dashes), else generated."""
    if request_id:
        candidate = "corr-" + request_id.replace("-", "")
        if candidate != "corr-" and _CORRELATION.fullmatch(candidate):
            return candidate
    return f"corr-{uuid.uuid4().hex}"


def _chain_for(scope: IdentityScope, domains: tuple[str, ...]) -> str:
    if len(domains) == 1:
        try:
            return domain_audit_chain_id(scope.customer_id, domains[0])
        except InvalidSchemaError:
            _LOG.debug("read audit falls back to the customer chain (unencodable domain)")
    return read_audit_chain_id(scope.customer_id)


def _subject_target(scope: IdentityScope, domains: tuple[str, ...]) -> tuple[str, str]:
    if len(domains) == 1:
        return domains[0], "domain"
    return f"{scope.cloud}:{scope.customer_id}:neurosphere:service:read-audit", "service"


@dataclass(frozen=True)
class ReadAudit:
    """Handed to a route by :func:`audited_read`: the scope plus the allowed-read recorder."""

    scope: IdentityScope
    operation: str
    request: Request

    async def allowed(self, domain_ids: Iterable[str], result_count: int) -> None:
        """Append one ``allow`` record; never raises (see the module failure rule)."""
        domains = tuple(sorted({d for d in domain_ids if d}))
        stats = read_audit_stats(self.request.app.state)
        repository = getattr(self.request.app.state, _AUDIT_REPOSITORY_ATTRIBUTE, None)
        if not isinstance(repository, AuditRepository):
            stats.add("audit_store_unconfigured")
            _LOG.warning(
                "allowed-read audit skipped: audit store not configured",
                extra={"operation": self.operation, "read_audit_reason": "unconfigured"},
            )
            return
        try:
            target, entity_type = _subject_target(self.scope, domains)
            subject = make_subject(
                target,
                entity_type,
                state={"domain_ids": list(domains), "result_count": max(result_count, 0)},
            )
            ctx = AuditContext.from_scope(
                self.scope,
                correlation_id=_correlation_id(correlation_id_of(self.request.scope)),
                operation=self.operation,
                channel="rest",
            )
            await repository.append(_chain_for(self.scope, domains), build_allowed(ctx, subject))
        except Exception as exc:
            # A read is not a mutation: log and count, never block the answer (decision 3).
            stats.add("audit_write_failed")
            _LOG.warning(
                "allowed-read audit write failed",
                extra={
                    "operation": self.operation,
                    "read_audit_reason": "write_failed",
                    "error_type": type(exc).__name__,
                },
            )


def audited_read(
    permission: Permission | str,
    operation: str,
    resource: ResourceResolver | None = None,
) -> Callable[..., Awaitable[ReadAudit]]:
    """Dependency: ``require(permission, resource)``, then a :class:`ReadAudit` for ``operation``.

    Denials keep their usual path (``require``'s denial recorder); this adds the allowed side.
    """
    base = require(permission, resource)

    async def audited(
        request: Request, scope: Annotated[IdentityScope, Depends(base)]
    ) -> ReadAudit:
        return ReadAudit(scope=scope, operation=operation, request=request)

    audited.__name__ = f"audited_{operation.replace('.', '_')}"
    return audited
