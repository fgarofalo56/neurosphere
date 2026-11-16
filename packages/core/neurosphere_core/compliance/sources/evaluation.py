"""Evaluation result evidence (PRP-56 item 3).

Counts the domain's evaluation results completed in the window through the bounded
``results_window`` read. No score, subject id, dataset or judge detail leaves this module.
"""

from __future__ import annotations

from datetime import datetime

from neurosphere_contracts.compliance.v1.evidence_observation import EvidenceObservation

from neurosphere_core.compliance.sources.base import (
    SourceRequest,
    make_observation,
    parse_utc,
    unavailable,
)
from neurosphere_core.evaluation.store import EvaluationStore

__all__ = ["EvaluationResultsSource"]

_MEASURES = ("records", "results_completed", "results_partial_or_failed")


class EvaluationResultsSource:
    source_id = "evaluation_results"

    def __init__(self, store: EvaluationStore | None) -> None:
        self._store = store

    async def observe(self, request: SourceRequest) -> EvidenceObservation:
        if self._store is None:
            return unavailable(self.source_id, request, "store_unconfigured", _MEASURES)
        try:
            window = await self._store.results_window(
                request.scope, request.domain_id, since=request.window_start, limit=request.cap
            )
        except Exception:
            return unavailable(self.source_id, request, "store_error", _MEASURES)
        total = completed = other = 0
        latest: datetime | None = None
        for result in window.items:
            moment = parse_utc(result.completed_at.root)
            if moment >= request.window_end:
                continue
            total += 1
            if result.status == "completed":
                completed += 1
            else:
                other += 1
            if latest is None or moment > latest:
                latest = moment
        return make_observation(
            self.source_id,
            request,
            status="partial" if window.truncated else "observed",
            reason_code="capped" if window.truncated else None,
            latest_at=latest,
            truncated=window.truncated,
            measures={
                "records": total,
                "results_completed": completed,
                "results_partial_or_failed": other,
            },
        )
