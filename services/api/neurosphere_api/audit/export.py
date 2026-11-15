"""``GET /api/v1/audit/export?format=ndjson|csv`` (PRP-40 item 4): a bounded, audited export.

Permission: ``audit.export`` (any domain) through ``require``, then ``audit.read`` AND
``audit.export`` on every domain exported (a named domain lacking either is 403
``target_out_of_scope``, recorded). Filters and the capped window are those of
``/api/v1/audit/search``.

Order: the matching rows (at most :data:`MAX_EXPORT_ROWS`) are collected first; then an
``audit.export`` record is appended to the chain of EVERY exported domain (outcome detail
``rows_<n>_<format>``, the filters as the subject's state digest, never a record body); only
then is the response streamed. If any of those appends fails the export is refused with 503
``audit_write_failed`` and nothing is streamed. CSV cells are escaped against formula injection.

No ``from __future__ import annotations``: FastAPI inspects these signatures.
"""

import csv
import io
import json
from collections.abc import AsyncIterator, Iterable
from typing import Annotated, Any, Final, Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from neurosphere_contracts.audit.v1.audit_record import AuditRecord
from neurosphere_core.audit import AuditRepository, build_after, make_subject
from neurosphere_core.auth.scope import Permission
from neurosphere_core.errors import DependencyTransientError
from neurosphere_core.paging.models import MAX_PAGE_SIZE
from neurosphere_core.scope import IdentityScope

from neurosphere_api.audit.access import (
    SearchFilters,
    audit_context,
    get_search_store,
    resolve_chains,
)
from neurosphere_api.audit.router import get_audit_repository
from neurosphere_api.audit.search import collect
from neurosphere_api.audit.search_store import AuditSearchStore, SearchPosition, position_of
from neurosphere_api.authz import AuthzState, get_authz_state, require

__all__ = ["CSV_COLUMNS", "MAX_EXPORT_ROWS", "PREFIX", "build_router", "csv_cell"]

PREFIX: Final = "/api/v1/audit/export"
#: Row cap of one export (documented in ``docs/runbooks/audit-siem.md``).
MAX_EXPORT_ROWS: Final = 10_000
EXPORT_OPERATION: Final = "audit.export"
TRUNCATED_HEADER: Final = "X-NeuroSphere-Export-Truncated"
ROWS_HEADER: Final = "X-NeuroSphere-Export-Rows"

_MEDIA: Final = {"ndjson": "application/x-ndjson", "csv": "text/csv; charset=utf-8"}
_FORMULA_PREFIXES: Final = ("=", "+", "-", "@", "\t", "\r")

CSV_COLUMNS: Final = (
    "domain_id",
    "chain_id",
    "sequence",
    "audit_id",
    "recorded_at",
    "kind",
    "operation",
    "channel",
    "actor_pseudonym",
    "actor_kind",
    "correlation_id",
    "target",
    "outcome_result",
    "outcome_verified",
    "outcome_detail",
    "denial_code",
    "denial_reason",
    "record_hash",
)

ExportFormat = Literal["ndjson", "csv"]


def csv_cell(value: object) -> str:
    """Text of one CSV cell; a leading formula trigger is neutralised with ``'``."""
    text = "" if value is None else str(value)
    if text.startswith(_FORMULA_PREFIXES):
        return "'" + text
    return text


def _csv_values(domain_id: str, record: AuditRecord) -> list[str]:
    body: dict[str, Any] = record.model_dump(mode="json")
    actor = body.get("actor") or {}
    subject = body.get("subject") or {}
    outcome = body.get("outcome") or {}
    denial = body.get("denial") or {}
    values: list[object] = [
        domain_id,
        body.get("chain_id"),
        body.get("sequence"),
        body.get("audit_id"),
        body.get("recorded_at"),
        body.get("kind"),
        body.get("operation"),
        body.get("channel"),
        actor.get("principal_pseudonym"),
        actor.get("principal_kind"),
        body.get("correlation_id"),
        (subject.get("target") or {}).get("canonical_id"),
        outcome.get("result"),
        outcome.get("verified"),
        outcome.get("detail"),
        denial.get("code"),
        denial.get("reason"),
        body.get("record_hash"),
    ]
    return [csv_cell(v) for v in values]


def _csv_line(values: Iterable[str]) -> str:
    buffer = io.StringIO()
    csv.writer(buffer, lineterminator="\r\n").writerow(list(values))
    return buffer.getvalue()


async def _lines(rows: list[tuple[str, AuditRecord]], fmt: ExportFormat) -> AsyncIterator[bytes]:
    if fmt == "csv":
        yield _csv_line(CSV_COLUMNS).encode("utf-8")
        for domain_id, record in rows:
            yield _csv_line(_csv_values(domain_id, record)).encode("utf-8")
        return
    for domain_id, record in rows:
        line = json.dumps(
            {"domain_id": domain_id, "record": record.model_dump(mode="json")},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        yield (line + "\n").encode("utf-8")


async def _gather_rows(
    store: AuditSearchStore, chains: dict[str, str], filters: SearchFilters
) -> tuple[list[tuple[str, AuditRecord]], bool]:
    rows: list[tuple[str, AuditRecord]] = []
    before: SearchPosition | None = None
    while True:
        want = min(MAX_PAGE_SIZE, MAX_EXPORT_ROWS - len(rows))
        page, more = await collect(store, chains, filters.filter, before=before, limit=want)
        rows += page
        if not more or not page:
            return rows, False
        if len(rows) >= MAX_EXPORT_ROWS:
            return rows, True
        before = position_of(page[-1][1])


def build_router() -> APIRouter:
    router = APIRouter(tags=["audit"])

    @router.get(
        "",
        response_class=StreamingResponse,
        responses={
            200: {
                "description": "NDJSON (one record per line) or CSV with a header row",
                "content": {"application/x-ndjson": {}, "text/csv": {}},
            }
        },
    )
    async def export_audit_records(
        request: Request,
        scope: Annotated[IdentityScope, Depends(require(Permission.AUDIT_EXPORT))],
        state: Annotated[AuthzState, Depends(get_authz_state)],
        filters: Annotated[SearchFilters, Depends()],
        store: Annotated[AuditSearchStore, Depends(get_search_store)],
        repository: Annotated[AuditRepository, Depends(get_audit_repository)],
        format: ExportFormat = "ndjson",
    ) -> StreamingResponse:
        chains = await resolve_chains(
            request,
            state,
            scope,
            filters.domains,
            (Permission.AUDIT_READ, Permission.AUDIT_EXPORT),
        )
        rows, truncated = await _gather_rows(store, chains, filters)
        ctx = audit_context(request, scope, EXPORT_OPERATION)
        detail = f"rows_{len(rows)}_{format}"
        described = {
            **filters.describe(),
            "format": format,
            "row_count": len(rows),
            "truncated": truncated,
        }
        for domain_id, chain_id in chains.items():
            draft = build_after(
                ctx,
                make_subject(domain_id, "domain", state=described),
                result="succeeded",
                verified=False,
                detail=detail,
            )
            try:
                await repository.append(chain_id, draft)
            except Exception as exc:  # no audit trail, no export (fail closed)
                raise DependencyTransientError(
                    "audit write failed", reason="audit_write_failed"
                ) from exc
        extension = "ndjson" if format == "ndjson" else "csv"
        return StreamingResponse(
            _lines(rows, format),
            media_type=_MEDIA[format],
            headers={
                "Content-Disposition": f'attachment; filename="audit-export.{extension}"',
                "Cache-Control": "no-store",
                TRUNCATED_HEADER: "true" if truncated else "false",
                ROWS_HEADER: str(len(rows)),
            },
        )

    return router
