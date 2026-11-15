"""Platform admin plane and audit wrapper (PRP-44 items 2 and 3).

Permission (customer-level ``config.manage``) is enforced by the routers before any method here
runs. Every mutation writes a ``before`` record, runs (validation included, so a refused write is
audited as ``failed`` with its reason code), then writes an ``after`` record on the customer chain
``<customer>.admin-config`` through the hash-chained audit store; a failed audit write aborts the
change (fail closed). Audit state is hashed: it holds ids, versions and counts, never a price
value or a policy body.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Final, TypeVar

from fastapi import FastAPI, Request
from neurosphere_core.admin import admin_config_chain_id
from neurosphere_core.admin.platform import PlatformAdmin
from neurosphere_core.audit import (
    AuditContext,
    AuditDraft,
    AuditRepository,
    build_after,
    build_before,
    make_subject,
    run_audited_mutation,
)
from neurosphere_core.errors import DependencyTransientError
from neurosphere_core.scope import IdentityScope

__all__ = [
    "STATE_ATTRIBUTE",
    "PlatformAdminPlane",
    "PlatformAuditor",
    "configure_admin_platform",
    "get_plane",
]

# A module TypeVar, not a PEP 695 parameter (CodeQL: uninitialized local in nested functions).
_T = TypeVar("_T")

STATE_ATTRIBUTE: Final = "admin_platform"
_DETAIL_OK: Final = re.compile(r"^[a-z][a-z0-9_.:=-]{0,127}$")
_LABEL_OK: Final = re.compile(r"[^a-z0-9._-]")


@dataclass(frozen=True)
class PlatformAdminPlane:
    """What the routes need; installed on ``app.state.admin_platform`` by the builder."""

    admin: PlatformAdmin
    #: Resolved per request: a missing audit store fails every mutation closed (503).
    audit: Callable[[], AuditRepository | None]


def configure_admin_platform(app: FastAPI, plane: PlatformAdminPlane | None) -> None:
    setattr(app.state, STATE_ATTRIBUTE, plane)


def get_plane(request: Request) -> PlatformAdminPlane:
    plane = getattr(request.app.state, STATE_ATTRIBUTE, None)
    if not isinstance(plane, PlatformAdminPlane):
        raise DependencyTransientError(
            "platform administration is not configured", reason="admin_platform_unconfigured"
        )
    return plane


def _error_code(exc: BaseException) -> str:
    reason = getattr(exc, "reason", None)
    if isinstance(reason, str) and _DETAIL_OK.fullmatch(reason):
        return reason
    return "error"


def _segment(value: str) -> str:
    """The last canonical segment, restricted to the audit canonical-id alphabet."""
    return _LABEL_OK.sub("-", value.rsplit(":", 1)[-1].lower())[:128] or "x"


class PlatformAuditor:
    def __init__(self, plane: PlatformAdminPlane, scope: IdentityScope) -> None:
        self._plane = plane
        self._scope = scope

    @property
    def actor(self) -> str:
        return self._scope.to_contract().principal.principal_id.root

    def _repository(self) -> AuditRepository:
        repository = self._plane.audit()
        if repository is None:
            raise DependencyTransientError(
                "audit store is not configured", reason="audit_store_unconfigured"
            )
        return repository

    def _subject(
        self,
        entity: str,
        target: str,
        operation: str,
        *,
        etag: str | None,
        stage: str,
        extra: dict[str, Any],
    ) -> Any:
        scope = self._scope
        canonical = (
            f"{scope.cloud}:{scope.customer_id}:admin:{entity.replace('_', '-')}:{_segment(target)}"
        )
        state = {"operation": operation, "target": target, "stage": stage, **extra}
        return make_subject(canonical, entity, target_version=etag, state=state)

    async def run(
        self,
        correlation_id: str,
        operation: str,
        entity: str,
        target: str,
        mutate: Callable[[], Awaitable[_T]],
        *,
        info: Callable[[_T], tuple[str | None, dict[str, Any]]],
    ) -> _T:
        """Audit ``mutate``. ``info(result)`` gives the ETag and non-sensitive audit state."""
        scope = self._scope
        ctx = AuditContext.from_scope(
            scope, correlation_id=correlation_id, operation=operation, channel="rest"
        )

        def after(result: _T) -> AuditDraft:
            etag, extra = info(result)
            subject = self._subject(
                entity, target, operation, etag=etag, stage="after", extra=extra
            )
            return build_after(
                ctx, subject, result="succeeded", verified=True, detail=f"{entity}_written"
            )

        def failed(exc: BaseException) -> AuditDraft:
            subject = self._subject(entity, target, operation, etag=None, stage="failed", extra={})
            return build_after(
                ctx, subject, result="failed", verified=False, detail=_error_code(exc)
            )

        return await run_audited_mutation(
            self._repository(),
            admin_config_chain_id(scope.customer_id),
            before=build_before(
                ctx,
                self._subject(entity, target, operation, etag=None, stage="before", extra={}),
            ),
            mutate=mutate,
            after=after,
            on_error=failed,
        )
