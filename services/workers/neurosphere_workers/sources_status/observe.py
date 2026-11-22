"""Map what a poller already keeps about its last tick to a run observation (PRP-139 item 3).

Each function reads status codes and counters only (never a project, gateway or storage name)
and returns a :class:`RunObservation`: state, reason CODE and integer counts. A 401 or 403 from
the provider becomes ``source_access_denied`` through the core classifier.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Final

from neurosphere_core.sources_status import SOURCE_ACCESS_DENIED, RunState, classify_failure

from neurosphere_workers.ingestion.billing_export.runner import TickStatus
from neurosphere_workers.ingestion.foundry_discovery.poller import TickStats

__all__ = [
    "RunObservation",
    "observe_billing",
    "observe_foundry",
    "observe_gateway",
]

SOURCE_UNREACHABLE: Final = "source_unreachable"
PARTIAL_RESULTS: Final = "partial_results"
INGEST_FAILED: Final = "ingest_failed"
CLOUD_NOT_SUPPORTED: Final = "cloud_not_supported"
INCOMPLETE_EXPORT: Final = "incomplete_export"
UNCHANGED: Final = "unchanged"
_GATEWAY_PARTIAL: Final = frozenset({"partial", "rate_limited", "stalled"})
_GATEWAY_CLOUD: Final = frozenset({"cloud_mismatch", "refused_government_unverified"})


@dataclass(frozen=True, slots=True)
class RunObservation:
    state: RunState
    reason: str | None = None
    counts: dict[str, int] = field(default_factory=lambda: dict[str, int]())


def observe_foundry(stats: TickStats) -> RunObservation:
    statuses = list(stats.status.values())
    if not statuses:
        return RunObservation("idle", "no_projects")
    failed = [s for s in statuses if s.startswith("failed")]
    partial = [s for s in statuses if s == "partial"]
    counts = {
        "projects_ok": len(statuses) - len(failed) - len(partial),
        "projects_partial": len(partial),
        "projects_failed": len(failed),
        "records": stats.created + stats.existing,
        "entities_created": stats.created,
        "skipped_invalid": stats.skipped_invalid,
        "collisions": stats.collisions,
    }
    denied = any(classify_failure(s) is not None for s in failed)
    failure_reason = SOURCE_ACCESS_DENIED if denied else SOURCE_UNREACHABLE
    if failed and len(failed) == len(statuses):
        return RunObservation("failed", failure_reason, counts)
    if failed:
        return RunObservation(
            "partial", SOURCE_ACCESS_DENIED if denied else PARTIAL_RESULTS, counts
        )
    if partial:
        return RunObservation("partial", PARTIAL_RESULTS, counts)
    return RunObservation("ok", None, counts)


def observe_billing(status: TickStatus) -> RunObservation:
    counts = {
        "records": status.posted,
        "skipped_null_cost": status.skipped_null_cost,
        "skipped_unmappable": status.skipped_unmappable,
        "rows_dropped_no_date": status.rows_dropped_no_date,
        "blobs_missing": len(status.blobs_missing),
        "held_open_period": status.held_open_period,
        "restated": status.restated,
    }
    code = status.status
    if code == "idle":
        return RunObservation("idle", None, counts)
    if code == "read_failed":
        # The poller keeps no error class for a failed blob read; the export container is the
        # only thing read, so the missing Storage Blob Data Reader role is the stated cause.
        return RunObservation("failed", SOURCE_ACCESS_DENIED, counts)
    if code == "ingest_failed":
        return RunObservation("failed", INGEST_FAILED, counts)
    if code == "incomplete":
        return RunObservation("partial", INCOMPLETE_EXPORT, counts)
    if code == "unchanged":
        return RunObservation("ok", UNCHANGED, counts)
    return RunObservation("ok", None, counts)


def _gateway_failure(code: str) -> str:
    denied = classify_failure(code)
    if denied is not None:
        return denied
    if code == INGEST_FAILED:
        return INGEST_FAILED
    if code in _GATEWAY_CLOUD:
        return CLOUD_NOT_SUPPORTED
    return SOURCE_UNREACHABLE


def observe_gateway(outcomes: Sequence[str]) -> RunObservation:
    """One tick's per-gateway ``poll_status`` codes."""
    if not outcomes:
        return RunObservation("idle", "no_gateways")
    failures = [_gateway_failure(c) for c in outcomes if c != "ok" and c not in _GATEWAY_PARTIAL]
    partial = [c for c in outcomes if c in _GATEWAY_PARTIAL]
    counts = {
        "gateways_polled": len(outcomes) - len(failures),
        "gateways_partial": len(partial),
        "gateways_failed": len(failures),
    }
    reason = SOURCE_ACCESS_DENIED if SOURCE_ACCESS_DENIED in failures else None
    if failures and len(failures) == len(outcomes):
        return RunObservation("failed", reason or failures[0], counts)
    if failures:
        return RunObservation("partial", reason or failures[0], counts)
    if partial:
        return RunObservation("partial", PARTIAL_RESULTS, counts)
    return RunObservation("ok", None, counts)
