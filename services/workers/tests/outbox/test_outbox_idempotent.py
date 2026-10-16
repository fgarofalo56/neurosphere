"""Outbox ids are deterministic, so retries never duplicate; Cosmos stores via a fake container."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from azure.cosmos.exceptions import (
    CosmosAccessConditionFailedError,
    CosmosResourceExistsError,
    CosmosResourceNotFoundError,
)
from neurosphere_core.ledger import LedgerEntry, fold_entry
from neurosphere_workers.projections.outbox import (
    CheckpointStore,
    CosmosCheckpointStore,
    CosmosOutboxStore,
    Cursor,
    InMemoryOutboxStore,
    OutboxEntry,
    OutboxStore,
    OutboxWriter,
    event_outbox_id,
    ledger_change_outbox_id,
)

from .support import Rig, model_call, raw_message, settings

CUST = "cust-1"


def _event(n: int, customer: str = CUST) -> OutboxEntry:
    doc_id = f"{n:064x}"
    return OutboxEntry(
        id=event_outbox_id(doc_id),
        customer_id=customer,
        kind="event",
        ref_id=doc_id,
        entity="event",
    )


def _entry_state(amount: str) -> LedgerEntry:
    from decimal import Decimal

    from neurosphere_core.ledger import Observation

    obs = Observation(
        observation_kind="gateway",
        doc_id="a" * 64,
        kind="estimated",
        amount=Decimal(amount),
        currency="USD",
        price_version_id="pv-1",
        observed_at=datetime(2026, 10, 1, tzinfo=UTC),
        cloud="commercial",
        source_id="s",
    )
    return fold_entry(CUST, "req-1", "model_inference", [obs])


async def test_append_is_idempotent_by_id() -> None:
    store = InMemoryOutboxStore()
    first = await store.append(_event(1))
    second = await store.append(_event(1))
    assert first is True
    assert second is False
    assert len(store.entries(CUST)) == 1


async def test_ledger_change_id_is_hash_of_entry_and_content() -> None:
    store = InMemoryOutboxStore()
    writer = OutboxWriter(store)
    one, same, other = _entry_state("1.00"), _entry_state("1.00"), _entry_state("2.00")

    assert await writer.write_ledger_change(one) is True
    assert await writer.write_ledger_change(same) is False  # retry: same content, same id
    assert await writer.write_ledger_change(other) is True  # changed content: new entry
    ids = [e.id for e in store.entries(CUST)]
    assert ids == [
        ledger_change_outbox_id(one.id, one.content_hash),
        ledger_change_outbox_id(other.id, other.content_hash),
    ]
    assert one.id == other.id and one.content_hash != other.content_hash


async def test_sink_repeat_writes_no_extra_outbox_entries() -> None:
    rig = Rig()
    harness = rig.harness()
    doc = model_call("evt-1")
    msg = raw_message(doc, 0, kind="telemetry", observation_kind="gateway")
    from neurosphere_workers.ingestion.pipeline import process_batch

    await process_batch([msg], harness.deps(), settings())
    harness.markers.marked.clear()  # force the sink to run again
    await process_batch([msg], harness.deps(), settings())

    assert len(rig.outbox_store.entries(doc["customer_id"])) == 2
    assert rig.outbox_store.append_calls == 4  # called twice per run, effect once


# ---- Cosmos stores against a fake container -------------------------------------------------


class FakeOutboxContainer:
    def __init__(self) -> None:
        self.items: dict[tuple[str, str], dict[str, Any]] = {}
        self.clock = 0
        self.etag = 0

    def _stamp(self, body: dict[str, Any], ts: int | None = None) -> dict[str, Any]:
        self.etag += 1
        return {**body, "_etag": str(self.etag), "_ts": ts if ts is not None else self.clock}

    async def read_item(self, item: str, partition_key: str) -> dict[str, Any]:
        found = self.items.get((partition_key, item))
        if found is None:
            raise CosmosResourceNotFoundError(status_code=404, message="nf")
        return dict(found)

    async def create_item(self, body: dict[str, Any]) -> dict[str, Any]:
        slot = (body["customer_id"], body["id"])
        if slot in self.items:
            raise CosmosResourceExistsError(status_code=409, message="conflict")
        self.items[slot] = self._stamp(body)
        return self.items[slot]

    async def replace_item(self, item: str, body: dict[str, Any], **kw: Any) -> dict[str, Any]:
        slot = (body["customer_id"], item)
        if kw["etag"] != self.items[slot]["_etag"]:
            raise CosmosAccessConditionFailedError(status_code=412, message="etag")
        self.items[slot] = self._stamp(body)
        return self.items[slot]

    async def query_items(
        self, query: str, parameters: list[dict[str, Any]], partition_key: str
    ) -> AsyncIterator[dict[str, Any]]:
        p = {x["name"]: x["value"] for x in parameters}
        assert "ORDER BY c._ts" in query and "c.id" not in query.split("ORDER BY")[1]
        rows = [
            d
            for (cust, _), d in self.items.items()
            if cust == p["@customer"] and p["@ts"] <= d["_ts"] <= p["@max"]
        ]
        rows.sort(key=lambda d: d["_ts"])  # ties come back in arbitrary (insertion) order
        for row in rows:
            yield dict(row)


def test_cosmos_stores_satisfy_protocols() -> None:
    assert isinstance(CosmosOutboxStore(FakeOutboxContainer()), OutboxStore)
    assert isinstance(CosmosCheckpointStore(FakeOutboxContainer()), CheckpointStore)


async def test_cosmos_outbox_append_idempotent_and_ordered_by_ts_then_id() -> None:
    container = FakeOutboxContainer()
    now = datetime(2026, 10, 1, 12, 0, 0, tzinfo=UTC)
    store = CosmosOutboxStore(container, settle_seconds=5, clock=lambda: now)
    stamp = int(now.timestamp()) - 60

    container.clock = stamp
    # Ids inserted out of id order within one _ts: the client-side tie-break must sort them.
    for n in (3, 1, 2):
        appended = await store.append(_event(n))
        assert appended is True
    duplicate = await store.append(_event(1))
    assert duplicate is False
    container.clock = stamp + 1
    await store.append(_event(4))

    got = await store.read_after(CUST, None, 100)
    assert [s.entry.ref_id for s in got] == [f"{n:064x}" for n in (1, 2, 3, 4)]
    assert [s.ts for s in got] == [stamp] * 3 + [stamp + 1]
    assert all("_ts" not in s.entry.model_dump() for s in got)

    after_second = await store.read_after(CUST, Cursor(stamp, f"{2:064x}"), 100)
    assert [s.entry.ref_id for s in after_second] == [f"{n:064x}" for n in (3, 4)]


async def test_cosmos_outbox_limit_never_splits_a_ts_group_wrongly() -> None:
    container = FakeOutboxContainer()
    now = datetime(2026, 10, 1, 12, 0, 0, tzinfo=UTC)
    store = CosmosOutboxStore(container, clock=lambda: now)
    stamp = int(now.timestamp()) - 60
    container.clock = stamp
    for n in (3, 1, 2):
        await store.append(_event(n))

    first = await store.read_after(CUST, None, 1)
    assert [s.entry.ref_id for s in first] == [f"{1:064x}"]  # smallest id, not insertion order
    rest = await store.read_after(CUST, first[0].cursor, 1)
    assert [s.entry.ref_id for s in rest] == [f"{2:064x}"]


async def test_cosmos_outbox_hides_entries_inside_the_settle_window() -> None:
    container = FakeOutboxContainer()
    now = datetime(2026, 10, 1, 12, 0, 0, tzinfo=UTC)
    store = CosmosOutboxStore(container, settle_seconds=5, clock=lambda: now)
    container.clock = int(now.timestamp()) - 2  # younger than the settle window
    await store.append(_event(1))

    assert await store.read_after(CUST, None, 10) == []


async def test_cosmos_checkpoint_is_monotonic_and_per_sink() -> None:
    container = FakeOutboxContainer()
    store = CosmosCheckpointStore(container)

    assert await store.get("catalog", CUST) is None
    await store.advance("catalog", CUST, Cursor(10, "b"))
    await store.advance("catalog", CUST, Cursor(5, "z"))  # older: ignored
    await store.advance("aggregates", CUST, Cursor(3, "a"))

    assert await store.get("catalog", CUST) == Cursor(10, "b")
    assert await store.get("aggregates", CUST) == Cursor(3, "a")
    assert await store.get("catalog", "other-customer") is None
