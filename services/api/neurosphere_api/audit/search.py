"""``GET /api/v1/audit/search`` (PRP-40 item 3): filtered audit records across readable chains.

Permission: ``audit.read`` (any domain) through ``require``, then ``audit.read`` on every domain
searched. With no ``domain`` filter the search covers every auditable domain of the caller's
scope; a named domain outside it is 403 ``target_out_of_scope``. ``since``/``until`` are
required and the window is capped (``MAX_SEARCH_WINDOW``). Results are newest first, at most
500 per page, with an opaque cursor bound to the searched chains.

No ``from __future__ import annotations``: FastAPI inspects these signatures.
"""

import asyncio
from typing import Annotated, Final

from fastapi import APIRouter, Depends, Query, Request
from neurosphere_contracts.audit.v1.audit_record import AuditRecord
from neurosphere_core.auth.scope import Permission
from neurosphere_core.paging.models import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from neurosphere_core.scope import IdentityScope

from neurosphere_api.audit.access import (
    CURSOR_PATTERN,
    SearchFilters,
    decode_cursor,
    encode_cursor,
    get_search_store,
    resolve_chains,
)
from neurosphere_api.audit.models import AuditSearchHit, AuditSearchPage
from neurosphere_api.audit.search_store import (
    AuditSearchFilter,
    AuditSearchStore,
    SearchPosition,
    position_of,
)
from neurosphere_api.authz import AuthzState, get_authz_state, require

__all__ = ["PREFIX", "build_router", "collect"]

PREFIX: Final = "/api/v1/audit/search"


async def collect(
    store: AuditSearchStore,
    chains: dict[str, str],
    flt: AuditSearchFilter,
    *,
    before: SearchPosition | None,
    limit: int,
) -> tuple[list[tuple[str, AuditRecord]], bool]:
    """The newest ``limit`` matches across ``chains`` older than ``before``, and whether more
    exist. Each chain returns at most ``limit + 1``; the merged top ``limit + 1`` is exact."""
    domains = list(chains)
    batches = await asyncio.gather(
        *(store.search(chains[d], flt, before=before, limit=limit + 1) for d in domains)
    )
    merged = [(d, r) for d, batch in zip(domains, batches, strict=True) for r in batch]
    merged.sort(key=lambda item: position_of(item[1]), reverse=True)
    return merged[:limit], len(merged) > limit


def build_router() -> APIRouter:
    router = APIRouter(tags=["audit"])

    @router.get("", response_model=AuditSearchPage)
    async def search_audit_records(
        request: Request,
        scope: Annotated[IdentityScope, Depends(require(Permission.AUDIT_READ))],
        state: Annotated[AuthzState, Depends(get_authz_state)],
        filters: Annotated[SearchFilters, Depends()],
        store: Annotated[AuditSearchStore, Depends(get_search_store)],
        cursor: Annotated[str | None, Query(pattern=CURSOR_PATTERN)] = None,
        page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    ) -> AuditSearchPage:
        chains = await resolve_chains(
            request, state, scope, filters.domains, (Permission.AUDIT_READ,)
        )
        before = decode_cursor(cursor, set(chains.values()))
        page, more = await collect(store, chains, filters.filter, before=before, limit=page_size)
        next_cursor = encode_cursor(position_of(page[-1][1])) if more and page else None
        return AuditSearchPage(
            items=tuple(AuditSearchHit(domain_id=d, record=r) for d, r in page),
            next_cursor=next_cursor,
            domains=tuple(chains),
        )

    return router
