"""``AzureMonitorAiPoller``: one tick reads GenAI spans from each configured workspace.

Per workspace and per kind (``APP_GENAI_DEPENDENCIES``, ``APP_GENAI_REQUESTS``) one connector poll
runs from a stored watermark (minus the overlap) or from the first-poll lookback. Rows are mapped
with ``map_genai_row`` and posted to the ingest edge as CloudEvents under a registered producer,
exactly like the gateway poller. The connector's ``next_watermark`` is committed ONLY after every
batch of that poll was accepted; a replay is safe because event ids are ``<trace>:<span>``.

Queries are counted from ``PollResult.requests_made`` (one per slice actually sent; a poll that
raised counts one). The connector is built per poll with ``max_pages`` capped at the queries left
in the tick budget, so the budget can never be overshot.

Nothing raises out of :meth:`tick` for an upstream failure. A checkpoint-store failure DOES
propagate (the supervisor restarts the role). Statuses, counts and logs hold codes and integers
only: never a workspace id, host, URL or token.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Final, Literal

from neurosphere_connector_azure_monitor import (
    GenAiRowSkipped,
    MonitorSource,
    PollBounds,
    PollResult,
    SourceKind,
    map_genai_row,
)
from neurosphere_contracts.telemetry.v1.telemetry_event import TelemetryEvent
from neurosphere_core.errors import (
    ForbiddenError,
    NeuroSphereError,
    RateLimitedError,
    UnauthorizedError,
)
from neurosphere_core.payload import CLOUDEVENT_TYPE_TELEMETRY
from neurosphere_core.sources_status import SOURCE_ACCESS_DENIED

from neurosphere_workers.ingestion.azure_monitor_ai.settings import AzureMonitorAiSettings
from neurosphere_workers.ingestion.gateway_poll import (
    ConnectorFactory,
    IngestClient,
    IngestPostError,
)
from neurosphere_workers.runtime.checkpoint import CheckpointStore
from neurosphere_workers.sources_status.observe import RunObservation

__all__ = [
    "CHECKPOINT_PREFIX",
    "EVENT_BUDGET_EXHAUSTED",
    "GENAI_KINDS",
    "QUERY_BUDGET_EXHAUSTED",
    "REFUSED_GOVERNMENT",
    "AzureMonitorAiPoller",
    "checkpoint_key",
]

logger = logging.getLogger("neurosphere.workers.azure_monitor_ai")

QUERY_BUDGET_EXHAUSTED: Final = "query_budget_exhausted"
EVENT_BUDGET_EXHAUSTED: Final = "event_budget_exhausted"
RATE_LIMITED: Final = "rate_limited"
STALLED: Final = "stalled"
INGEST_FAILED: Final = "ingest_failed"
SOURCE_UNREACHABLE: Final = "source_unreachable"
PARTIAL_RESULTS: Final = "partial_results"
REFUSED_GOVERNMENT: Final = "refused_government_unverified"
CHECKPOINT_PREFIX: Final = "azure-monitor-ai"
GENAI_KINDS: Final = (SourceKind.APP_GENAI_DEPENDENCIES, SourceKind.APP_GENAI_REQUESTS)
_SLICE: Final = timedelta(minutes=15)
#: Most specific first: the reason a tick reports when several things went wrong.
_PRIORITY: Final = (
    SOURCE_ACCESS_DENIED,
    INGEST_FAILED,
    SOURCE_UNREACHABLE,
    RATE_LIMITED,
    STALLED,
    QUERY_BUDGET_EXHAUSTED,
    EVENT_BUDGET_EXHAUSTED,
    PARTIAL_RESULTS,
)
_FAILURES: Final = frozenset({SOURCE_ACCESS_DENIED, INGEST_FAILED, SOURCE_UNREACHABLE})


def checkpoint_key(kind: SourceKind, workspace_id: str) -> str:
    """Store-internal key (never logged): one watermark per workspace and kind."""
    return f"{CHECKPOINT_PREFIX}/{kind.value}/{workspace_id}"


def _cloud_event(event: TelemetryEvent) -> dict[str, Any]:
    data = event.model_dump(mode="json", exclude_none=True)
    return {
        "specversion": "1.0",
        "id": data["event_id"],
        "source": "neurosphere/azure-monitor-ai",
        "type": CLOUDEVENT_TYPE_TELEMETRY,
        "datacontenttype": "application/json",
        "data": data,
    }


def _parse_watermark(raw: str | None) -> datetime | None:
    if raw is None:
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


@dataclass(slots=True)
class _Tick:
    queries: int = 0
    rows: int = 0
    events_posted: int = 0
    rows_skipped: int = 0
    ok_units: int = 0
    reasons: set[str] = field(default_factory=lambda: set[str]())
    stop: bool = False
    #: Index of the unit a budget stopped at: the next tick starts there so none is starved.
    resume_at: int | None = None

    def observation(self) -> RunObservation:
        counts = {
            "queries": self.queries,
            "rows": self.rows,
            "events_posted": self.events_posted,
            "rows_skipped": self.rows_skipped,
        }
        reason = next((r for r in _PRIORITY if r in self.reasons), None)
        failed = bool(self.reasons & _FAILURES)
        if failed and self.ok_units == 0 and self.events_posted == 0:
            return RunObservation("failed", reason, counts)
        if self.reasons:
            return RunObservation("partial", reason, counts)
        return RunObservation("ok", None, counts)


class AzureMonitorAiPoller:
    def __init__(
        self,
        *,
        ingest: IngestClient,
        checkpoints: CheckpointStore,
        settings: AzureMonitorAiSettings,
        customer_id: str,
        domain_id: str,
        cloud: Literal["commercial", "government"],
        connector_factory: ConnectorFactory,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._ingest = ingest
        self._checkpoints = checkpoints
        self._settings = settings
        self._customer_id = customer_id
        self._domain_id = domain_id
        self._cloud: Literal["commercial", "government"] = cloud
        self._factory = connector_factory
        self._clock = clock
        self._status = RunObservation("idle", "no_workspaces")
        self._offset = 0

    @property
    def last_status(self) -> RunObservation:
        return self._status

    async def tick(self) -> None:
        cfg = self._settings
        if self._cloud == "government" and not cfg.allow_unverified_government:
            logger.warning(
                "azure_monitor_ai not polled: government is unverified and not opted in",
                extra={"event": "azure_monitor_ai.refused"},
            )
            self._status = RunObservation(
                "failed",
                REFUSED_GOVERNMENT,
                {"queries": 0, "rows": 0, "events_posted": 0, "rows_skipped": 0},
            )
            return
        workspaces = cfg.workspaces
        if not workspaces:
            self._status = RunObservation("idle", "no_workspaces")
            return
        state = _Tick()
        units = [(workspace, kind) for workspace in workspaces for kind in GENAI_KINDS]
        offset = self._offset % len(units)
        for step, (workspace, kind) in enumerate(units[offset:] + units[:offset]):
            if state.stop:
                break
            await self._poll_unit(state, workspace, kind, (offset + step) % len(units))
        self._offset = 0 if state.resume_at is None else state.resume_at
        self._status = state.observation()

    async def _poll_unit(self, state: _Tick, workspace: str, kind: SourceKind, index: int) -> None:
        cfg = self._settings
        remaining = cfg.max_queries_per_tick - state.queries
        if remaining <= 0:
            state.reasons.add(QUERY_BUDGET_EXHAUSTED)
            state.stop = True
            state.resume_at = index
            return
        if state.events_posted >= cfg.max_events_per_tick:
            state.reasons.add(EVENT_BUDGET_EXHAUSTED)
            state.stop = True
            state.resume_at = index
            return

        key = checkpoint_key(kind, workspace)
        stored = _parse_watermark(await self._checkpoints.get(key))  # an outage propagates
        now = self._clock()
        floor = now - timedelta(seconds=cfg.lookback_seconds)
        if stored is None:
            start = floor
        else:
            start = max(stored - timedelta(seconds=cfg.overlap_seconds), floor)

        full_pages = max(1, math.ceil(cfg.window_seconds / _SLICE.total_seconds()))
        pages = min(full_pages, remaining)
        bounds = PollBounds(
            slice_length=_SLICE,
            max_pages=pages,
            max_window=timedelta(seconds=cfg.window_seconds),
            initial_lookback=timedelta(0),
        )
        connector = self._factory(self._cloud, bounds)
        try:
            result = await connector.poll([MonitorSource(kind, workspace)], watermark=start)
        except (UnauthorizedError, ForbiddenError):
            state.queries += 1
            state.reasons.add(SOURCE_ACCESS_DENIED)
            logger.warning(
                "azure_monitor_ai workspace access denied",
                extra={"event": "azure_monitor_ai.denied"},
            )
            return
        except RateLimitedError:
            state.queries += 1
            state.reasons.add(RATE_LIMITED)
            state.stop = True  # the workspace API is throttling this principal: stop the tick
            return
        except Exception as exc:  # an upstream failure must never crash the role
            state.queries += 1
            state.reasons.add(SOURCE_UNREACHABLE)
            code = exc.code if isinstance(exc, NeuroSphereError) else type(exc).__name__
            logger.warning(
                "azure_monitor_ai poll failed",
                extra={"event": "azure_monitor_ai.poll_failed", "error": str(code)},
            )
            return
        finally:
            await connector.close()

        state.queries += max(1, result.requests_made)
        events = self._map(state, result)
        state.rows += len(result.records)

        remaining_events = cfg.max_events_per_tick - state.events_posted
        if len(events) > remaining_events and state.events_posted > 0:
            # Would overshoot the budget: leave the watermark, re-read next tick (the first poll
            # of a tick always goes through, so progress is guaranteed).
            state.reasons.add(EVENT_BUDGET_EXHAUSTED)
            state.stop = True
            state.resume_at = index
            return

        accepted = 0
        try:
            for begin in range(0, len(events), cfg.batch_size):
                accepted += await self._ingest.post(events[begin : begin + cfg.batch_size])
        except IngestPostError as exc:
            state.events_posted += accepted
            state.reasons.add(INGEST_FAILED)
            state.stop = True  # the edge is shared: no point trying the next workspace
            logger.warning(
                "azure_monitor_ai ingest post failed",
                extra={"event": "azure_monitor_ai.ingest_failed", "status": exc.status},
            )
            return
        state.events_posted += accepted

        # Only now, with every batch accepted, may the watermark move (never backwards).
        if stored is None or result.next_watermark > stored:
            await self._checkpoints.commit(key, result.next_watermark.astimezone(UTC).isoformat())
        state.ok_units += 1
        self._note_partial(state, result, index, budget_limited=pages < full_pages)

    def _map(self, state: _Tick, result: PollResult) -> list[dict[str, Any]]:
        cfg = self._settings
        events: list[dict[str, Any]] = []
        for row in result.records:
            try:
                telemetry = map_genai_row(
                    row,
                    cloud=self._cloud,
                    customer_id=self._customer_id,
                    source_id=cfg.source_id,
                    domain_id=self._domain_id,
                    app_role_names=cfg.roles,
                )
            except GenAiRowSkipped:
                state.rows_skipped += 1
                continue
            events.append(_cloud_event(telemetry))
        return events

    @staticmethod
    def _note_partial(
        state: _Tick, result: PollResult, index: int, *, budget_limited: bool
    ) -> None:
        if result.stalled_slice_start is not None:
            state.reasons.add(STALLED)
            logger.warning(
                "azure_monitor_ai stalled: a slice stays truncated at the minimum slice length",
                extra={"event": "azure_monitor_ai.stalled"},
            )
        elif result.rate_limited:
            state.reasons.add(RATE_LIMITED)
            state.stop = True
        elif result.failed_sources or result.truncated_pages:
            state.reasons.add(PARTIAL_RESULTS)
        elif result.partial and budget_limited:
            state.reasons.add(QUERY_BUDGET_EXHAUSTED)
            state.stop = True
            state.resume_at = index
        # Otherwise partial only means the window cap was hit: the rest is read next tick.
