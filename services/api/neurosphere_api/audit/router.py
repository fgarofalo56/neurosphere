"""Auditor read and chain-verify routes (PRP-06 item 4). Read-only: there is no write route.

``GET /api/v1/audit/chains/{chain_id}/records`` -- page through records by sequence (permission
``audit.read``). ``GET /api/v1/audit/chains/{chain_id}/verify`` -- verify the whole chain against
its tail pointer (permission ``audit.verify``). The old ``/audit`` prefix stays as a deprecated
alias for one release (PRP-29 item 4).

AUTHZ SEAM (until PRP-06 item 3 lands): every route depends on
``require_permission(<permission>)``. ``build_router`` takes that factory as a parameter and
defaults to :func:`deny_all_until_authz`, which refuses every request with 403
(reason ``authz_not_wired``). Item 3 passes its ``require`` (same ``(permission) -> dependency``
shape) when mounting; this module deliberately does not import ``neurosphere_api.authz``.
The permission dependency is declared on the route decorator, so FastAPI resolves it BEFORE the
repository lookup or any read. The dependency must also confine ``chain_id`` to the caller's
scope (it can read the path parameter from the request); that check belongs to item 3.

The repository comes from ``app.state.audit_repository`` (an ``AuditRepository``); when it is
absent the routes fail closed with 503 (reason ``audit_store_unconfigured``).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Annotated, Any, Final

from fastapi import APIRouter, Depends, Path, Query, Request
from neurosphere_contracts.audit.v1.audit_record import AuditRecord
from neurosphere_core.audit import AuditRepository, ChainVerification
from neurosphere_core.audit.repository import CHAIN_ID_PATTERN, MAX_RANGE
from neurosphere_core.errors import DependencyTransientError, ForbiddenError
from neurosphere_core.paging import Page
from neurosphere_core.paging.models import DEFAULT_PAGE_SIZE

from neurosphere_api.deprecation import register_with_alias
from neurosphere_api.routers import RouterRegistry

PERMISSION_AUDIT_READ: Final = "audit.read"
PERMISSION_AUDIT_VERIFY: Final = "audit.verify"
ROUTE_PREFIX: Final = "/api/v1/audit"
#: Deprecated alias for one release (PRP-29 item 4): same router, same permissions.
ALIAS_PREFIX: Final = "/audit"

PermissionDependency = Callable[..., Any]
RequirePermission = Callable[[str], PermissionDependency]

ChainIdPath = Annotated[str, Path(pattern=CHAIN_ID_PATTERN.pattern, max_length=128)]


def deny_all_until_authz(permission: str) -> Callable[[], Awaitable[None]]:
    """Placeholder permission factory: denies everything until item 3's ``require`` is wired."""

    async def deny_until_authz_wired() -> None:
        raise ForbiddenError(
            f"authorization for {permission} is not wired", reason="authz_not_wired"
        )

    return deny_until_authz_wired


def get_audit_repository(request: Request) -> AuditRepository:
    repository = getattr(request.app.state, "audit_repository", None)
    if not isinstance(repository, AuditRepository):
        raise DependencyTransientError(
            "audit store is not configured", reason="audit_store_unconfigured"
        )
    return repository


Repository = Annotated[AuditRepository, Depends(get_audit_repository)]


def build_router(*, require_permission: RequirePermission = deny_all_until_authz) -> APIRouter:
    router = APIRouter(tags=["audit"])

    @router.get(
        "/chains/{chain_id}/records",
        response_model=Page[AuditRecord],
        dependencies=[Depends(require_permission(PERMISSION_AUDIT_READ))],
    )
    async def list_audit_records(
        chain_id: ChainIdPath,
        repository: Repository,
        cursor: Annotated[str | None, Query(pattern=r"^[0-9]{1,18}$")] = None,
        page_size: Annotated[int, Query(ge=1, le=MAX_RANGE)] = DEFAULT_PAGE_SIZE,
    ) -> Page[AuditRecord]:
        start = int(cursor) if cursor is not None else 0
        records = await repository.read_range(chain_id, start=start, limit=page_size)
        tail = await repository.tail(chain_id)
        next_start = start + page_size
        more = tail is not None and next_start <= tail.sequence
        return Page[AuditRecord](
            items=tuple(records), next_cursor=str(next_start) if more else None
        )

    @router.get(
        "/chains/{chain_id}/verify",
        response_model=ChainVerification,
        dependencies=[Depends(require_permission(PERMISSION_AUDIT_VERIFY))],
    )
    async def verify_audit_chain(
        chain_id: ChainIdPath, repository: Repository
    ) -> ChainVerification:
        return await repository.verify(chain_id)

    return router


def register(
    registry: RouterRegistry, *, require_permission: RequirePermission = deny_all_until_authz
) -> None:
    """Router-registry hook (see ``neurosphere_api/routers.py``)."""
    register_with_alias(
        registry,
        build_router(require_permission=require_permission),
        prefix=ROUTE_PREFIX,
        alias_prefix=ALIAS_PREFIX,
    )
