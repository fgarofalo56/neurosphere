"""Replay routes (PRP-18 item 5), mounted at ``/api/v1/replay``. GET only, read-only inspection.

| Method | Path                                  | Permission    |
|--------|---------------------------------------|---------------|
| GET    | ``/domains/{domain_id}/traces``       | ``data.read`` |
| GET    | ``/domains/{domain_id}/traces/{id}``  | ``data.read`` |

The path domain is the authorization TARGET (403 outside it, matching dashboards); the customer
comes only from the derived ``IdentityScope``. A trace id with no span in the addressed domain is
404, indistinguishable from an absent trace. Nothing here can re-run a trace, call a tool or write.

Payload bodies (PRP-104 item 5, criterion 7). The trace detail is payload-free unless ALL hold:
``include_payload=true``; the deployment allows bodies (``PayloadPolicy.allow_bodies``, derived
from the installed interaction explorer); and the caller holds ``interaction.read`` in the domain
(the privileged, time-bound ``interaction_investigator``). A caller without it, a viewer or an
admin included, gets the same payload-free detail as before, with no error. A caller with it must
send a valid ``purpose_code`` (and optional ``case_ref``), otherwise 422 before the trace is read.
The ``interaction:<id>`` pointers of the domain's ``redacted`` spans are then read through ONE
``InteractionContentReader.read_many`` call: one fail-closed ``interaction.read`` audit record per
trace read, listing the interaction ids, appended before anything is decrypted (an append failure
is 503 and nothing is decrypted). Each stored ``RedactedContent`` is attached to its span in its
JSON form; any other pointer gets no body. More than ``MAX_READ_BATCH`` distinct interactions in
one trace is 422 ``interaction_batch_too_large`` before any audit or decrypt: a silently partial
view would misstate what the investigator saw, and the per-interaction content-reads route stays
available for such traces.

While no explorer is installed the pre-PRP-104 branch (``TraceReader.read_payload``) is kept
unchanged; it is reachable only when the policy dependency is overridden (tests), and the archive
reader always returns None there.

No ``from __future__ import annotations``: FastAPI inspects these signatures.
"""

import re
from datetime import UTC, datetime
from typing import Annotated, Final

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response
from neurosphere_core.auth.scope import Permission, domains_with_permission
from neurosphere_core.errors import DependencyTransientError, InvalidSchemaError, NeuroSphereError
from neurosphere_core.interactions.capture import POINTER_PREFIX
from neurosphere_core.paging import PageRequest
from neurosphere_core.paging.models import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from neurosphere_core.scope import IdentityScope

from neurosphere_api.authz import domain_from_path, require
from neurosphere_api.authz.state import AuthzState, get_authz_state
from neurosphere_api.interactions.content import (
    MAX_READ_BATCH,
    ContentAccess,
    InteractionContentReader,
    validate_purpose,
)
from neurosphere_api.middleware import correlation_id_of
from neurosphere_api.replay.assemble import assemble_trace
from neurosphere_api.replay.dependencies import (
    PayloadPolicy,
    get_payload_policy,
    get_trace_reader,
)
from neurosphere_api.replay.models import Span, TraceDetail, TracePage
from neurosphere_api.replay.reader import TraceReader, TraceRecords
from neurosphere_api.routers import RouterRegistry

__all__ = ["BATCH_TOO_LARGE", "PREFIX", "build_router", "register"]

PREFIX: Final = "/api/v1/replay"
#: 422 reason when one trace names more interactions than one audited batch read may decrypt.
BATCH_TOO_LARGE: Final = "interaction_batch_too_large"

ReadScope = Annotated[
    IdentityScope, Depends(require(Permission.DATA_READ, domain_from_path("domain_id")))
]
Reader = Annotated[TraceReader, Depends(get_trace_reader)]
Policy = Annotated[PayloadPolicy, Depends(get_payload_policy)]
Authz = Annotated[AuthzState, Depends(get_authz_state)]
DomainPath = Annotated[str, Path(min_length=1, max_length=512)]
CursorQuery = Annotated[
    str | None, Query(min_length=1, max_length=2048, pattern=r"^[A-Za-z0-9_\-=.~]+$")
]
TraceIdPath = Annotated[str, Path(pattern=r"^[0-9a-f]{32}$")]
PurposeCodeQuery = Annotated[
    str | None,
    Query(
        min_length=1,
        max_length=64,
        description=(
            "Access purpose code. Used only with include_payload=true; required then from a "
            "caller holding interaction.read in the domain."
        ),
    ),
]
CaseRefQuery = Annotated[
    str | None,
    Query(
        min_length=1,
        max_length=128,
        description=(
            "Optional case record id, used only with include_payload=true; bound into the "
            "interaction.read audit record."
        ),
    ),
]

_INTERACTION_ID: Final = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)


def _interaction_id(pointer: str) -> str | None:
    """The interaction id of an ``interaction:<id>`` pointer; None for any other pointer."""
    if not pointer.startswith(POINTER_PREFIX):
        return None
    iid = pointer[len(POINTER_PREFIX) :]
    return iid if _INTERACTION_ID.fullmatch(iid) else None


def _domain_pointers(records: TraceRecords, domain_id: str) -> dict[str, str]:
    """span_id -> payload pointer, for this domain's spans only."""
    return {
        r.span_id: r.payload_pointer
        for r in records.spans
        if r.domain_id == domain_id and r.payload_pointer is not None
    }


def _redacted_interactions(
    records: TraceRecords, detail: TraceDetail, domain_id: str
) -> dict[str, str]:
    """span_id -> interaction id, for this domain's ``redacted`` spans with interaction pointers."""
    pointers = _domain_pointers(records, domain_id)
    out: dict[str, str] = {}
    for span in detail.spans:
        pointer = pointers.get(span.span_id)
        if span.payload_state != "redacted" or pointer is None:
            continue
        iid = _interaction_id(pointer)
        if iid is not None:
            out[span.span_id] = iid
    return out


async def _legacy_bodies(
    reader: TraceReader,
    records: TraceRecords,
    detail: TraceDetail,
    customer_id: str,
    domain_id: str,
) -> TraceDetail:
    """Pre-PRP-104 branch, only while no explorer is installed (the archive reader returns None)."""
    pointers = _domain_pointers(records, domain_id)
    spans: list[Span] = []
    for span in detail.spans:
        pointer = pointers.get(span.span_id)
        if span.payload_state == "redacted" and pointer is not None:
            body = await reader.read_payload(customer_id, domain_id, pointer)
            span = span.model_copy(update={"payload": body})
        spans.append(span)
    return detail.model_copy(update={"spans": tuple(spans)})


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
        authz: Authz,
        request: Request,
        response: Response,
        include_payload: bool = False,
        purpose_code: PurposeCodeQuery = None,
        case_ref: CaseRefQuery = None,
    ) -> TraceDetail:
        customer_id = scope.customer_id  # derived scope only
        wants_bodies = include_payload and policy.allow_bodies
        content_reader = (
            InteractionContentReader.from_app_state(request.app.state) if wants_bodies else None
        )
        now = datetime.fromtimestamp(authz.clock(), UTC)
        # Only a holder of an unexpired interaction.read in this domain reaches content; anyone
        # else gets the payload-free detail exactly as before (no error, no read, no record).
        investigator = content_reader is not None and domain_id in domains_with_permission(
            scope, Permission.INTERACTION_READ, now=now
        )
        # Purpose first: 422 before the trace or any content is read.
        purpose = (
            validate_purpose({"purpose_code": purpose_code, "case_ref": case_ref})
            if investigator
            else None
        )
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
        if not wants_bodies:
            return detail  # default: payload_state only, never a body
        if content_reader is None:
            return await _legacy_bodies(reader, records, detail, customer_id, domain_id)
        if purpose is None:
            return detail  # no interaction.read in this domain: payload-free, as before
        by_span = _redacted_interactions(records, detail, domain_id)
        ids = list(dict.fromkeys(by_span.values()))
        if len(ids) > MAX_READ_BATCH:
            raise InvalidSchemaError(
                "too many captured interactions in one trace; read them individually",
                reason=BATCH_TOO_LARGE,
            )
        response.headers["Cache-Control"] = "no-store"
        if not ids:
            return detail
        access = ContentAccess(
            scope=scope,
            now=now,
            request_id=correlation_id_of(request.scope),
            method=request.method,
            path=request.url.path,
            denials=authz.denial_recorder,
        )
        # ONE audited batch read for the whole trace: the record lists every id, then decrypts.
        contents = await content_reader.read_many(access, domain_id, ids, purpose)
        spans: list[Span] = []
        for span in detail.spans:
            iid = by_span.get(span.span_id)
            content = contents.get(iid) if iid is not None else None
            if content is not None:
                span = span.model_copy(update={"payload": content.model_dump(mode="json")})
            spans.append(span)
        return detail.model_copy(update={"spans": tuple(spans)})

    return router


def register(registry: RouterRegistry) -> None:
    registry.register(PREFIX, build_router())
