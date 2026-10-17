"""Catalog sink handler for ``OutboxReader.drain(SINK_CATALOG, ...)`` (PRP-10 item 3).

Per ``event`` outbox entry: load the trace event, map its span to inferred edges, then for each
edge ``rules.merge_observation`` -> ``put_edge`` (ETag) -> ``record_observation``, and enqueue a
``ReviewItem`` when re-inference conflicts with a lock or a curated reject.

Delivery is at-least-once, so everything is idempotent: edge IDs and observation IDs are
deterministic, an unchanged edge is not rewritten, and review items are idempotent by ID.
The handler RAISES on any failure (transient repo error, missing event, stale version past the
retry bound), so ``OutboxReader`` never advances the checkpoint past an entry that is not durable.
The durable write order (edge, then observation, then review item) converges on replay after a
crash between any two of them.

The worker writes only inside its derived ``IdentityScope``: an event whose cloud, customer or
domain the scope does not cover is skipped and counted, never written and never an exception that
would wedge the checkpoint.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Final, Protocol, runtime_checkable

from neurosphere_contracts.telemetry.v1.telemetry_event import TelemetryEvent
from neurosphere_core.catalog.protocol import AliasKey, CatalogRepository
from neurosphere_core.catalog.review_queue import ReviewQueue
from neurosphere_core.catalog.rules import MergeOutcome, format_timestamp, merge_observation
from neurosphere_core.errors import DependencyTransientError, ForbiddenError, StaleVersionError
from neurosphere_core.scope import IdentityScope

from neurosphere_workers.projections.catalog.mapping import (
    EdgeCandidate,
    build_edge,
    delegation_candidate,
    deterministic_model_id,
    model_alias_value,
    model_call_candidate,
    slug,
    tool_call_candidates,
)
from neurosphere_workers.projections.catalog.scope import ScopeProvider
from neurosphere_workers.projections.catalog.source import LoadedEvent, TraceEventSource
from neurosphere_workers.projections.outbox import OutboxEntry

MAX_STALE_RETRIES: Final = 3
"""Attempts per edge when ``put_edge`` loses an ETag race (re-read and re-merge each time)."""


@runtime_checkable
class ModelDeploymentResolver(Protocol):
    async def resolve(self, scope: IdentityScope, event: TelemetryEvent) -> str | None:
        """Canonical model-deployment ID for a ``model_call`` span, or None to skip it."""
        raise NotImplementedError


class DeterministicModelResolver:
    """``cloud:customer:source:model_deployment:model-version``; no catalog lookup."""

    async def resolve(self, scope: IdentityScope, event: TelemetryEvent) -> str | None:
        return deterministic_model_id(event)


class AliasModelResolver:
    """Resolve ``provider/model/version`` through a ``source_native_id`` alias, else fall back."""

    def __init__(self, repository: CatalogRepository) -> None:
        self._repo = repository

    async def resolve(self, scope: IdentityScope, event: TelemetryEvent) -> str | None:
        value = model_alias_value(event)
        if value is not None:
            key = AliasKey(
                alias_source_id=slug(event.source_id.root, "trace"),
                alias_kind="source_native_id",
                alias_value=value,
            )
            found = await self._repo.resolve_alias(scope, key)
            if found is not None:
                return found
        return deterministic_model_id(event)


@dataclass(slots=True)
class ProjectionStats:
    """Counters for observability and tests; never contain event content."""

    entries: int = 0
    non_event: int = 0
    no_candidates: int = 0
    edges_written: int = 0
    edges_unchanged: int = 0
    observations_recorded: int = 0
    observations_replayed: int = 0
    review_items: int = 0
    skipped_out_of_scope: int = 0
    stale_retries: int = 0
    by_rule: dict[str, int] = field(default_factory=dict)


def _utcnow() -> datetime:
    return datetime.now(UTC)


class CatalogProjection:
    """Idempotent catalog projection. ``handle`` is the ``SinkHandler`` for ``SINK_CATALOG``."""

    def __init__(
        self,
        *,
        repository: CatalogRepository,
        review_queue: ReviewQueue,
        source: TraceEventSource,
        scope_provider: ScopeProvider,
        model_resolver: ModelDeploymentResolver | None = None,
        clock: Callable[[], datetime] = _utcnow,
        max_stale_retries: int = MAX_STALE_RETRIES,
    ) -> None:
        if max_stale_retries < 1:
            raise ValueError("max_stale_retries must be >= 1")
        self._repo = repository
        self._queue = review_queue
        self._source = source
        self._scopes = scope_provider
        self._models = model_resolver or DeterministicModelResolver()
        self._clock = clock
        self._max_attempts = max_stale_retries
        self.stats = ProjectionStats()

    async def handle(self, entry: OutboxEntry) -> None:
        self.stats.entries += 1
        if entry.kind != "event" or entry.event_kind == "cost":
            self.stats.non_event += 1  # ledger changes and cost events carry no trace spans
            return
        scope = await self._scopes.get()
        if entry.customer_id != scope.customer_id:
            raise ForbiddenError("outbox entry belongs to another customer than the worker scope")
        loaded = await self._source.get_event(entry.customer_id, entry.ref_id)
        if loaded is None:
            # Archive write precedes the outbox entry, so absence is a lag or storage fault: retry.
            raise DependencyTransientError(
                "trace event is not readable yet", reason="trace_event_missing"
            )
        candidates = await self._candidates(scope, loaded, entry.customer_id)
        if not candidates:
            self.stats.no_candidates += 1
            return
        for candidate in candidates:
            await self._apply(scope, candidate)

    async def __call__(self, entry: OutboxEntry) -> None:
        await self.handle(entry)

    # ------------------------------------------------------------------ mapping

    async def _candidates(
        self, scope: IdentityScope, loaded: LoadedEvent, customer_id: str
    ) -> list[EdgeCandidate]:
        event = loaded.event
        found: list[EdgeCandidate | None] = []
        if event.span_kind == "model_call":
            found.append(model_call_candidate(loaded, await self._models.resolve(scope, event)))
        elif event.span_kind == "tool_call":
            found.extend(tool_call_candidates(loaded))
        elif event.span_kind == "delegation" and event.trace_id and event.span_id:
            children = await self._source.find_child_spans(
                customer_id, event.trace_id.root, event.span_id.root
            )
            found.extend(delegation_candidate(loaded, child) for child in children)
        elif event.span_kind == "agent_run" and event.trace_id and event.parent_span_id:
            parent = await self._source.find_span(
                customer_id, event.trace_id.root, event.parent_span_id.root
            )
            if parent is not None:
                found.append(delegation_candidate(parent, loaded))
        return [c for c in found if c is not None]

    # ------------------------------------------------------------------ durable write

    async def _apply(self, scope: IdentityScope, candidate: EdgeCandidate) -> None:
        if (
            candidate.cloud != scope.cloud
            or candidate.customer_id != scope.customer_id
            or candidate.domain_id not in scope.allowed_domains
        ):
            self.stats.skipped_out_of_scope += 1
            return
        now = self._clock()
        outcome = await self._store_edge(scope, candidate, now)
        if await self._repo.record_observation(scope, outcome.observation):
            self.stats.observations_recorded += 1
        else:
            self.stats.observations_replayed += 1
        if outcome.review_item is not None and await self._queue.enqueue(
            scope, outcome.review_item
        ):
            self.stats.review_items += 1
        self.stats.by_rule[candidate.rule] = self.stats.by_rule.get(candidate.rule, 0) + 1

    async def _store_edge(
        self, scope: IdentityScope, candidate: EdgeCandidate, now: datetime
    ) -> MergeOutcome:
        """Merge into the stored edge and write it; re-read and retry on an ETag race."""
        new_edge = build_edge(candidate, format_timestamp(now))
        attempt = 0
        while True:
            attempt += 1
            existing = await self._repo.get_edge(scope, candidate.edge_id)
            overrides = await self._repo.list_overrides(scope, candidate.edge_id)
            outcome = merge_observation(existing, new_edge, overrides, now)
            try:
                if existing is None:
                    await self._repo.put_edge(scope, outcome.stored, None)
                    self.stats.edges_written += 1
                elif outcome.stored.model_copy(update={"updated_at": existing.updated_at}) == (
                    existing
                ):
                    self.stats.edges_unchanged += 1  # replay: nothing new to store
                else:
                    await self._repo.put_edge(scope, outcome.stored, existing.etag.root)
                    self.stats.edges_written += 1
            except StaleVersionError:
                self.stats.stale_retries += 1
                if attempt >= self._max_attempts:
                    raise
                continue
            return outcome
