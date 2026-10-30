"""Durable append-only apply-record store (PRP-34 item 2): in-memory and Cosmos (fake container).

The record model here mirrors the connector's ``ApplyRecord`` facets; core never imports the
connector, which is exactly why the store is generic over the model.
"""

from __future__ import annotations

import copy
from collections.abc import AsyncIterator, Mapping
from typing import Any

import pytest
from azure.cosmos.exceptions import (
    CosmosAccessConditionFailedError,
    CosmosHttpResponseError,
    CosmosResourceExistsError,
    CosmosResourceNotFoundError,
)
from neurosphere_core.errors import (
    DependencyTransientError,
    InvalidSchemaError,
    RateLimitedError,
    StaleVersionError,
)
from neurosphere_core.gateway import CosmosGatewayRecordStore, InMemoryGatewayRecordStore
from neurosphere_core.gateway.records import (
    APPLY_RECORD_IMMUTABLE,
    HEAD_DOC_TYPE,
    RECORD_DOC_TYPE,
)
from pydantic import BaseModel, ConfigDict

CUSTOMER = "contoso"
DOMAIN = "commercial:contoso:catalog:domain:finance"
GW = "gw-" + "a" * 32
OTHER_GW = "gw-" + "b" * 32
DIGEST = "1" * 64


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    gateway_id: str = GW
    target: str = "commercial:contoso:apim:apim_gateway:" + GW
    plan_digest: str = DIGEST
    status: str = "applying"
    steps: tuple[str, ...] = ()


class FakeContainer:
    """Just enough of ``ContainerProxy`` for the record store: ids, etags, partitions."""

    def __init__(self) -> None:
        self.docs: dict[tuple[str, str, str], dict[str, Any]] = {}
        self.counter = 0
        self.fail_head_move_once = False
        self.error: Exception | None = None

    def _key(self, body: Mapping[str, Any]) -> tuple[str, str, str]:
        return (str(body["customer_id"]), str(body["domain_id"]), str(body["id"]))

    def _stamp(self, body: Mapping[str, Any]) -> dict[str, Any]:
        self.counter += 1
        return {**copy.deepcopy(dict(body)), "_etag": f'"{self.counter}"'}

    def _raise(self) -> None:
        if self.error is not None:
            raise self.error

    async def create_item(self, body: dict[str, Any]) -> dict[str, Any]:
        self._raise()
        key = self._key(body)
        if key in self.docs:
            raise CosmosResourceExistsError(message="exists")
        if self.fail_head_move_once and body.get("doc_type") == HEAD_DOC_TYPE:
            self.fail_head_move_once = False
            raise CosmosHttpResponseError(status_code=503, message="lost")
        self.docs[key] = self._stamp(body)
        return self.docs[key]

    async def read_item(self, item: str, partition_key: list[str]) -> dict[str, Any]:
        self._raise()
        found = self.docs.get((partition_key[0], partition_key[1], item))
        if found is None:
            raise CosmosResourceNotFoundError(message="missing")
        return copy.deepcopy(found)

    async def replace_item(
        self, item: str, body: dict[str, Any], etag: str, match_condition: object
    ) -> dict[str, Any]:
        self._raise()
        key = self._key(body)
        current = self.docs.get(key)
        if current is None or current["_etag"] != etag:
            raise CosmosAccessConditionFailedError(message="precondition")
        if self.fail_head_move_once and body.get("doc_type") == HEAD_DOC_TYPE:
            self.fail_head_move_once = False
            raise CosmosHttpResponseError(status_code=503, message="lost")
        self.docs[key] = self._stamp(body)
        return self.docs[key]

    async def query_items(
        self, sql: str, parameters: list[dict[str, Any]], partition_key: list[str]
    ) -> AsyncIterator[dict[str, Any]]:
        self._raise()
        params = {p["name"]: p["value"] for p in parameters}
        rows = [
            copy.deepcopy(doc)
            for (customer, domain, _), doc in self.docs.items()
            if [customer, domain] == partition_key and doc["doc_type"] == params["@doc_type"]
        ]
        if "@record" in params:
            rows = sorted(
                (r for r in rows if r["record_id"] == params["@record"]),
                key=lambda r: r["version"],
            )
        if "@gateway" in params:
            rows = [
                r
                for r in rows
                if r["gateway_id"] == params["@gateway"] and r["status"] == params["@status"]
            ][:1]
        for row in rows:
            yield row


def _cosmos() -> tuple[CosmosGatewayRecordStore[Record], FakeContainer]:
    container = FakeContainer()
    store = CosmosGatewayRecordStore(
        container,  # type: ignore[arg-type]
        customer_id=CUSTOMER,
        domain_id=DOMAIN,
        model=Record,
    )
    return store, container


def _memory() -> InMemoryGatewayRecordStore[Record]:
    return InMemoryGatewayRecordStore(Record)


Store = InMemoryGatewayRecordStore[Record] | CosmosGatewayRecordStore[Record]


@pytest.fixture(params=["memory", "cosmos"])
def store(request: pytest.FixtureRequest) -> Store:
    """A fresh store per test (both implementations obey the same rules)."""
    return _memory() if request.param == "memory" else _cosmos()[0]


async def test_append_only_versions_latest_and_history(store: Store) -> None:
    assert await store.latest("apply-1") is None
    await store.append(Record(id="apply-1"))
    await store.append(Record(id="apply-1", steps=("backends/foundry",)))
    await store.append(Record(id="apply-1", steps=("backends/foundry",), status="succeeded"))
    latest = await store.latest("apply-1")
    assert latest is not None and latest.status == "succeeded"
    history = await store.history("apply-1")
    assert [r.status for r in history] == ["applying", "applying", "succeeded"]
    assert history[0].steps == ()


async def test_running_tracks_the_newest_status_per_gateway(store: Store) -> None:
    assert not await store.running(GW)
    await store.append(Record(id="apply-1"))
    assert await store.running(GW)
    assert not await store.running(OTHER_GW)
    await store.append(Record(id="apply-1", status="succeeded"))
    assert not await store.running(GW)
    await store.append(Record(id="apply-2"))
    await store.append(Record(id="apply-2", status="rolled_back"))
    assert not await store.running(GW)


@pytest.mark.parametrize(
    "change",
    [{"plan_digest": "2" * 64}, {"gateway_id": OTHER_GW}, {"target": "commercial:x:apim:y:z"}],
)
async def test_reviewed_plan_is_immutable(store: Store, change: dict[str, str]) -> None:
    await store.append(Record(id="apply-1"))
    with pytest.raises(StaleVersionError) as info:
        await store.append(Record.model_validate({"id": "apply-1", **change}))
    assert info.value.reason == APPLY_RECORD_IMMUTABLE
    assert len(await store.history("apply-1")) == 1


@pytest.mark.parametrize("terminal", ["rolled_back", "rollback_failed"])
async def test_nothing_is_appended_after_a_terminal_status(store: Store, terminal: str) -> None:
    await store.append(Record(id="apply-1"))
    await store.append(Record(id="apply-1", status=terminal))
    with pytest.raises(StaleVersionError) as info:
        await store.append(Record(id="apply-1", status="succeeded"))
    assert info.value.reason == APPLY_RECORD_IMMUTABLE


async def test_a_record_without_its_facets_is_refused(store: Store) -> None:
    with pytest.raises(InvalidSchemaError):
        await store.append(Record(id="apply-1", gateway_id=""))


async def test_cosmos_documents_are_versions_plus_one_head() -> None:
    store, container = _cosmos()
    await store.append(Record(id="apply-1"))
    await store.append(Record(id="apply-1", status="succeeded"))
    docs = {doc["id"]: doc for doc in container.docs.values()}
    assert set(docs) == {"rec-apply-1-v000001", "rec-apply-1-v000002", "rechead-apply-1"}
    assert docs["rec-apply-1-v000001"]["doc_type"] == RECORD_DOC_TYPE
    assert docs["rec-apply-1-v000001"]["record"]["status"] == "applying"  # never rewritten
    head = docs["rechead-apply-1"]
    assert head["doc_type"] == HEAD_DOC_TYPE
    assert (head["version"], head["status"]) == (2, "succeeded")
    assert all(d["customer_id"] == CUSTOMER and d["domain_id"] == DOMAIN for d in docs.values())


async def test_cosmos_append_repairs_a_lost_head_move() -> None:
    store, container = _cosmos()
    await store.append(Record(id="apply-1"))
    container.fail_head_move_once = True
    with pytest.raises(DependencyTransientError):
        await store.append(Record(id="apply-1", steps=("a",)))
    # The version landed, the head did not: latest still shows v1 ...
    latest = await store.latest("apply-1")
    assert latest is not None and latest.steps == ()
    # ... and the next append adopts the orphan before writing v3.
    await store.append(Record(id="apply-1", steps=("a", "b"), status="succeeded"))
    history = await store.history("apply-1")
    assert [r.steps for r in history] == [(), ("a",), ("a", "b")]
    latest = await store.latest("apply-1")
    assert latest is not None and latest.status == "succeeded"


async def test_cosmos_outages_map_to_the_taxonomy() -> None:
    store, container = _cosmos()
    container.error = CosmosHttpResponseError(status_code=429, message="throttled")
    with pytest.raises(RateLimitedError):
        await store.append(Record(id="apply-1"))
    container.error = CosmosHttpResponseError(status_code=503, message="down")
    with pytest.raises(DependencyTransientError):
        await store.running(GW)
    with pytest.raises(DependencyTransientError):
        await store.latest("apply-1")


async def test_cosmos_concurrent_head_move_is_a_conflict() -> None:
    store, container = _cosmos()
    await store.append(Record(id="apply-1"))
    head_key = (CUSTOMER, DOMAIN, "rechead-apply-1")
    original = container.replace_item

    async def racing(
        item: str, body: dict[str, Any], etag: str, match_condition: object
    ) -> dict[str, Any]:
        container.docs[head_key]["_etag"] = '"raced"'
        return await original(item, body, etag, match_condition)

    container.replace_item = racing  # type: ignore[method-assign]
    with pytest.raises(StaleVersionError) as info:
        await store.append(Record(id="apply-1", status="succeeded"))
    assert info.value.reason == "apply_record_conflict"


async def test_memory_store_fails_closed_on_outage() -> None:
    store = _memory()
    store.fail_with(DependencyTransientError("down", reason="gateway_store_unavailable"))
    with pytest.raises(DependencyTransientError):
        await store.running(GW)
