"""Replay routes (PRP-18 item 5), mounted at ``/api/v1/replay``. GET only, read-only inspection.

| Method | Path                                  | Permission    |
|--------|---------------------------------------|---------------|
| GET    | ``/domains/{domain_id}/traces``       | ``data.read`` |
| GET    | ``/domains/{domain_id}/traces/{id}``  | ``data.read`` |

The path domain is the authorization TARGET (403 outside it, matching dashboards); the customer
comes only from the derived ``IdentityScope``. A trace id with no span in the addressed domain is
404, indistinguishable from an absent trace. Nothing here can re-run a trace, call a tool or write.

No ``from __future__ import annotations``: FastAPI inspects these signatures.
"""

from typing import Annotated, Final

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from neurosphere_core.auth.scope import Permission
from neurosphere_core.errors import DependencyTransientError, NeuroSphereError
from neurosphere_core.paging import PageRequest
from neurosphere_core.paging.models import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from neurosphere_core.scope import IdentityScope

from neurosphere_api.authz import domain_from_path, require
from neurosphere_api.replay.assemble import assemble_trace
from neurosphere_api.replay.dependencies import (
    PayloadPolicy,
    get_payload_policy,
    get_trace_reader,
)
from neurosphere_api.replay.models import TraceDetail, TracePage
from neurosphere_api.replay.reader import TraceReader
from neurosphere_api.routers import RouterRegistry

__all__ = ["PREFIX", "build_router", "register"]

PREFIX: Final = "/api/v1/replay"

ReadScope = Annotated[
    IdentityScope, Depends(require(Permission.DATA_READ, domain_from_path("domain_id")))
]
Reader = Annotated[TraceReader, Depends(get_trace_reader)]
Policy = Annotated[PayloadPolicy, Depends(get_payload_policy)]
DomainPath = Annotated[str, Path(min_length=1, max_length=512)]
CursorQuery = Annotated[
    str | None, Query(min_length=1, max_length=2048, pattern=r"^[A-Za-z0-9_\-=.~]+$")
]
TraceIdPath = Annotated[str, Path(pattern=r"^[0-9a-f]{32}$")]


def build_router() -> APIRouter:
    router = APIRouter(tags=["replay"])

    @router.get("/domains/{domain_id}/traces", response_model=TracePage)
    async def list_traces(
        domain_id: DomainPath,
        scope: ReadScope,
        reader: Reader,
        cursor: CursorQuery = None,
        page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    ) -> TracePage:
        try:
            page = await reader.list_traces(
                scope.customer_id, domain_id, PageRequest(page_size=page_size, cursor=cursor)
            )
        except NeuroSphereError:
            raise
        except Exception as exc:
            raise DependencyTransientError(
                "trace archive is unavailable", reason="traces_unavailable"
            ) from exc
        return TracePage(items=page.items, next_cursor=page.next_cursor)

    @router.get("/domains/{domain_id}/traces/{trace_id}", response_model=TraceDetail)
    async def get_trace(
        domain_id: DomainPath,
        trace_id: TraceIdPath,
        scope: ReadScope,
        reader: Reader,
        policy: Policy,
        include_payload: bool = False,
    ) -> TraceDetail:
        customer_id = scope.customer_id  # derived scope only
        try:
            records = await reader.get_trace(customer_id, domain_id, trace_id)
        except NeuroSphereError:
            raise
        except Exception as exc:
            raise DependencyTransientError(
                "trace archive is unavailable", reason="traces_unavailable"
            ) from exc
        detail = assemble_trace(records, domain_id, trace_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="not found")
        if not (include_payload and policy.allow_bodies):
            return detail  # default: payload_state only, never a body
        pointers = {
            r.span_id: r.payload_pointer
            for r in records.spans
            if r.domain_id == domain_id and r.payload_pointer is not None
        }
        spans = []
        for span in detail.spans:
            pointer = pointers.get(span.span_id)
            if span.payload_state == "redacted" and pointer is not None:
                body = await reader.read_payload(customer_id, domain_id, pointer)
                span = span.model_copy(update={"payload": body})
            spans.append(span)
        return detail.model_copy(update={"spans": tuple(spans)})

    return router


def register(registry: RouterRegistry) -> None:
    registry.register(PREFIX, build_router())
