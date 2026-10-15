"""Cosmos-backed marker and watermark stores against a fake container (emulator tests: item 6)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from azure.cosmos.exceptions import (
    CosmosAccessConditionFailedError,
    CosmosResourceExistsError,
    CosmosResourceNotFoundError,
)
from neurosphere_workers.ingestion.cosmos_stores import (
    CosmosAcceptedMarkerStore,
    CosmosWatermarkStore,
)
from neurosphere_workers.ingestion.models import EventKey
from neurosphere_workers.ingestion.protocols import AcceptedMarkerStore, WatermarkStore

from .support import T0


class FakeContainer:
    def __init__(self) -> None:
        self.items: dict[tuple[str, str], dict[str, Any]] = {}
        self.create_calls = 0
        self.fail_next_replace = 0

    async def read_item(self, item: str, partition_key: str) -> dict[str, Any]:
        found = self.items.get((partition_key, item))
        if found is None:
            raise CosmosResourceNotFoundError(status_code=404, message="not found")
        return dict(found)

    async def create_item(self, body: dict[str, Any]) -> dict[str, Any]:
        self.create_calls += 1
        slot = (body["customer_id"], body["id"])
        if slot in self.items:
            raise CosmosResourceExistsError(status_code=409, message="conflict")
        self.items[slot] = {**body, "_etag": "1"}
        return body

    async def replace_item(self, item: str, body: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        slot = (body["customer_id"], item)
        if self.fail_next_replace > 0:
            self.fail_next_replace -= 1
            raise CosmosAccessConditionFailedError(status_code=412, message="etag")
        assert kwargs["etag"] == self.items[slot]["_etag"]
        self.items[slot] = {**body, "_etag": str(int(self.items[slot]["_etag"]) + 1)}
        return body


KEY = EventKey("cust", "src", "evt-1")


def test_satisfy_protocols() -> None:
    assert isinstance(CosmosAcceptedMarkerStore(FakeContainer()), AcceptedMarkerStore)
    assert isinstance(CosmosWatermarkStore(FakeContainer()), WatermarkStore)


async def test_marker_create_then_conflict_means_already_accepted() -> None:
    container = FakeContainer()
    store = CosmosAcceptedMarkerStore(container)

    assert not await store.is_accepted(KEY)
    assert await store.mark_accepted(KEY) is True
    assert await store.mark_accepted(KEY) is False  # conflict, not an error
    assert await store.is_accepted(KEY)
    assert list(container.items) == [("cust", KEY.doc_id)]  # deterministic id, /customer_id


async def test_marker_is_scoped_to_customer() -> None:
    store = CosmosAcceptedMarkerStore(FakeContainer())
    await store.mark_accepted(KEY)

    assert not await store.is_accepted(EventKey("other", "src", "evt-1"))


async def test_watermark_get_advance_and_never_moves_back() -> None:
    store = CosmosWatermarkStore(FakeContainer())

    assert await store.get("cust", "src") is None
    assert await store.advance("cust", "src", T0) == T0
    assert await store.advance("cust", "src", T0 + timedelta(minutes=5)) == T0 + timedelta(
        minutes=5
    )
    assert await store.advance("cust", "src", T0) == T0 + timedelta(minutes=5)
    assert await store.get("cust", "src") == T0 + timedelta(minutes=5)


async def test_watermark_retries_on_etag_conflict() -> None:
    container = FakeContainer()
    store = CosmosWatermarkStore(container)
    await store.advance("cust", "src", T0)
    container.fail_next_replace = 2

    assert await store.advance("cust", "src", T0 + timedelta(minutes=1)) == T0 + timedelta(
        minutes=1
    )


async def test_watermark_source_ids_with_unsafe_characters_are_hashed() -> None:
    container = FakeContainer()
    store = CosmosWatermarkStore(container)

    await store.advance("cust", "a/b?c#d", T0)

    ((_, doc_id),) = container.items
    assert not set(doc_id) & set("/\\?#")
    assert await store.get("cust", "a/b?c#d") == T0


async def test_watermark_gives_up_under_permanent_contention() -> None:
    from neurosphere_core.errors import DependencyTransientError

    container = FakeContainer()
    store = CosmosWatermarkStore(container)
    await store.advance("cust", "src", T0)
    container.fail_next_replace = 99

    with pytest.raises(DependencyTransientError):
        await store.advance("cust", "src", T0 + timedelta(minutes=1))
