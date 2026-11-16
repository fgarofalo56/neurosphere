"""Catalog ownership and recertification evidence (PRP-56 item 3).

Reads the active ``owner`` entities of one domain through the scope-filtered catalog repository
and counts them. Counts and timestamps only: no owner name, kind or id leaves this module.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from neurosphere_contracts.compliance.v1.evidence_observation import EvidenceObservation

from neurosphere_core.catalog.protocol import CatalogRepository, EntityFilter
from neurosphere_core.compliance.sources.base import (
    SourceRequest,
    make_observation,
    parse_utc,
    unavailable,
)
from neurosphere_core.paging import PageRequest

__all__ = ["CatalogOwnershipSource"]

_PAGE = 100
_MEASURES = (
    "records",
    "owners_with_recertify_by",
    "owners_overdue",
    "owners_recertified_in_window",
)


class CatalogOwnershipSource:
    source_id = "catalog_ownership"

    def __init__(self, repository: CatalogRepository | None) -> None:
        self._repository = repository

    async def observe(self, request: SourceRequest) -> EvidenceObservation:
        if self._repository is None:
            return unavailable(self.source_id, request, "store_unconfigured", _MEASURES)
        flt = EntityFilter(
            entity_types=["owner"],
            domain_ids=[request.domain_id],
            lifecycle_statuses=["active"],
        )
        owners = scheduled = overdue = recertified = 0
        latest: datetime | None = None
        cursor: str | None = None
        truncated = False
        try:
            while True:
                size = min(_PAGE, request.cap - owners)
                page = await self._repository.list_entities(
                    request.scope, flt, PageRequest(page_size=size, cursor=cursor)
                )
                for entity in page.items:
                    body: dict[str, Any] = entity.model_dump(mode="json")
                    owners += 1
                    by, at = body.get("recertify_by"), body.get("recertified_at")
                    if isinstance(by, str):
                        scheduled += 1
                        if parse_utc(by) < request.window_end:
                            overdue += 1
                    if isinstance(at, str):
                        moment = parse_utc(at)
                        if request.window_start <= moment < request.window_end:
                            recertified += 1
                        if latest is None or moment > latest:
                            latest = moment
                cursor = page.next_cursor
                if cursor is None:
                    break
                if owners >= request.cap:
                    truncated = True
                    break
        except Exception:
            return unavailable(self.source_id, request, "store_error", _MEASURES)
        return make_observation(
            self.source_id,
            request,
            status="partial" if truncated else "observed",
            reason_code="capped" if truncated else None,
            latest_at=latest,
            truncated=truncated,
            measures={
                "records": owners,
                "owners_with_recertify_by": scheduled,
                "owners_overdue": overdue,
                "owners_recertified_in_window": recertified,
            },
        )
