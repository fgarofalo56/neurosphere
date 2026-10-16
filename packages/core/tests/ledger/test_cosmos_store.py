"""CosmosLedgerStore against a fake container (emulator tests: PRP-07 item 6)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from azure.cosmos.exceptions import (
    CosmosAccessConditionFailedError,
    CosmosResourceExistsError,
    CosmosResourceNotFoundError,
)
from neurosphere_core.ledger import CostLedger, LedgerStore, StoreLedgerReader, TimeWindow
from neurosphere_core.ledger.cosmos import CosmosLedgerStore

from .builders import CATEGORY, CUSTOMER, T0, WINDOW, D, application, billing, gateway


class FakeContainer:
    def __init__(self) -> None:
        self.items: dict[tuple[str, str], dict[str, Any]] = {}
        self.etag = 0
        self.queries: list[tuple[str, dict[str, Any]]] = []

    def _stamp(self, body: dict[str, Any]) -> dict[str, Any]:
        self.etag += 1
        return {**body, "_etag": str(self.etag), "_ts": 1, "_rid": "x"}

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
        if slot not in self.items:
            raise CosmosResourceNotFoundError(status_code=404, message="nf")
        if kw["etag"] != self.items[slot]["_etag"]:
            raise CosmosAccessConditionFailedError(status_code=412, message="etag")
        self.items[slot] = self._stamp(body)
        return self.items[slot]

    async def query_items(
        self, query: str, parameters: list[dict[str, Any]], partition_key: str
    ) -> AsyncIterator[dict[str, Any]]:
        params = {p["name"]: p["value"] for p in parameters}
        self.queries.append((query, params))
        for (cust, _), doc in list(self.items.items()):
            if cust != partition_key or doc["customer_id"] != params["@customer"]:
                continue
            if "doc_type = 'entry'" in query:
                if doc["doc_type"] != "entry":
                    continue
                if not params["@start"] <= doc["occurred_at"] < params["@end"]:
                    continue
            elif doc["doc_type"] != "allocation":
                continue
            yield dict(doc)


def test_satisfies_protocol() -> None:
    assert isinstance(CosmosLedgerStore(FakeContainer()), LedgerStore)


async def test_ledger_over_cosmos_store_round_trips_and_is_idempotent() -> None:
    container = FakeContainer()
    ledger = CostLedger(CosmosLedgerStore(container))
    for o in (gateway(1), application(2), billing(3)):
        await ledger.record(CUSTOMER, "r1", CATEGORY, o)
    snapshot = dict(container.items)

    redo = await ledger.record(CUSTOMER, "r1", CATEGORY, gateway(1))

    assert not redo.changed
    assert container.items == snapshot  # no write, same etag
    assert len(container.items) == 1  # one entry, partition /customer_id
    ((cust, _),) = container.items
    assert cust == CUSTOMER
    totals = await StoreLedgerReader(CosmosLedgerStore(container)).totals(CUSTOMER, WINDOW)
    assert totals["USD"].amount == D("1.20")


async def test_stale_etag_returns_false_and_ledger_retries() -> None:
    container = FakeContainer()
    store = CosmosLedgerStore(container)
    ledger = CostLedger(store)
    await ledger.record(CUSTOMER, "r1", CATEGORY, gateway(1))
    stale = await store.read_entry(CUSTOMER, (await _only_entry(store)).id)
    assert stale is not None
    await ledger.record(CUSTOMER, "r1", CATEGORY, billing(3))  # bumps the etag

    assert await store.write_entry(stale.entry, stale.version) is False
    assert await store.write_entry(stale.entry, None) is False  # exists


async def _only_entry(store: CosmosLedgerStore):  # type: ignore[no-untyped-def]
    (entry,) = await store.list_entries(CUSTOMER, WINDOW)
    return entry


async def test_window_query_is_parameterized_with_fixed_width_utc_strings() -> None:
    container = FakeContainer()
    store = CosmosLedgerStore(container)
    await CostLedger(store).record(CUSTOMER, "r1", CATEGORY, gateway(1))

    assert await store.list_entries(CUSTOMER, TimeWindow(T0, T0)) == []
    _, params = container.queries[-1]
    assert params["@start"] == "2026-10-01T12:00:00.000000Z"
    assert "@start" in container.queries[-1][0]  # never string-built SQL
