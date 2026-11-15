"""``GET /api/v1/audit/denials`` (PRP-40 item 4): the customer-wide ``authz-denials`` chain.

``<customer>.authz-denials`` holds denials whose target was not a domain the caller belonged to
(``runtime/builders/authz.py``) and identity-known failures before a scope existed (item 5). It
names other domains' targets, so it needs ``audit.read`` on the customer control domain
(``permits_customer_wide``); a domain-only auditor gets 403 ``customer_scope_required``. The
chain id is built from the server-derived scope's customer, never from the request.

Records are paged by sequence exactly like ``GET /api/v1/audit/chains/{chain_id}/records``.

No ``from __future__ import annotations``: FastAPI inspects these signatures.
"""

from typing import Annotated, Final

from fastapi import APIRouter, Depends, Query
from neurosphere_contracts.audit.v1.audit_record import AuditRecord
from neurosphere_core.audit import AuditRepository
from neurosphere_core.audit.repository import MAX_RANGE
from neurosphere_core.auth.scope import Permission
from neurosphere_core.paging import Page
from neurosphere_core.paging.models import DEFAULT_PAGE_SIZE
from neurosphere_core.scope import IdentityScope

from neurosphere_api.audit.access import DENIALS_CHAIN_NAME, require_customer_wide
from neurosphere_api.audit.router import get_audit_repository

__all__ = ["PREFIX", "build_router", "denials_chain"]

PREFIX: Final = "/api/v1/audit/denials"


def denials_chain(scope: IdentityScope) -> str:
    return f"{scope.customer_id}.{DENIALS_CHAIN_NAME}"


def build_router() -> APIRouter:
    router = APIRouter(tags=["audit"])

    @router.get("", response_model=Page[AuditRecord])
    async def list_audit_denials(
        scope: Annotated[IdentityScope, Depends(require_customer_wide(Permission.AUDIT_READ))],
        repository: Annotated[AuditRepository, Depends(get_audit_repository)],
        cursor: Annotated[str | None, Query(pattern=r"^[0-9]{1,18}$")] = None,
        page_size: Annotated[int, Query(ge=1, le=MAX_RANGE)] = DEFAULT_PAGE_SIZE,
    ) -> Page[AuditRecord]:
        chain = denials_chain(scope)
        start = int(cursor) if cursor is not None else 0
        records = await repository.read_range(chain, start=start, limit=page_size)
        tail = await repository.tail(chain)
        next_start = start + page_size
        more = tail is not None and next_start <= tail.sequence
        return Page[AuditRecord](
            items=tuple(records), next_cursor=str(next_start) if more else None
        )

    return router
