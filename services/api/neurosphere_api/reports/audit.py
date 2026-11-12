"""Audit trail of saved-report actions (PRP-19 round 2 item 11).

Events (chain ``<customer>.<domain name>``, the catalog convention), all metadata only:

====================================  ==========================================================
operation                             records
====================================  ==========================================================
``report.run``                        ``allowed`` (kind ``after``) or ``denied``
``report.share`` / ``report.unshare`` ``before`` + ``after`` (detail ``shared:target=<principal>``
                                      / ``unshared:target=<principal>``) or ``denied``
``report.publication.request``        ``before`` + ``after`` (detail ``publication_requested``)
``report.publication.decide``         ``before`` + ``after`` (detail ``decision=approve|reject``)
                                      or ``denied`` (``self_approval_refused``)
====================================  ==========================================================

The actor and scope hash come from the verified scope. The subject is the report (canonical id
``<cloud>:<customer>:reports:report:<domain>/<report id>``, version = its ETag). Result rows,
chart values, titles and queries are never written; a share target is the (pseudonymous,
normalized) principal id. Without an audit repository the helper is a pass-through, so a deployment
that has not wired one keeps working; the composition always wires it.
"""

import hashlib
import re
from collections.abc import Awaitable, Callable
from typing import Final

from neurosphere_contracts.audit.v1.audit_record import Subject
from neurosphere_core.audit import (
    AuditContext,
    AuditRepository,
    build_after,
    build_allowed,
    build_before,
    build_denied,
    make_subject,
    run_audited_mutation,
)
from neurosphere_core.audit.builders import DenialCode
from neurosphere_core.audit.chains import domain_audit_chain_id
from neurosphere_core.audit.content_guard import GUID
from neurosphere_core.scope import IdentityScope

__all__ = ["ReportAuditor", "audit_correlation_id"]

_CANONICAL_ID: Final = re.compile(r"^[a-z0-9._/=-]+$")
_DETAIL_TARGET: Final = re.compile(r"^[a-z0-9._:=-]{1,100}$")
_UNSET_CORRELATION: Final = "corr-unset"


def audit_correlation_id(request_id: str) -> str:
    """Request id in audit-safe form (the content guard rejects GUID-shaped values here)."""
    return "corr-" + request_id.replace("-", "")


def _domain_name(domain_id: str) -> str:
    return domain_id.rsplit(":", 1)[-1]


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]


def _safe_segment(value: str) -> str:
    return value if _CANONICAL_ID.fullmatch(value) else "h" + _digest(value)


class ReportAuditor:
    """Appends report audit records; fail closed (an unwritable record aborts the action)."""

    def __init__(self, repository: AuditRepository | None) -> None:
        self._repo = repository

    def _context(
        self, scope: IdentityScope, operation: str, correlation_id: str | None
    ) -> AuditContext:
        return AuditContext.from_scope(
            scope,
            correlation_id=correlation_id or _UNSET_CORRELATION,
            operation=operation,
            channel="rest",
        )

    @staticmethod
    def _chain(scope: IdentityScope, domain_id: str) -> str:
        return domain_audit_chain_id(scope.customer_id, domain_id)

    @staticmethod
    def _subject(scope: IdentityScope, domain_id: str, report_id: str, etag: str | None) -> Subject:
        target = (
            f"{scope.cloud}:{scope.customer_id}:reports:report:"
            f"{_safe_segment(_domain_name(domain_id))}/{_safe_segment(report_id)}"
        )
        return make_subject(target, "report", target_version=etag or None)

    @staticmethod
    def target_detail(prefix: str, principal_id: str) -> str:
        """``<prefix>:target=<principal>``; a principal that is not detail-safe (or is GUID-shaped)
        is replaced by a digest of it so the record is still written and still correlatable."""
        if _DETAIL_TARGET.fullmatch(principal_id) and not GUID.search(principal_id):
            return f"{prefix}:target={principal_id}"
        return f"{prefix}:target=sha256-{_digest(principal_id)}"

    async def allowed(
        self,
        scope: IdentityScope,
        *,
        operation: str,
        domain_id: str,
        report_id: str,
        etag: str | None,
        correlation_id: str | None,
    ) -> None:
        if self._repo is None:
            return
        ctx = self._context(scope, operation, correlation_id)
        subject = self._subject(scope, domain_id, report_id, etag)
        await self._repo.append(self._chain(scope, domain_id), build_allowed(ctx, subject))

    async def denied(
        self,
        scope: IdentityScope,
        *,
        operation: str,
        domain_id: str,
        report_id: str,
        etag: str | None,
        code: DenialCode,
        reason: str,
        correlation_id: str | None,
    ) -> None:
        if self._repo is None:
            return
        ctx = self._context(scope, operation, correlation_id)
        subject = self._subject(scope, domain_id, report_id, etag)
        await self._repo.append(
            self._chain(scope, domain_id),
            build_denied(ctx, code=code, reason=reason, subject=subject),
        )

    async def mutate[T](
        self,
        scope: IdentityScope,
        *,
        operation: str,
        domain_id: str,
        report_id: str,
        etag: str | None,
        detail: str,
        correlation_id: str | None,
        action: Callable[[], Awaitable[T]],
        new_etag: Callable[[T], str | None],
    ) -> T:
        """``before`` record, the change, ``after`` record (or a ``failed`` one)."""
        if self._repo is None:
            return await action()
        ctx = self._context(scope, operation, correlation_id)
        before = self._subject(scope, domain_id, report_id, etag)
        return await run_audited_mutation(
            self._repo,
            self._chain(scope, domain_id),
            before=build_before(ctx, before),
            mutate=action,
            after=lambda result: build_after(
                ctx,
                self._subject(scope, domain_id, report_id, new_etag(result)),
                result="succeeded",
                verified=True,
                detail=detail,
            ),
            on_error=lambda _exc: build_after(
                ctx, before, result="failed", verified=False, detail="mutation_failed"
            ),
        )
