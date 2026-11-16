"""Durable plan approvals (PRP-55 item 1): create-only, conflict, expiry, no eviction, value-free.

Both implementations run the same cases. The Cosmos repository runs over an in-memory fake
container, so the "two processes on one container" property is two repository instances sharing
that fake. No network.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from azure.cosmos.exceptions import CosmosResourceNotFoundError
from neurosphere_contracts.deployment.v1.deploy_action_plan import ResourceSpec
from neurosphere_core.deploy.approvals import (
    PLAN_ID_CONFLICT,
    InMemoryPlanApprovalRepository,
    PlanApprovalRecord,
    PlanApprovalRepository,
)
from neurosphere_core.deploy.approvals.cosmos_store import (
    DEFAULT_APPROVALS_CONTAINER,
    PARTITION_KEY_PATH,
    CosmosPlanApprovalRepository,
)
from neurosphere_core.errors import InvalidSchemaError
from neurosphere_core.stores import container_spec
from pydantic import ValidationError

from .fake_container import FakeContainer

T0 = datetime(2026, 11, 16, 12, 0, 0, tzinfo=UTC)
CUSTOMER = "contoso"
PLAN_ID = "plan-0123456789abcdef0123456789abcdef"
HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
DIGEST = "sha256:" + "d" * 64
SUB = "aaaaaaaa-0000-4000-8000-000000000001"


class Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now


def _spec() -> ResourceSpec:
    return ResourceSpec.model_validate(
        {
            "service": "storage",
            "kind": "arm_resource",
            "disposition": "create",
            "name": "nsstdemoeastus2",
            "region": "eastus2",
            "sku": None,
            "resource_id": None,
            "subscription_id": SUB,
            "resource_group": "rg-neurosphere",
            "consent_reference": None,
        }
    )


def _record(
    *, plan_hash: str = HASH_A, customer: str = CUSTOMER, at: datetime = T0, ttl_h: int = 24
) -> PlanApprovalRecord:
    return PlanApprovalRecord(
        customer_id=customer,
        plan_id=PLAN_ID,
        plan_hash=plan_hash,
        resources_digest=DIGEST,
        deployment_id="demo-eastus2",
        cloud="commercial",
        resources=(_spec(),),
        approver="pp-7f3a9c",
        approved_at=at,
        expires_at=at + timedelta(hours=ttl_h),
    )


Factory = Callable[[Clock], PlanApprovalRepository]


def _memory(clock: Clock) -> PlanApprovalRepository:
    return InMemoryPlanApprovalRepository(clock)


def _cosmos(clock: Clock) -> PlanApprovalRepository:
    return CosmosPlanApprovalRepository(FakeContainer(), clock=clock)  # type: ignore[arg-type]


@pytest.fixture(params=[_memory, _cosmos], ids=["memory", "cosmos"])
def factory(request: pytest.FixtureRequest) -> Factory:
    return request.param  # type: ignore[no-any-return]


async def test_create_then_get_returns_the_record(factory: Factory) -> None:
    repo = factory(Clock())
    stored = await repo.create(_record())
    assert stored == _record()
    assert await repo.get(CUSTOMER, PLAN_ID) == _record()
    assert await repo.get("fabrikam", PLAN_ID) is None  # keyed by customer


async def test_same_hash_is_idempotent_and_keeps_the_first_window(factory: Factory) -> None:
    clock = Clock()
    repo = factory(clock)
    first = await repo.create(_record())
    clock.now = T0 + timedelta(hours=1)
    again = await repo.create(_record(at=clock.now))
    assert again == first


async def test_a_different_hash_under_a_live_approval_is_plan_id_conflict(
    factory: Factory,
) -> None:
    repo = factory(Clock())
    await repo.create(_record())
    with pytest.raises(InvalidSchemaError) as raised:
        await repo.create(_record(plan_hash=HASH_B))
    assert raised.value.reason == PLAN_ID_CONFLICT
    found = await repo.get(CUSTOMER, PLAN_ID)
    assert found is not None and found.plan_hash == HASH_A


async def test_expired_reads_as_absent_and_can_be_replaced(factory: Factory) -> None:
    clock = Clock()
    repo = factory(clock)
    await repo.create(_record(ttl_h=1))
    clock.now = T0 + timedelta(hours=1)  # expires_at == now: expired
    assert await repo.get(CUSTOMER, PLAN_ID) is None
    replaced = await repo.create(_record(plan_hash=HASH_B, at=clock.now))
    assert replaced.plan_hash == HASH_B
    found = await repo.get(CUSTOMER, PLAN_ID)
    assert found is not None and found.plan_hash == HASH_B


async def test_no_eviction(factory: Factory) -> None:
    repo = factory(Clock())
    ids = [f"plan-{i:032x}" for i in range(1200)]
    for plan_id in ids:
        await repo.create(_record().model_copy(update={"plan_id": plan_id}))
    assert await repo.get(CUSTOMER, ids[0]) is not None
    assert await repo.get(CUSTOMER, ids[-1]) is not None


async def test_two_repository_instances_on_one_container_share_approvals() -> None:
    container = FakeContainer()
    api_side = CosmosPlanApprovalRepository(container, clock=Clock())  # type: ignore[arg-type]
    worker_side = CosmosPlanApprovalRepository(container, clock=Clock())  # type: ignore[arg-type]
    await api_side.create(_record())
    assert await worker_side.get(CUSTOMER, PLAN_ID) == _record()
    with pytest.raises(InvalidSchemaError):
        await worker_side.create(_record(plan_hash=HASH_B))


async def test_a_lost_create_race_is_decided_by_the_winner() -> None:
    container = FakeContainer()
    repo = CosmosPlanApprovalRepository(container, clock=Clock())  # type: ignore[arg-type]
    original_read = container.read_item
    calls = {"n": 0}

    async def read_then_race(item: str, partition_key: str) -> dict[str, Any]:
        calls["n"] += 1
        if calls["n"] == 1:  # first read sees nothing, then another approver wins
            await container.create_item(
                {**_record(plan_hash=HASH_B).model_dump(mode="json"), "id": PLAN_ID}
            )
            raise CosmosResourceNotFoundError(status_code=404, message="not found")
        return await original_read(item, partition_key)

    container.read_item = read_then_race  # type: ignore[method-assign]
    with pytest.raises(InvalidSchemaError) as raised:
        await repo.create(_record())
    assert raised.value.reason == PLAN_ID_CONFLICT


async def test_the_document_is_value_free() -> None:
    container = FakeContainer()
    repo = CosmosPlanApprovalRepository(container, clock=Clock())  # type: ignore[arg-type]
    await repo.create(_record())
    (doc,) = container.docs.values()
    assert doc["id"] == PLAN_ID and doc["customer_id"] == CUSTOMER
    assert doc["doc_type"] == "plan_approval"
    text = json.dumps(doc).lower()
    for word in ("secret", "password", "token", "connectionstring", "@"):
        assert word not in text


def test_an_email_approver_is_refused() -> None:
    with pytest.raises(ValidationError):
        PlanApprovalRecord.model_validate(
            {**_record().model_dump(mode="json"), "approver": "dave@contoso.com"}
        )


def test_an_inverted_window_is_refused() -> None:
    with pytest.raises(ValidationError):
        PlanApprovalRecord.model_validate(
            {**_record().model_dump(mode="json"), "expires_at": T0.isoformat()}
        )


def test_the_registry_declares_the_container() -> None:
    spec = container_spec(DEFAULT_APPROVALS_CONTAINER)
    assert spec.partition_key_paths == (PARTITION_KEY_PATH,)
    assert spec.default_ttl is None
