"""HITL stores: one contract, two backends (in-memory, and Cosmos over an in-process fake).

The emulator run of the same contract is ``tests/integration/stores_hitl`` (marked
``integration``; never runs in CI).
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from neurosphere_core.errors import (
    DependencyTransientError,
    InvalidSchemaError,
    RateLimitedError,
)
from neurosphere_core.hitl import (
    DecisionStore,
    HitlStore,
    InMemoryDecisionStore,
    InMemoryHitlStore,
)
from neurosphere_core.hitl_cosmos.store import (
    DECISION_PARTITION_KEY_PATHS,
    DEFAULT_DECISION_CONTAINER,
    DEFAULT_ITEM_CONTAINER,
    ITEM_PARTITION_KEY_PATHS,
    CosmosDecisionStore,
    CosmosHitlStore,
)

from .contract import (
    DOMAIN,
    DecisionStoreContract,
    HitlStoreContract,
    make_decision,
    make_item,
    make_scope,
)
from .fake_container import FakeContainer, throttled


@pytest.fixture(params=["memory", "cosmos-fake"])
def store(request: pytest.FixtureRequest) -> HitlStore:
    if request.param == "memory":
        return InMemoryHitlStore()
    return CosmosHitlStore(FakeContainer(ITEM_PARTITION_KEY_PATHS))  # type: ignore[arg-type]


@pytest.fixture(params=["memory", "cosmos-fake"])
def rig(request: pytest.FixtureRequest) -> tuple[HitlStore, DecisionStore]:
    if request.param == "memory":
        return InMemoryHitlStore(), InMemoryDecisionStore()
    items = CosmosHitlStore(FakeContainer(ITEM_PARTITION_KEY_PATHS))  # type: ignore[arg-type]
    decisions = CosmosDecisionStore(
        FakeContainer(DECISION_PARTITION_KEY_PATHS)  # type: ignore[arg-type]
    )
    return items, decisions


class TestHitlStoreContract(HitlStoreContract):
    pass


class TestDecisionStoreContract(DecisionStoreContract):
    pass


# -- Cosmos-specific behaviour ------------------------------------------------------------------


def cosmos_items() -> tuple[CosmosHitlStore, FakeContainer]:
    container = FakeContainer(ITEM_PARTITION_KEY_PATHS)
    return CosmosHitlStore(container), container  # type: ignore[arg-type]


async def test_items_live_in_the_customer_domain_partition() -> None:
    items, container = cosmos_items()
    created = await items.create(make_item())
    ((partition, doc_id),) = container.docs
    assert partition == ("contoso", DOMAIN)
    assert doc_id == created.item_id


async def test_list_is_a_single_partition_bounded_query() -> None:
    items, container = cosmos_items()
    await items.create(make_item())
    await items.list(make_scope(), DOMAIN, limit=10)
    sql, params, partition = container.queries[-1]
    assert partition == ("contoso", DOMAIN)
    assert "TOP @limit" in sql
    assert params["@limit"] == 11


async def test_expiry_scan_is_bounded_and_only_reads_items_with_active_deadlines() -> None:
    items, container = cosmos_items()
    created = await items.create(make_item(sla_hours=1, expiry_hours=2))
    await items.due(created.created_at + timedelta(hours=3), limit=7)
    sql, params, partition = container.queries[-1]
    assert partition is None  # the protocol has no customer: the one cross-partition query
    assert "TOP @limit" in sql
    assert "IS_DEFINED(c.due_key)" in sql
    assert params["@limit"] == 7
    stored = next(iter(container.docs.values()))
    assert "due_key" in stored and "due_ts" in stored


async def test_final_items_carry_no_due_fields() -> None:
    from neurosphere_core.hitl.models import transition

    items, container = cosmos_items()
    created = await items.create(make_item())
    assert created.etag is not None
    await items.replace(transition(created, "expired"), if_match=created.etag)
    stored = next(iter(container.docs.values()))
    assert "due_key" not in stored and "due_ts" not in stored
    assert stored["state_name"] == "expired"


async def test_items_use_only_create_replace_read_and_query() -> None:
    items, container = cosmos_items()
    created = await items.create(make_item())
    await items.get(created.item_id)
    assert set(container.calls) <= {"create_item", "replace_item", "read_item", "query_items"}


async def test_outage_is_dependency_transient_and_throttle_is_rate_limited() -> None:
    items, container = cosmos_items()
    container.fail = RuntimeError("boom")
    with pytest.raises(DependencyTransientError) as outage:
        await items.get("x")
    assert outage.value.reason == "hitl_store_unavailable"
    assert "boom" not in str(outage.value)
    container.fail = throttled()
    with pytest.raises(RateLimitedError):
        await items.due(make_item().created_at)


async def test_decisions_are_append_only_at_the_container() -> None:
    items, _ = cosmos_items()
    container = FakeContainer(DECISION_PARTITION_KEY_PATHS)
    decisions = CosmosDecisionStore(container)  # type: ignore[arg-type]
    item = await items.create(make_item())
    doc = make_decision(item.item_id)
    await decisions.create(doc["decision_id"], doc)
    await decisions.get(doc["decision_id"])
    await decisions.list_for_item(item.item_id)
    assert set(container.calls) <= {"create_item", "read_item", "query_items"}
    assert "replace_item" not in container.calls
    assert "upsert_item" not in container.calls
    assert "delete_item" not in container.calls
    ((partition, _),) = container.docs
    assert partition == (item.item_id,)


def test_container_constants_match_the_registry() -> None:
    from neurosphere_core.stores import containers

    by_name = {spec.name: spec for spec in containers.CONTAINERS}
    assert DEFAULT_ITEM_CONTAINER == "hitl_items"
    assert DEFAULT_DECISION_CONTAINER == "hitl_decisions"
    assert by_name[DEFAULT_ITEM_CONTAINER].partition_key_paths == ITEM_PARTITION_KEY_PATHS
    assert by_name[DEFAULT_DECISION_CONTAINER].partition_key_paths == DECISION_PARTITION_KEY_PATHS


async def test_decision_list_is_a_single_partition_query() -> None:
    container = FakeContainer(DECISION_PARTITION_KEY_PATHS)
    decisions = CosmosDecisionStore(container)  # type: ignore[arg-type]
    await decisions.list_for_item("item-1")
    _, _, partition = container.queries[-1]
    assert partition == ("item-1",)


async def test_decision_without_a_review_item_id_is_refused() -> None:
    container = FakeContainer(DECISION_PARTITION_KEY_PATHS)
    decisions = CosmosDecisionStore(container)  # type: ignore[arg-type]
    with pytest.raises(InvalidSchemaError):
        await decisions.create("d1", {"decision": "approved"})
    assert container.docs == {}
