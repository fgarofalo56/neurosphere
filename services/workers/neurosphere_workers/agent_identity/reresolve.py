"""Re-resolution job: re-apply archived telemetry after an alias was declared (PRP-137 item 4).

Events are resolved at read time (clarification 1), so an event already folded into the
aggregates under its derived id stays there until its contribution is re-applied. This job finds
the archived telemetry of one ``(source, external agent id)`` inside the aggregates window and
feeds each event through the aggregates and catalog handlers again with a synthetic outbox entry.
The handlers must be built on the resolving source so the new alias applies.

Why the old derived series disappears: ``AggregateProjection._apply`` replaces the contribution
with the same id (``event-<doc_id>``) and rebuilds every bucket of the previous and the new
contribution from the full member list; ``replace_bucket`` deletes documents not in the rebuilt
set. The domain is not part of the agent id, so both land in the same buckets.

``moved`` means: a stored contribution existed before the re-apply and its ``agent_id`` differs
after it. A re-apply that changes nothing (second run) is counted in ``reapplied`` but not
``moved``, so ``moved == 0`` on an idempotent second run.

Scope: records of another customer are counted and never processed; no customer refuses to run.
Scan bound: ``max_events`` records are examined, then ``truncated`` is set when more remain.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from neurosphere_contracts.telemetry.v1.telemetry_event import TelemetryEvent
from neurosphere_core.agent_identity import ResolutionStats, slug
from neurosphere_core.aggregates import AggregateStore

from neurosphere_workers.aggregates.handler import AggregateProjection, window_start
from neurosphere_workers.aggregates.mapping import EVENT_PREFIX
from neurosphere_workers.projections.outbox import OutboxEntry
from neurosphere_workers.runtime.archive_reader import ArchiveReader

__all__ = [
    "EntryHandler",
    "ReresolveError",
    "ReresolveReport",
    "reresolve_external_id",
]


class ReresolveError(ValueError):
    """The job was asked to run with unusable arguments (for example no customer)."""


class EntryHandler(Protocol):
    async def handle(self, entry: OutboxEntry) -> None: ...


@dataclass(slots=True)
class ReresolveReport:
    """Counters only; no event content."""

    customer_id: str
    source_id: str
    window_start: str
    since: str | None = None
    examined: int = 0
    matched: int = 0
    reapplied: int = 0
    moved: int = 0
    skipped_out_of_window: int = 0
    skipped_foreign_customer: int = 0
    skipped_unreadable: int = 0
    truncated: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _utc(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(UTC)


def _parse_since(since: datetime | None) -> datetime | None:
    if since is None:
        return None
    return since.replace(tzinfo=UTC) if since.tzinfo is None else since.astimezone(UTC)


def _telemetry_event(doc: dict[str, Any]) -> TelemetryEvent | None:
    message = doc.get("message")
    if not isinstance(message, dict) or message.get("kind") != "telemetry":
        return None
    try:
        return TelemetryEvent.model_validate(doc.get("contract"))
    except ValueError:
        return None


async def _agent_of(
    store: AggregateStore, customer_id: str, doc_id: str
) -> tuple[bool, str | None]:
    found = await store.get_contribution(customer_id, EVENT_PREFIX + doc_id)
    if found is None or found.event is None:
        return False, None
    return True, found.event.agent_id


async def reresolve_external_id(
    *,
    customer_id: str,
    source_id: str,
    external_agent_id: str,
    reader: ArchiveReader,
    aggregates: AggregateProjection,
    store: AggregateStore,
    catalog: EntryHandler | None,
    max_events: int,
    since: datetime | None = None,
    resolver_stats: ResolutionStats | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> ReresolveReport:
    """Re-apply the archived telemetry of ``external_agent_id`` in ``source_id``.

    ``aggregates`` and ``catalog`` must read events through the resolving source, and ``store`` is
    the aggregate store behind ``aggregates`` (read only, to tell whether a contribution moved).
    """
    if not customer_id or not customer_id.strip():
        raise ReresolveError("customer id is required")
    if not source_id or not external_agent_id:
        raise ReresolveError("source id and external agent id are required")
    if max_events < 1:
        raise ReresolveError("max_events must be at least 1")
    floor = window_start(clock())
    lower = _parse_since(since)
    report = ReresolveReport(
        customer_id=customer_id,
        source_id=source_id,
        window_start=floor.isoformat(),
        since=None if lower is None else lower.isoformat(),
    )
    wanted_source = slug(source_id, "trace")
    names = await reader.names(customer_id, force=True)
    report.truncated = bool(getattr(reader, "truncated", False))
    ordered = sorted(names.items(), key=lambda kv: kv[1])
    for index, (doc_id, name) in enumerate(ordered):
        if index >= max_events:
            report.truncated = True
            break
        report.examined += 1
        doc = await reader.read(customer_id, name)
        if doc is None:
            report.skipped_unreadable += 1
            continue
        event = _telemetry_event(doc)
        if event is None:
            continue
        if event.customer_id.root != customer_id:
            report.skipped_foreign_customer += 1
            continue
        if (
            slug(event.source_id.root, "trace") != wanted_source
            or event.external_agent_id is None
            or event.external_agent_id.root != external_agent_id
        ):
            continue
        report.matched += 1
        moment = _utc(event.event_time.root)
        if moment < floor or (lower is not None and moment < lower):
            report.skipped_out_of_window += 1
            continue
        entry = OutboxEntry(
            id=doc_id,
            customer_id=customer_id,
            kind="event",
            ref_id=doc_id,
            entity="event",
            source_id=event.source_id.root,
            event_kind="telemetry",
            occurred_at=event.event_time.root,
        )
        had, before = await _agent_of(store, customer_id, doc_id)
        await aggregates.handle(entry)
        if catalog is not None:
            await catalog.handle(entry)
        has, after = await _agent_of(store, customer_id, doc_id)
        report.reapplied += 1
        if had and has and before != after:
            report.moved += 1
            if resolver_stats is not None:
                resolver_stats.contributions_moved += 1
    return report
