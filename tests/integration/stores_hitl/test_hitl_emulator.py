"""CosmosHitlStore and CosmosDecisionStore against the compose emulator (same contract as CI)."""

from __future__ import annotations

import pytest
import pytest_asyncio
from azure.cosmos.aio import DatabaseProxy
from neurosphere_core.hitl import DecisionStore, HitlStore
from neurosphere_core.hitl.cosmos_store import (
    CosmosDecisionStore,
    CosmosHitlStore,
    create_decision_container,
    create_item_container,
)

from .support import load_contract

contract = load_contract("hitl_cosmos")

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def store(database: DatabaseProxy) -> HitlStore:
    return CosmosHitlStore(await create_item_container(database))


@pytest_asyncio.fixture
async def rig(database: DatabaseProxy) -> tuple[HitlStore, DecisionStore]:
    items = CosmosHitlStore(await create_item_container(database))
    return items, CosmosDecisionStore(await create_decision_container(database), items)


class TestHitlStoreEmulator(contract.HitlStoreContract):
    pass


class TestDecisionStoreEmulator(contract.DecisionStoreContract):
    pass
