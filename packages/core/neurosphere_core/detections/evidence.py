"""``configuration_findings`` evidence source for compliance bundles (PRP-61 item 5).

Counts open (unexpired) detection findings of one domain per kind, read through the existing
``RecommendationStore``. Counts, timestamps and ids only. A count says how many findings the
detections role has stored and not yet expired; it says nothing about whether the estate meets a
control (the bundle collects and maps, it never judges).
"""

from __future__ import annotations

from neurosphere_contracts.compliance.v1.evidence_observation import EvidenceObservation

from neurosphere_core.compliance.sources.base import (
    SourceRequest,
    make_observation,
    parse_utc,
    unavailable,
)
from neurosphere_core.detections.models import (
    KIND_CONFIGURATION_FINDING,
    KIND_UNREGISTERED_AI_RESOURCE,
)
from neurosphere_core.recommendations.store import RecommendationStore

__all__ = ["ConfigurationFindingsSource"]

_PAGE = 100
_MEASURES = ("records", KIND_CONFIGURATION_FINDING, KIND_UNREGISTERED_AI_RESOURCE)


class ConfigurationFindingsSource:
    source_id = "configuration_findings"

    def __init__(self, store: RecommendationStore | None) -> None:
        self._store = store

    async def observe(self, request: SourceRequest) -> EvidenceObservation:
        if self._store is None:
            return unavailable(self.source_id, request, "store_unconfigured", _MEASURES)
        counts = dict.fromkeys(_MEASURES[1:], 0)
        total = 0
        latest = None
        truncated = False
        try:
            for kind in counts:
                cursor: str | None = None
                while True:
                    page = await self._store.list(
                        request.scope,
                        request.domain_id,
                        kind=kind,
                        cursor=cursor,
                        limit=min(_PAGE, request.cap),
                    )
                    for rec in page.items:
                        if total >= request.cap:
                            truncated = True
                            break
                        expires = rec.expires_at
                        if expires is not None and parse_utc(expires.root) <= request.window_end:
                            continue  # retired: expiry is how a finding that stopped applying goes
                        counts[kind] += 1
                        total += 1
                        created = parse_utc(rec.created_at.root)
                        if latest is None or created > latest:
                            latest = created
                    cursor = page.next_cursor
                    if truncated or cursor is None:
                        break
                if truncated:
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
            measures={"records": total, **counts},
        )
