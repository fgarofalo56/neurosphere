"""Cosmos lifecycle stores against the compose emulator (same contracts as CI)."""

from __future__ import annotations

import pytest
import pytest_asyncio
from azure.cosmos.aio import DatabaseProxy
from neurosphere_core.lifecycle.cosmos import (
    CosmosHoldRegistry,
    CosmosMappingStore,
    CosmosRequestQueue,
    create_hold_container,
    create_mapping_container,
    create_request_container,
)

from .support import load_contract

contract = load_contract("lifecycle_cosmos")

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def mappings(database: DatabaseProxy) -> CosmosMappingStore:
    return CosmosMappingStore(
        await create_mapping_container(database), customer_id=contract.CUSTOMER
    )


@pytest_asyncio.fixture
async def holds(database: DatabaseProxy) -> CosmosHoldRegistry:
    return CosmosHoldRegistry(await create_hold_container(database), customer_id=contract.CUSTOMER)


@pytest_asyncio.fixture
async def queue(database: DatabaseProxy) -> CosmosRequestQueue:
    return CosmosRequestQueue(
        await create_request_container(database), customer_id=contract.CUSTOMER
    )


class TestMappingStoreEmulator(contract.MappingStoreContract):
    pass


class TestHoldRegistryEmulator(contract.HoldRegistryContract):
    pass


class TestRequestQueueEmulator(contract.RequestQueueContract):
    pass
