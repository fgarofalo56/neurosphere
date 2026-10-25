"""CosmosReviewQueue against the compose emulator (same contract as CI)."""

from __future__ import annotations

import pytest
import pytest_asyncio
from azure.cosmos.aio import DatabaseProxy
from neurosphere_core.catalog import ReviewQueue
from neurosphere_core.catalog.review_queue_cosmos import (
    CosmosReviewQueue,
    create_review_queue_container,
)

from .support import load_contract

contract = load_contract("review_queue_cosmos")

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def queue(database: DatabaseProxy) -> ReviewQueue:
    return CosmosReviewQueue(await create_review_queue_container(database))


class TestReviewQueueEmulator(contract.ReviewQueueContract):
    pass
