"""Lifecycle stores: one contract, two backends (in-memory, Cosmos over an in-process fake).

The fake container lives in ``hitl_cosmos`` (shared by the three PRP-29 item 3 suites). The
emulator run is ``tests/integration/stores_hitl`` (marked ``integration``; not run in CI).
"""

from __future__ import annotations

import pytest
from hitl_cosmos.fake_container import (  # pyright: ignore[reportMissingImports]
    FakeContainer,
    throttled,
)
from neurosphere_core.errors import DependencyTransientError, RateLimitedError
from neurosphere_core.lifecycle import HoldRegistry, RequestQueue
from neurosphere_core.lifecycle.cosmos import (
    DEFAULT_HOLD_CONTAINER,
    DEFAULT_MAPPING_CONTAINER,
    DEFAULT_REQUEST_CONTAINER,
    LIFECYCLE_PARTITION_KEY_PATH,
    CosmosHoldRegistry,
    CosmosMappingStore,
    CosmosRequestQueue,
)
from neurosphere_core.lifecycle.memory import (
    InMemoryHoldRegistry,
    InMemoryMappingStore,
    InMemoryRequestQueue,
)

from .contract import (
    CUSTOMER,
    HoldRegistryContract,
    MappingStoreContract,
    RequestQueueContract,
    make_hold,
    make_queued,
)


def fake() -> FakeContainer:
    return FakeContainer((LIFECYCLE_PARTITION_KEY_PATH,))


class MemoryMappings(InMemoryMappingStore):
    async def register(self, subject_id: str) -> None:
        self.subjects.add(subject_id)


@pytest.fixture(params=["memory", "cosmos-fake"])
def mappings(request: pytest.FixtureRequest) -> MemoryMappings | CosmosMappingStore:
    if request.param == "memory":
        return MemoryMappings()
    return CosmosMappingStore(fake(), customer_id=CUSTOMER)  # type: ignore[arg-type]


@pytest.fixture(params=["memory", "cosmos-fake"])
def holds(request: pytest.FixtureRequest) -> HoldRegistry:
    if request.param == "memory":
        return InMemoryHoldRegistry()
    return CosmosHoldRegistry(fake(), customer_id=CUSTOMER)  # type: ignore[arg-type]


@pytest.fixture(params=["memory", "cosmos-fake"])
def queue(request: pytest.FixtureRequest) -> RequestQueue:
    if request.param == "memory":
        return InMemoryRequestQueue()
    return CosmosRequestQueue(fake(), customer_id=CUSTOMER)  # type: ignore[arg-type]


class TestMappingStoreContract(MappingStoreContract):
    pass


class TestHoldRegistryContract(HoldRegistryContract):
    pass


class TestRequestQueueContract(RequestQueueContract):
    pass


# -- Cosmos-specific behaviour ------------------------------------------------------------------


def test_container_constants_match_the_wire_contract() -> None:
    assert DEFAULT_MAPPING_CONTAINER == "lifecycle_mappings"
    assert DEFAULT_HOLD_CONTAINER == "lifecycle_holds"
    assert DEFAULT_REQUEST_CONTAINER == "lifecycle_requests"
    assert LIFECYCLE_PARTITION_KEY_PATH == "/customer_id"


async def test_mapping_ids_do_not_contain_the_subject() -> None:
    container = fake()
    await CosmosMappingStore(container, customer_id=CUSTOMER).register("person@example.invalid")  # type: ignore[arg-type]
    ((partition, doc_id),) = container.docs
    assert partition == (CUSTOMER,)
    assert "person" not in doc_id
    assert len(doc_id) == 64


async def test_each_store_is_confined_to_its_customer_partition() -> None:
    container = fake()
    mine = CosmosHoldRegistry(container, customer_id="contoso")  # type: ignore[arg-type]
    theirs = CosmosHoldRegistry(container, customer_id="fabrikam")  # type: ignore[arg-type]
    await mine.place(make_hold("hold-1"))
    assert await theirs.active() == []
    assert await theirs.release("hold-1") is False
    assert len(await mine.active()) == 1
    for _, params, partition in container.queries:
        assert partition is not None
        assert params["@customer"] in {"contoso", "fabrikam"}


async def test_queue_queries_are_single_partition() -> None:
    container = fake()
    queue = CosmosRequestQueue(container, customer_id=CUSTOMER)  # type: ignore[arg-type]
    item = make_queued("c-1")
    await queue.enqueue(item)
    await queue.pending()
    await queue.remove(item.request.request_id)
    assert container.queries
    assert all(partition == (CUSTOMER,) for _, _, partition in container.queries)
    assert container.docs == {}


async def test_outage_and_throttle_are_mapped() -> None:
    container = fake()
    holds = CosmosHoldRegistry(container, customer_id=CUSTOMER)  # type: ignore[arg-type]
    container.fail = RuntimeError("sdk detail")
    with pytest.raises(DependencyTransientError) as outage:
        await holds.active()
    assert "sdk detail" not in str(outage.value)
    container.fail = throttled()
    with pytest.raises(RateLimitedError):
        await holds.place(make_hold("hold-1"))
