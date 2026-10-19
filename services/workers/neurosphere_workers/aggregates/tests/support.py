"""Builders for the aggregates tests (synthetic data only, in-memory stores, no Azure calls)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal

from neurosphere_contracts.telemetry.v1.telemetry_event import TelemetryEvent
from neurosphere_core.aggregates import AggregateStore, AggregateWindow, InMemoryAggregateStore
from neurosphere_core.ledger import (
    AllocationRecord,
    InMemoryLedgerStore,
    LedgerEntry,
    Observation,
    PriceTable,
    PriceVersion,
    fold_entry,
)
from neurosphere_core.ledger.models import allocation_id, entry_id

from neurosphere_workers.aggregates import AggregateProjection, StoreLedgerSource
from neurosphere_workers.projections.catalog import InMemoryTraceEventSource, LoadedEvent
from neurosphere_workers.projections.outbox import (
    SINK_AGGREGATES,
    InMemoryCheckpointStore,
    InMemoryOutboxStore,
    OutboxEntry,
    OutboxReader,
    ledger_change_outbox_id,
)

CUST = "cust-1"
DOMAIN = "dom-a"
NOW = datetime(2026, 10, 19, 12, 0, 0, tzinfo=UTC)
CATEGORY = "model_inference"

PRICES = PriceTable(
    [
        PriceVersion(
            price_version_id="pv-1",
            effective_date=date(2026, 1, 1),
            currency="USD",
            source="synthetic",
            rates=[],
        )
    ]
)

SourceKind = Literal["gateway", "application", "billing"]


def days_ago(days: float, *, hour: int | None = None) -> datetime:
    moment = NOW - timedelta(days=days)
    return moment if hour is None else moment.replace(hour=hour, minute=0)


def doc_id(n: int) -> str:
    return f"{n:064x}"


def observation(
    source: SourceKind,
    n: int,
    amount: str | None,
    *,
    at: datetime,
    kind: Literal["estimated", "invoiced"] | None = None,
    currency: str | None = "USD",
    domain: str | None = DOMAIN,
    price_version: str | None = "pv-1",
    unresolved: bool = False,
) -> Observation:
    resolved_kind = kind or ("invoiced" if source == "billing" else "estimated")
    return Observation(
        observation_kind=source,
        doc_id=doc_id(n),
        kind=resolved_kind,
        amount=None if amount is None else Decimal(amount),
        currency=currency if amount is not None else None,
        price_version_id=(
            price_version if resolved_kind == "estimated" and not unresolved else None
        ),
        price_unresolved=unresolved,
        observed_at=at,
        cloud="commercial",
        source_id="src-1",
        domain_id=domain,
    )


def ledger_entry(request_id: str, *observations: Observation) -> LedgerEntry:
    return fold_entry(CUST, request_id, CATEGORY, list(observations))


def event_doc(
    event_id: str,
    *,
    at: datetime,
    duration_ms: int | None,
    outcome: str | None = "success",
    domain: str | None = DOMAIN,
    span_kind: str = "model_call",
) -> LoadedEvent:
    body: dict[str, Any] = {
        "schema_version": "1.0.0",
        "event_id": event_id,
        "event_time": at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "cloud": "commercial",
        "customer_id": CUST,
        "source_id": "src-1",
        "span_kind": span_kind,
        "outcome": outcome,
    }
    if duration_ms is not None:
        body["duration_ms"] = duration_ms
    if domain is not None:
        body["domain_id"] = domain
    event = TelemetryEvent.model_validate(body)
    return LoadedEvent(doc_id=f"ev-{event_id}", event=event)


def entry_pointer(entry: LedgerEntry) -> OutboxEntry:
    assert entry.id == entry_id(entry.customer_id, entry.request_id, entry.cost_category)
    return OutboxEntry(
        id=ledger_change_outbox_id(entry.id, entry.content_hash),
        customer_id=entry.customer_id,
        kind="ledger_change",
        ref_id=entry.id,
        entity="ledger_entry",
        content_hash=entry.content_hash,
    )


def allocation_pointer(record: AllocationRecord) -> OutboxEntry:
    return OutboxEntry(
        id=ledger_change_outbox_id(record.id, record.content_hash),
        customer_id=record.customer_id,
        kind="ledger_change",
        ref_id=record.id,
        entity="allocation",
        content_hash=record.content_hash,
    )


def event_pointer(loaded: LoadedEvent) -> OutboxEntry:
    return OutboxEntry(
        id=loaded.doc_id,
        customer_id=CUST,
        kind="event",
        ref_id=loaded.doc_id,
        entity="event",
        event_kind="telemetry",
    )


def vendor_allocation(
    n: int, amount: str | None, *, at: datetime, currency: str | None = "USD"
) -> AllocationRecord:
    return AllocationRecord(
        id=allocation_id(CUST, doc_id(n)),
        customer_id=CUST,
        granularity="vendor_period",
        observation_doc_id=doc_id(n),
        observation_kind="billing",
        kind="invoiced",
        currency=currency if amount is not None else None,
        amount=None if amount is None else Decimal(amount),
        cloud="commercial",
        source_id="src-1",
        domain_id=DOMAIN,
        observed_at=at,
    ).with_hash()


class Rig:
    """Outbox, checkpoints, ledger and aggregates wired together over in-memory stores."""

    def __init__(self, now: datetime = NOW, store: AggregateStore | None = None) -> None:
        self.now = now
        self.outbox = InMemoryOutboxStore()
        self.checkpoints = InMemoryCheckpointStore()
        self.ledger_store = InMemoryLedgerStore()
        self.events = InMemoryTraceEventSource()
        self.aggregates: Any = store or InMemoryAggregateStore()
        self.projection = AggregateProjection(
            store=self.aggregates,
            ledger=StoreLedgerSource(self.ledger_store),
            events=self.events,
            prices=PRICES,
            clock=lambda: self.now,
        )
        self.reader = OutboxReader(self.outbox, self.checkpoints, batch_size=3)

    async def add_entry(self, entry: LedgerEntry) -> None:
        current = await self.ledger_store.read_entry(entry.customer_id, entry.id)
        written = await self.ledger_store.write_entry(
            entry, None if current is None else current.version
        )
        assert written
        await self.outbox.append(entry_pointer(entry))

    async def add_allocation(self, record: AllocationRecord) -> None:
        await self.ledger_store.put_allocation(record)
        await self.outbox.append(allocation_pointer(record))

    async def add_event(self, loaded: LoadedEvent) -> None:
        self.events.add(loaded)
        await self.outbox.append(event_pointer(loaded))

    async def drain(self) -> Any:
        return await self.reader.drain(SINK_AGGREGATES, CUST, self.projection)

    async def replay_all(self) -> Any:
        """Redeliver the whole outbox from the start (a rewound checkpoint)."""
        self.checkpoints = InMemoryCheckpointStore()
        self.reader = OutboxReader(self.outbox, self.checkpoints, batch_size=3)
        return await self.drain()

    def snapshot(self) -> dict[str, Any]:
        """In-memory store only: every stored document, byte-for-byte comparable."""
        docs = self.aggregates.documents(CUST)
        return {
            "docs": {k: v.model_dump(mode="json") for k, v in docs.items()},
            "contributions": {
                k: v.model_dump(mode="json") for k, v in self.aggregates.contributions(CUST).items()
            },
            "status": (
                self.aggregates._status[CUST].model_dump(mode="json")
                if CUST in self.aggregates._status
                else None
            ),
        }

    async def read_everything(self) -> dict[str, Any]:
        """Reads through the public reader API only (works for any store implementation)."""
        out: dict[str, Any] = {}
        for domain in (DOMAIN,):
            for metric in ("cost", "latency", "errors", "coverage", "reconciliation"):
                for grain in ("day", "hour"):
                    result = await self.aggregates.query(
                        CUST,
                        domain,
                        metric,
                        grain,
                        wide_window(self, 13 if grain == "hour" else 90),
                        max_series=50,
                        max_points=2160,
                    )
                    out[f"{domain}/{metric}/{grain}"] = result.model_dump(mode="json")
        status = await self.aggregates.status(CUST)
        out["status"] = None if status is None else status.model_dump(mode="json")
        return out


def series(result: Any, key: str) -> Any:
    for item in result.series:
        if item.key == key:
            return item
    raise AssertionError(f"no series {key}: {[s.key for s in result.series]}")


def keys(result: Any) -> list[str]:
    return [s.key for s in result.series]


def wide_window(rig: Rig, days: int = 90) -> AggregateWindow:
    return AggregateWindow(rig.now - timedelta(days=days), rig.now + timedelta(days=1))
