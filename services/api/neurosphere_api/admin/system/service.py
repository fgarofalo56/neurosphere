"""System admin plane and the audited settings write (PRP-45 items 2 and 3).

Every route checks the deployment-scoped admin permission (``config.manage`` on the customer's
control domain, PRP-48) before anything here runs. A settings write is NOT an executor intent: it
changes NeuroSphere's own configuration, not an external system (clarification 4). It is an
audited, ``If-Match``-guarded ``admin_config`` write: a ``before`` record, the write, then an
``after`` record on ``<customer>.admin-config``; a failed audit write aborts the change. Body
validation (``validate_setting``) and ``check_runtime_settings`` run in the settings router before
the auditor, so a 422 refusal is not audited; only a write that passed validation and then failed
is audited ``failed`` with its reason code. Audit state carries the key, document id, version and
changed pointers, never a stored value.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, Final, TypeVar

from fastapi import FastAPI, Request
from neurosphere_core.admin import AdminConfigRepository, admin_config_chain_id
from neurosphere_core.admin.runtime import StoredSettingsSnapshot
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
    "SystemAdminPlane",
    "SystemAuditor",
    "configure_admin_system",
    "get_plane",
]

_T = TypeVar("_T")

STATE_ATTRIBUTE: Final = "admin_system"
_DETAIL_OK: Final = re.compile(r"^[a-z][a-z0-9_.:=-]{0,127}$")
_LABEL_OK: Final = re.compile(r"[^a-z0-9._-]")


@dataclass(frozen=True)
class SystemAdminPlane:
    """What the routes need; installed on ``app.state.admin_system`` by the builder."""

    repository: AdminConfigRepository
    #: Resolved per request: a missing audit store fails every write closed (503).
    audit: Callable[[], AuditRepository | None]
    #: The snapshot this process started with (applied revisions, A1).
    applied: StoredSettingsSnapshot
    cloud: str
    #: The environment the process composed from (status ``source``); never echoed.
    environ: Mapping[str, str]
    #: ``explicit`` (``NS_AUTH_CUSTOMER_ID`` set), ``local_default`` or ``missing``.
    customer_binding: str


def configure_admin_system(app: FastAPI, plane: SystemAdminPlane | None) -> None:
    setattr(app.state, STATE_ATTRIBUTE, plane)


def get_plane(request: Request) -> SystemAdminPlane:
    plane = getattr(request.app.state, STATE_ATTRIBUTE, None)
    if not isinstance(plane, SystemAdminPlane):
        raise DependencyTransientError(
            "system administration is not configured", reason="admin_system_unconfigured"
        )
    return plane


def _error_code(exc: BaseException) -> str:
    reason = getattr(exc, "reason", None)
    if isinstance(reason, str) and _DETAIL_OK.fullmatch(reason):
        return reason
    return "error"


class SystemAuditor:
    def __init__(self, plane: SystemAdminPlane, scope: IdentityScope) -> None:
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

    def _subject(self, target: str, stage: str, etag: str | None, extra: dict[str, Any]) -> Any:
        scope = self._scope
        segment = _LABEL_OK.sub("-", target.lower())[:128] or "x"
        canonical = f"{scope.cloud}:{scope.customer_id}:admin:system-setting:{segment}"
        state = {"operation": "system_setting.put", "target": target, "stage": stage, **extra}
        return make_subject(canonical, "system_setting", target_version=etag, state=state)

    async def run(
        self,
        correlation_id: str,
        target: str,
        mutate: Callable[[], Awaitable[_T]],
        *,
        info: Callable[[_T], tuple[str | None, dict[str, Any]]],
    ) -> _T:
        scope = self._scope
        ctx = AuditContext.from_scope(
            scope, correlation_id=correlation_id, operation="system_setting.put", channel="rest"
        )

        def after(result: _T) -> AuditDraft:
            etag, extra = info(result)
            return build_after(
                ctx,
                self._subject(target, "after", etag, extra),
                result="succeeded",
                verified=True,
                detail="system_setting_written",
            )

        def failed(exc: BaseException) -> AuditDraft:
            return build_after(
                ctx,
                self._subject(target, "failed", None, {}),
                result="failed",
                verified=False,
                detail=_error_code(exc),
            )

        return await run_audited_mutation(
            self._repository(),
            admin_config_chain_id(scope.customer_id),
            before=build_before(ctx, self._subject(target, "before", None, {})),
            mutate=mutate,
            after=after,
            on_error=failed,
        )
