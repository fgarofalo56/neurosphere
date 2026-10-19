"""Replaying the same outbox batch yields identical aggregates.

The unmarked tests run over the in-memory stores (and are what CI executes). The ``integration``
test runs the same scenario against the compose Cosmos emulator and compares it with the
in-memory result. Emulator limits (G12): no RU accounting, no range/composite indexes; this
proves document shape and idempotency only.
"""

from __future__ import annotations

import base64
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from azure.cosmos import PartitionKey
from neurosphere_core.aggregates import AggregateStore
from neurosphere_core.aggregates.cosmos import PARTITION_KEY_PATH, CosmosAggregateStore
from neurosphere_core.clients import ClientLifetime, create_cosmos_client
from neurosphere_core.cloud import Settings
from neurosphere_core.errors import DependencyTransientError

from .support import (
    CUST,
    Rig,
    days_ago,
    event_doc,
    ledger_entry,
    observation,
    vendor_allocation,
)


async def populate(rig: Rig) -> None:
    """Null-heavy, multi-source, multi-day scenario with two outbox entries for one request."""
    first = ledger_entry("req-1", observation("gateway", 1, "2.00", at=days_ago(2, hour=9)))
    await rig.add_entry(first)
    # The same request later gains billing + app observations: a NEW outbox entry for it.
    await rig.add_entry(
        ledger_entry(
            "req-1",
            observation("gateway", 1, "2.00", at=days_ago(2, hour=9)),
            observation("application", 2, "2.20", at=days_ago(2, hour=10)),
            observation("billing", 3, "2.10", at=days_ago(1, hour=8)),
        )
    )
    await rig.add_entry(ledger_entry("req-2", observation("gateway", 4, None, at=days_ago(3))))
    await rig.add_entry(
        ledger_entry("req-3", observation("gateway", 5, "5.00", at=days_ago(1), currency="EUR"))
    )
    await rig.add_allocation(vendor_allocation(6, "40.00", at=days_ago(1)))
    for i, (ms, outcome) in enumerate([(120, "success"), (None, "unknown"), (900, "error")]):
        await rig.add_event(
            event_doc(f"e{i}", at=days_ago(1, hour=11), duration_ms=ms, outcome=outcome)
        )


async def test_replaying_the_same_batch_twice_yields_identical_aggregates() -> None:
    rig = Rig()
    await populate(rig)
    assert (await rig.drain()).ok
    once = rig.snapshot()
    reads = await rig.read_everything()
    assert once["docs"], "scenario produced no aggregates"

    again = await rig.replay_all()  # checkpoint rewound: every entry redelivered
    assert again.ok
    assert again.delivered == 8
    assert rig.snapshot() == once
    assert await rig.read_everything() == reads

    # A third pass, one entry at a time and out of order, still changes nothing.
    entries = rig.outbox.entries(CUST)
    entries = entries[3:] + entries[:3]  # a rotated, out-of-order delivery
    for entry in entries:
        await rig.projection.handle(entry)
        await rig.projection.handle(entry)
    assert rig.snapshot() == once


async def test_delivery_order_does_not_change_the_result() -> None:
    forward, backward = Rig(), Rig()
    await populate(forward)
    await populate(backward)
    assert (await forward.drain()).ok
    for entry in reversed(backward.outbox.entries(CUST)):
        await backward.projection.handle(entry)
    assert backward.snapshot() == forward.snapshot()


async def test_a_failed_write_does_not_advance_the_checkpoint_and_converges_on_retry() -> None:
    clean = Rig()
    await populate(clean)
    assert (await clean.drain()).ok

    flaky = Rig()
    await populate(flaky)
    real = flaky.aggregates.replace_bucket
    failures = {"left": 2}

    async def failing(*args: Any, **kwargs: Any) -> None:
        if failures["left"] > 0:
            failures["left"] -= 1
            raise DependencyTransientError("injected store fault")
        await real(*args, **kwargs)

    flaky.aggregates.replace_bucket = failing  # type: ignore[method-assign]
    first = await flaky.drain()
    assert first.error == "DependencyTransientError"  # stopped; checkpoint stayed put
    second = await flaky.drain()
    assert second.error == "DependencyTransientError"
    assert (await flaky.drain()).ok  # faults exhausted: redelivery converges
    assert flaky.snapshot() == clean.snapshot()


# --------------------------------------------------------------------------- Cosmos emulator


@pytest.fixture
def _emulator_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NS_ENV", "local")
    monkeypatch.setenv("NS_COSMOS_ENDPOINT", "http://localhost:8081")
    monkeypatch.setenv("NS_COSMOS_KEY", base64.b64encode(b"emulator-ignores-this").decode())


@pytest_asyncio.fixture
async def cosmos_store(_emulator_env: None) -> AsyncIterator[AggregateStore]:
    async with ClientLifetime() as lifetime:
        client = create_cosmos_client(Settings(env="local"), lifetime=lifetime)
        database = await client.create_database_if_not_exists("ns_aggregates_it")
        name = f"agg_{uuid.uuid4().hex[:10]}"
        container = await database.create_container_if_not_exists(
            id=name, partition_key=PartitionKey(path=PARTITION_KEY_PATH)
        )
        try:
            yield CosmosAggregateStore(container)
        finally:
            await database.delete_container(name)


@pytest.mark.integration
async def test_cosmos_replay_is_idempotent_and_matches_in_memory(
    cosmos_store: AggregateStore,
) -> None:
    memory = Rig()
    await populate(memory)
    assert (await memory.drain()).ok
    expected = await memory.read_everything()

    cosmos = Rig(store=cosmos_store)
    await populate(cosmos)
    assert (await cosmos.drain()).ok
    first = await cosmos.read_everything()
    assert first == expected  # same documents through the Cosmos implementation

    assert (await cosmos.replay_all()).ok  # replay the whole outbox
    assert await cosmos.read_everything() == first
    # Prune is a no-op for in-window data and idempotent.
    assert await cosmos.projection.prune(CUST) == 0
    assert await cosmos.read_everything() == first
