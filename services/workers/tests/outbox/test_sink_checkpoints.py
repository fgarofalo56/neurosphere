"""Per-sink checkpoints: independent progress, isolated failures, restart without duplicates."""

from __future__ import annotations

from neurosphere_workers.projections.outbox import (
    SINK_AGGREGATES,
    SINK_CATALOG,
    InMemoryCheckpointStore,
    InMemoryOutboxStore,
    OutboxEntry,
    OutboxReader,
)

CUST = "cust-1"


def _entry(n: int, customer: str = CUST) -> OutboxEntry:
    doc_id = f"{n:064x}"
    return OutboxEntry(id=doc_id, customer_id=customer, kind="event", ref_id=doc_id, entity="event")


class Sink:
    """A test sink: records effects keyed by entry id (so duplicates are visible as calls)."""

    def __init__(self, fail_on: int | None = None) -> None:
        self.calls: list[str] = []
        self.effects: set[str] = set()
        self.fail_on = fail_on

    async def __call__(self, entry: OutboxEntry) -> None:
        self.calls.append(entry.id)
        if self.fail_on is not None and entry.id == f"{self.fail_on:064x}":
            raise RuntimeError("sink down")
        self.effects.add(entry.id)


async def _filled(count: int) -> tuple[InMemoryOutboxStore, InMemoryCheckpointStore, OutboxReader]:
    store, checkpoints = InMemoryOutboxStore(), InMemoryCheckpointStore()
    for n in range(1, count + 1):
        await store.append(_entry(n))
    return store, checkpoints, OutboxReader(store, checkpoints, batch_size=2)


async def test_sinks_advance_independently() -> None:
    _, checkpoints, reader = await _filled(5)
    catalog, aggregates = Sink(), Sink(fail_on=3)

    results = await reader.drain_all(CUST, {SINK_CATALOG: catalog, SINK_AGGREGATES: aggregates})

    assert results[SINK_CATALOG].ok and results[SINK_CATALOG].delivered == 5
    assert not results[SINK_AGGREGATES].ok
    assert results[SINK_AGGREGATES].delivered == 2  # stopped at the failing entry, in order
    assert results[SINK_AGGREGATES].error == "RuntimeError"
    # The failure rolled nothing back: catalog is at the end, aggregates after entry 2.
    assert (await checkpoints.get(SINK_CATALOG, CUST)).entry_id == f"{5:064x}"  # type: ignore[union-attr]
    assert (await checkpoints.get(SINK_AGGREGATES, CUST)).entry_id == f"{2:064x}"  # type: ignore[union-attr]


async def test_restart_replays_from_the_sink_checkpoint_without_duplicate_effect() -> None:
    store, checkpoints, reader = await _filled(5)
    sink = Sink(fail_on=3)
    await reader.drain(SINK_AGGREGATES, CUST, sink)
    assert sink.calls == [f"{n:064x}" for n in (1, 2, 3)]

    # "Restart": a brand new reader over the same stores, sink recovered.
    sink.fail_on = None
    restarted = OutboxReader(store, checkpoints, batch_size=2)
    result = await restarted.drain(SINK_AGGREGATES, CUST, sink)

    assert result.ok and result.delivered == 3  # 3, 4, 5
    assert sink.calls == [f"{n:064x}" for n in (1, 2, 3, 3, 4, 5)]  # only the failed entry repeats
    assert sink.effects == {f"{n:064x}" for n in range(1, 6)}  # one effect each

    again = await restarted.drain(SINK_AGGREGATES, CUST, sink)
    assert again.delivered == 0 and len(sink.calls) == 6  # nothing replayed once caught up


async def test_new_entries_after_a_drain_are_picked_up_once() -> None:
    store, _checkpoints, reader = await _filled(2)
    sink = Sink()
    await reader.drain(SINK_CATALOG, CUST, sink)
    await store.append(_entry(3))

    result = await reader.drain(SINK_CATALOG, CUST, sink)

    assert result.delivered == 1 and sink.calls == [f"{n:064x}" for n in (1, 2, 3)]


async def test_a_second_sink_starts_from_the_beginning_regardless_of_the_first() -> None:
    _, _, reader = await _filled(3)
    first, second = Sink(), Sink()
    await reader.drain(SINK_CATALOG, CUST, first)

    await reader.drain(SINK_AGGREGATES, CUST, second)

    assert len(first.calls) == 3 and len(second.calls) == 3


async def test_checkpoints_are_per_customer() -> None:
    store, checkpoints = InMemoryOutboxStore(), InMemoryCheckpointStore()
    await store.append(_entry(1, "cust-a"))
    await store.append(_entry(2, "cust-b"))
    reader = OutboxReader(store, checkpoints)
    sink = Sink()

    await reader.drain(SINK_CATALOG, "cust-a", sink)

    assert sink.calls == [f"{1:064x}"]
    assert await checkpoints.get(SINK_CATALOG, "cust-b") is None


async def test_checkpoint_store_failure_is_a_sink_failure_not_a_crash_of_others() -> None:
    _store, checkpoints, reader = await _filled(2)
    real_advance = checkpoints.advance

    async def flaky(sink: str, customer_id: str, cursor):  # type: ignore[no-untyped-def]
        if sink == SINK_CATALOG:
            raise RuntimeError("checkpoint store down")
        await real_advance(sink, customer_id, cursor)

    checkpoints.advance = flaky  # type: ignore[method-assign]
    catalog, aggregates = Sink(), Sink()

    results = await reader.drain_all(CUST, {SINK_CATALOG: catalog, SINK_AGGREGATES: aggregates})

    assert not results[SINK_CATALOG].ok and results[SINK_AGGREGATES].ok
    assert await checkpoints.get(SINK_CATALOG, CUST) is None  # will replay; effects idempotent
