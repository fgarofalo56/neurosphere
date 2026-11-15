"""Producer admin service: every mutation wrapped in audit records (PRP-41 item 3).

Before/after records go on ``<customer>.admin-config`` through ``run_audited_mutation`` (a failed
audit write aborts the change). Record state is digest-free: operation, producer id, source ids
and status. The generated secret never leaves :class:`ProducerResult`.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Final, Literal, TypeVar

from fastapi import FastAPI, Request
from neurosphere_contracts.admin.v1.admin_config_document import AdminConfigDocument
from neurosphere_contracts.admin.v1.producer_record import ProducerRecord
from neurosphere_core.admin import admin_config_chain_id
from neurosphere_core.admin.producers import ProducerAdmin, ProducerResult
from neurosphere_core.audit import (
    AuditContext,
    AuditDraft,
    AuditRepository,
    build_after,
    build_before,
    make_subject,
    run_audited_mutation,
)
from neurosphere_core.errors import DependencyTransientError, InvalidSchemaError, ValidationIssue
from neurosphere_core.scope import IdentityScope

from neurosphere_api.admin.sources.producers.models import ProducerCreateRequest

__all__ = [
    "STATE_ATTRIBUTE",
    "ProducerAdminPlane",
    "ProducerAdminService",
    "configure_producer_admin",
    "get_plane",
]

STATE_ATTRIBUTE: Final = "admin_producers"
_T = TypeVar("_T")
_DETAIL_OK: Final = re.compile(r"^[a-z][a-z0-9_.:=-]{0,127}$")


@dataclass(frozen=True)
class ProducerAdminPlane:
    """What the routes need. ``on_change`` updates the local ingest snapshot after a write."""

    admin: ProducerAdmin
    audit: AuditRepository
    on_change: Callable[[AdminConfigDocument], None] | None = None


def configure_producer_admin(app: FastAPI, plane: ProducerAdminPlane) -> None:
    setattr(app.state, STATE_ATTRIBUTE, plane)


def get_plane(request: Request) -> ProducerAdminPlane:
    plane = getattr(request.app.state, STATE_ATTRIBUTE, None)
    if not isinstance(plane, ProducerAdminPlane):
        raise DependencyTransientError(
            "producer administration is not configured", reason="admin_producers_unconfigured"
        )
    return plane


def _error_code(exc: BaseException) -> str:
    reason = getattr(exc, "reason", None)
    return reason if isinstance(reason, str) and _DETAIL_OK.fullmatch(reason) else "error"


def require_if_match(if_match: str | None) -> str:
    if not if_match:
        raise InvalidSchemaError(
            "If-Match is required",
            errors=[ValidationIssue("/headers/If-Match", "required")],
            reason="precondition_required",
        )
    return if_match


class ProducerAdminService:
    def __init__(
        self, plane: ProducerAdminPlane, scope: IdentityScope, correlation_id: str
    ) -> None:
        self._plane = plane
        self._scope = scope
        self._correlation = correlation_id

    @property
    def _actor(self) -> str:
        return self._scope.to_contract().principal.principal_id.root

    def _subject(self, operation: str, producer_id: str, state: dict[str, object]):
        scope = self._scope
        return make_subject(
            f"{scope.cloud}:{scope.customer_id}:ingest:producer:{producer_id}",
            "ingest_producer",
            state={"operation": operation, "producer_id": producer_id, **state},
        )

    @staticmethod
    def _state_of(document: AdminConfigDocument) -> dict[str, object]:
        body = document.body
        assert isinstance(body, ProducerRecord)
        return {
            "source_ids": sorted(s.source_id for s in body.sources),
            "status": body.status,
            "version": document.version.root,
        }

    async def _audited(
        self,
        operation: str,
        producer_id: str,
        intent_state: dict[str, object],
        mutate: Callable[[], Awaitable[ProducerResult]],
    ) -> ProducerResult:
        ctx = AuditContext.from_scope(
            self._scope,
            correlation_id=self._correlation,
            operation=operation,
            channel="rest",
        )

        def after(result: ProducerResult) -> AuditDraft:
            return build_after(
                ctx,
                self._subject(operation, producer_id, self._state_of(result.document)),
                result="succeeded",
                verified=True,
                detail=operation.replace(".", "_"),
            )

        def failed(exc: BaseException) -> AuditDraft:
            return build_after(
                ctx,
                self._subject(operation, producer_id, intent_state),
                result="failed",
                verified=False,
                detail=_error_code(exc),
            )

        result = await run_audited_mutation(
            self._plane.audit,
            admin_config_chain_id(self._scope.customer_id),
            before=build_before(ctx, self._subject(operation, producer_id, intent_state)),
            mutate=mutate,
            after=after,
            on_error=failed,
        )
        if self._plane.on_change is not None:
            self._plane.on_change(result.document)
        return result

    async def create(self, body: ProducerCreateRequest) -> ProducerResult:
        admin = self._plane.admin
        return await self._audited(
            "producer.create",
            body.producer_id,
            {"source_ids": sorted(body.sources), "status": "active"},
            lambda: admin.create(
                self._scope.customer_id,
                body.producer_id,
                cloud=body.cloud,
                sources=body.sources,
                updated_by=self._actor,
                requested_customer_id=body.customer_id,
            ),
        )

    async def rotate(self, producer_id: str, if_match: str | None) -> ProducerResult:
        etag = require_if_match(if_match)
        admin = self._plane.admin
        return await self._audited(
            "producer.rotate",
            producer_id,
            {},
            lambda: admin.rotate(
                self._scope.customer_id, producer_id, if_match=etag, updated_by=self._actor
            ),
        )

    async def set_status(
        self, producer_id: str, status: Literal["active", "disabled"], if_match: str | None
    ) -> ProducerResult:
        etag = require_if_match(if_match)
        admin = self._plane.admin
        operation = "producer.enable" if status == "active" else "producer.disable"
        return await self._audited(
            operation,
            producer_id,
            {"status": status},
            lambda: admin.set_status(
                self._scope.customer_id,
                producer_id,
                status,
                if_match=etag,
                updated_by=self._actor,
            ),
        )

    async def get(self, producer_id: str) -> AdminConfigDocument:
        return await self._plane.admin.get(self._scope.customer_id, producer_id)

    async def list(self, limit: int) -> list[AdminConfigDocument]:
        return await self._plane.admin.list(self._scope.customer_id, limit=limit)
