"""PriceSnapshotStore conformance: in-memory and CosmosPriceSnapshotStore on a fake container."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any

import pytest
from azure.cosmos.exceptions import CosmosHttpResponseError
from neurosphere_core.errors import DependencyTransientError, RateLimitedError
from neurosphere_core.pricing import InMemoryPriceSnapshotStore, PriceSnapshotStore, cosmos_store
from neurosphere_core.pricing.cosmos_store import (
    DEFAULT_PRICE_SNAPSHOT_CONTAINER,
    PRICE_SNAPSHOT_PARTITION_KEY_PATH,
    CosmosPriceSnapshotStore,
)

from .conformance import CHECKS, MODEL, retail_fixture, sheet
from .cosmos_fake import new_container

BACKENDS: dict[str, Callable[[], PriceSnapshotStore]] = {
    "memory": InMemoryPriceSnapshotStore,
    "cosmos-fake": lambda: CosmosPriceSnapshotStore(new_container()),  # type: ignore[arg-type]
}


@pytest.mark.parametrize("backend", sorted(BACKENDS))
@pytest.mark.parametrize("check", sorted(CHECKS))
def test_conformance(backend: str, check: str) -> None:
    CHECKS[check](BACKENDS[backend]())


def test_container_constants_match_the_wire_contract() -> None:
    assert DEFAULT_PRICE_SNAPSHOT_CONTAINER == "price_snapshots"
    assert PRICE_SNAPSHOT_PARTITION_KEY_PATH == "/snapshot_id"


# -- Cosmos-specific ----------------------------------------------------------------------------


def test_documents_are_partitioned_by_snapshot_id_and_snapshots_are_never_rewritten() -> None:
    container = new_container()
    store = CosmosPriceSnapshotStore(container)  # type: ignore[arg-type]
    retail = retail_fixture()
    store.put(retail)
    store.put(sheet("s-a", date(2026, 10, 1), "1"))
    assert sorted(key for key, _ in container.items) == sorted([(retail.snapshot_id,), ("s-a",)])
    before = {slot: doc["_etag"] for slot, doc in container.items.items()}
    assert store.put(retail) is False
    assert {slot: doc["_etag"] for slot, doc in container.items.items()} == before


def test_listing_is_one_bounded_query_and_get_is_point_reads() -> None:
    container = new_container()
    store = CosmosPriceSnapshotStore(container)  # type: ignore[arg-type]
    store.put(sheet("s-a", date(2026, 10, 1), "1"))
    store.list_snapshots("commercial")
    store.resolve("commercial", date(2026, 10, 19))
    assert len(container.queries) == 2
    for record in container.queries:
        assert "TOP @limit" in record.query
        assert record.params["@limit"] == cosmos_store.MAX_SNAPSHOTS + 1
        assert record.params["@cloud"] == "commercial"
    assert container.queries[1].params["@on"] == "2026-10-19"
    queries_before = len(container.queries)
    store.get("s-a")
    store.put(sheet("s-b", date(2026, 10, 2), "2"))
    assert len(container.queries) == queries_before  # lookups are point reads, never scans


def test_resolution_fails_loudly_past_the_snapshot_bound(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cosmos_store, "MAX_SNAPSHOTS", 2)
    store = CosmosPriceSnapshotStore(new_container())  # type: ignore[arg-type]
    for n in range(3):
        store.put(sheet(f"s-{n}", date(2026, 10, 1 + n), "1"))
    with pytest.raises(DependencyTransientError) as raised:
        store.resolve("commercial", date(2026, 12, 1))
    assert raised.value.reason == "price_set_too_large"
    assert store.get("s-0") is not None  # point reads are unaffected


def test_a_tampered_document_fails_closed_as_upstream_invalid() -> None:
    container = new_container()
    store = CosmosPriceSnapshotStore(container)  # type: ignore[arg-type]
    store.put(sheet("s-a", date(2026, 10, 1), "1"))
    for doc in container.items.values():
        doc["rows"][0]["retail_price"] = "999"  # content_hash no longer matches
    with pytest.raises(DependencyTransientError) as raised:
        store.get("s-a")
    assert raised.value.reason == "price_snapshot_record_invalid"
    assert raised.value.status == 502


class _Failing:
    def __init__(self, status: int | None) -> None:
        self.status = status

    def _fail(self) -> Any:
        if self.status is None:
            raise ConnectionError("secret-host.example")
        raise CosmosHttpResponseError(status_code=self.status, message="boom secret")

    def create_item(self, **_: Any) -> Any:
        self._fail()

    def read_item(self, **_: Any) -> Any:
        self._fail()

    def query_items(self, *_: Any, **__: Any) -> Any:
        self._fail()


@pytest.mark.parametrize(
    ("status", "expected"),
    [(None, DependencyTransientError), (503, DependencyTransientError), (429, RateLimitedError)],
)
def test_outages_map_to_taxonomy_errors_without_echoing_sdk_text(
    status: int | None, expected: type[Exception]
) -> None:
    store = CosmosPriceSnapshotStore(_Failing(status))  # type: ignore[arg-type]
    calls: list[Callable[[], object]] = [
        lambda: store.put(sheet("s-a", date(2026, 10, 1), "1")),
        lambda: store.get("s-a"),
        lambda: store.list_snapshots(),
        lambda: store.resolve("commercial", date(2026, 10, 19)),
        lambda: store.resolve_token_price("commercial", *MODEL, date(2026, 10, 19)),
    ]
    for call in calls:
        with pytest.raises(expected) as raised:
            call()
        assert "secret" not in str(raised.value)
