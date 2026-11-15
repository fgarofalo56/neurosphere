"""Connector admin service: each mutation wrapped in an audit record (PRP-42 item 3).

Permission (customer-level ``config.manage``) is enforced by the router before any method here
runs. Every mutation writes a ``before`` record, runs (validation included, so a refused write is
audited as ``failed`` with its reason code), then writes an ``after`` record on the customer chain
``<customer>.admin-config`` through the PRP-06 hash-chained store; a failed audit write aborts
the change (fail closed). Records carry the actor pseudonym, the connector id and kind, the
version and ETag; the audit state is hashed and holds no setting value and no reference.
"""

from __future__ import annotations

import builtins
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Final, TypeVar

from fastapi import FastAPI, Request
from neurosphere_contracts.admin.v1.admin_config_document import AdminConfigDocument
from neurosphere_contracts.admin.v1.connector_config import ConnectorConfig
from neurosphere_core.admin import admin_config_chain_id
from neurosphere_core.admin.connectors import ConnectorConfigAdmin, ConnectorWrite
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
    "ConnectorAdminPlane",
    "ConnectorAdminService",
    "configure_admin_connectors",
    "get_plane",
]

# A module TypeVar, not a PEP 695 parameter (CodeQL: uninitialized local in nested functions).
_T = TypeVar("_T")

STATE_ATTRIBUTE: Final = "admin_connectors"
_DETAIL_OK: Final = re.compile(r"^[a-z][a-z0-9_.:=-]{0,127}$")


@dataclass(frozen=True)
class ConnectorAdminPlane:
    """What the routes need; installed on ``app.state.admin_connectors`` by the builder."""

    admin: ConnectorConfigAdmin
    audit: AuditRepository


def configure_admin_connectors(app: FastAPI, plane: ConnectorAdminPlane | None) -> None:
    setattr(app.state, STATE_ATTRIBUTE, plane)


def get_plane(request: Request) -> ConnectorAdminPlane:
    plane = getattr(request.app.state, STATE_ATTRIBUTE, None)
    if not isinstance(plane, ConnectorAdminPlane):
        raise DependencyTransientError(
            "connector administration is not configured", reason="admin_connectors_unconfigured"
        )
    return plane


def _error_code(exc: BaseException) -> str:
    reason = getattr(exc, "reason", None)
    if isinstance(reason, str) and _DETAIL_OK.fullmatch(reason):
        return reason
    return "error"


def _actor(scope: IdentityScope) -> str:
    return scope.to_contract().principal.principal_id.root


class ConnectorAdminService:
    def __init__(self, plane: ConnectorAdminPlane, scope: IdentityScope) -> None:
        self._plane = plane
        self._scope = scope

    # -- audit ---------------------------------------------------------------------------------

    def _subject(
        self, operation: str, config_id: str, *, kind: str | None, etag: str | None, stage: str
    ) -> Any:
        scope = self._scope
        canonical = f"{scope.cloud}:{scope.customer_id}:admin:connector:{config_id}"
        state = {"operation": operation, "connector_id": config_id, "kind": kind, "stage": stage}
        return make_subject(canonical, "connector_config", target_version=etag, state=state)

    async def _audited(
        self,
        correlation_id: str,
        operation: str,
        config_id: str,
        mutate: Callable[[], Awaitable[_T]],
        *,
        kind: str | None,
        etag_of: Callable[[_T], tuple[str | None, str | None]],
    ) -> _T:
        scope = self._scope
        ctx = AuditContext.from_scope(
            scope, correlation_id=correlation_id, operation=operation, channel="rest"
        )

        def after(result: _T) -> AuditDraft:
            etag, result_kind = etag_of(result)
            subject = self._subject(
                operation, config_id, kind=result_kind or kind, etag=etag, stage="after"
            )
            return build_after(
                ctx, subject, result="succeeded", verified=True, detail="connector_config_written"
            )

        def failed(exc: BaseException) -> AuditDraft:
            subject = self._subject(operation, config_id, kind=kind, etag=None, stage="failed")
            return build_after(
                ctx, subject, result="failed", verified=False, detail=_error_code(exc)
            )

        return await run_audited_mutation(
            self._plane.audit,
            admin_config_chain_id(scope.customer_id),
            before=build_before(
                ctx, self._subject(operation, config_id, kind=kind, etag=None, stage="before")
            ),
            mutate=mutate,
            after=after,
            on_error=failed,
        )

    @staticmethod
    def _write_info(write: ConnectorWrite) -> tuple[str | None, str | None]:
        body = write.document.body
        kind = body.connector_kind if isinstance(body, ConnectorConfig) else None
        return write.document.etag.root, kind

    @staticmethod
    def _doc_info(document: AdminConfigDocument) -> tuple[str | None, str | None]:
        body = document.body
        kind = body.connector_kind if isinstance(body, ConnectorConfig) else None
        return document.etag.root, kind

    # -- mutations -----------------------------------------------------------------------------

    async def create(self, correlation_id: str, body: ConnectorConfig) -> ConnectorWrite:
        scope = self._scope
        return await self._audited(
            correlation_id,
            "connector.create",
            body.connector_id.root,
            lambda: self._plane.admin.create(scope.customer_id, body, updated_by=_actor(scope)),
            kind=body.connector_kind,
            etag_of=self._write_info,
        )

    async def replace(
        self, correlation_id: str, config_id: str, body: ConnectorConfig, if_match: str
    ) -> ConnectorWrite:
        scope = self._scope
        return await self._audited(
            correlation_id,
            "connector.replace",
            config_id,
            lambda: self._plane.admin.replace(
                scope.customer_id, config_id, body, if_match=if_match, updated_by=_actor(scope)
            ),
            kind=body.connector_kind,
            etag_of=self._write_info,
        )

    async def set_enabled(
        self, correlation_id: str, config_id: str, enabled: bool, if_match: str
    ) -> ConnectorWrite:
        scope = self._scope
        return await self._audited(
            correlation_id,
            "connector.enable" if enabled else "connector.disable",
            config_id,
            lambda: self._plane.admin.set_enabled(
                scope.customer_id, config_id, enabled, if_match=if_match, updated_by=_actor(scope)
            ),
            kind=None,
            etag_of=self._write_info,
        )

    async def retire(
        self, correlation_id: str, config_id: str, if_match: str
    ) -> AdminConfigDocument:
        scope = self._scope
        return await self._audited(
            correlation_id,
            "connector.retire",
            config_id,
            lambda: self._plane.admin.retire(
                scope.customer_id, config_id, if_match=if_match, updated_by=_actor(scope)
            ),
            kind=None,
            etag_of=self._doc_info,
        )

    # -- reads ---------------------------------------------------------------------------------

    async def get(self, config_id: str) -> AdminConfigDocument:
        return await self._plane.admin.get(self._scope.customer_id, config_id)

    async def list(
        self, *, connector_kind: str | None, include_retired: bool, limit: int
    ) -> builtins.list[AdminConfigDocument]:
        return await self._plane.admin.list(
            self._scope.customer_id,
            connector_kind=connector_kind,
            include_retired=include_retired,
            limit=limit,
        )
