"""CosmosReviewQueue open-duplicate race on the compose emulator (PRP-43 item 4).

Run locally with the emulator up (``docker compose up -d --wait``); the python CI job skips the
``integration`` marker. Use ``127.0.0.1``: ``localhost`` resolves to ``::1`` and the Docker IPv6
forward is flaky.
"""

from __future__ import annotations

import asyncio
import base64
import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from azure.cosmos.aio import DatabaseProxy
from neurosphere_core.catalog import ReviewItem
from neurosphere_core.catalog.review_queue_cosmos import (
    CosmosReviewQueue,
    create_review_queue_container,
)
from neurosphere_core.clients import ClientLifetime, create_cosmos_client
from neurosphere_core.cloud import Settings

from .test_repo_cosmos import helper

NS = "rqit"
dom = helper.dom
make_scope = helper.make_scope

pytestmark = pytest.mark.integration

DOMAIN = dom(NS, "a")
EDGE = f"commercial:{NS}:foundry:invokes:e-0001"
OVERRIDE = f"commercial:{NS}:foundry:edge_override:lock-1"


@pytest.fixture(autouse=True)
def _emulator_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NS_ENV", "local")
    monkeypatch.setenv("NS_COSMOS_ENDPOINT", "http://127.0.0.1:8081")
    monkeypatch.setenv("NS_COSMOS_KEY", base64.b64encode(b"emulator-ignores-this").decode())


@pytest_asyncio.fixture
async def database() -> AsyncIterator[DatabaseProxy]:
    async with ClientLifetime() as lifetime:
        client = create_cosmos_client(Settings(env="local"), lifetime=lifetime)
        yield await client.create_database_if_not_exists("ns_catalog_rq_it")


def _item(item_id: str) -> ReviewItem:
    return ReviewItem(
        id=item_id,
        edge_id=EDGE,
        relation_type="invokes",
        cloud="commercial",
        customer_id=NS,
        domain_id=DOMAIN,
        reason="conflicts_with_lock",
        governing_override_id=OVERRIDE,
        observed_confidence=0.4,
        presented_confidence=0.9,
        new_evidence_ids=[],
        created_at="2026-10-17T10:00:00Z",
    )


async def test_concurrent_enqueues_leave_one_open_item_then_resolve_frees(
    database: DatabaseProxy,
) -> None:
    container = await create_review_queue_container(database, f"rq_{uuid.uuid4().hex[:8]}")
    try:
        queue = CosmosReviewQueue(container)
        scope = make_scope(NS, [DOMAIN])
        results = await asyncio.gather(
            *(queue.enqueue(scope, _item(f"review:{i}")) for i in range(6))
        )
        assert results.count(True) == 1
        open_items = await queue.list_open(scope)
        assert len(open_items) == 1
        await queue.resolve(
            scope,
            open_items[0].id,
            resolved_by=f"commercial:{NS}:entra:person:psn_steward000000001",
            resolution="kept_curation",
            resolved_at="2026-10-17T11:00:00Z",
        )
        assert await queue.enqueue(scope, _item("review:later"))
        assert [i.id for i in await queue.list_open(scope)] == ["review:later"]
    finally:
        await database.delete_container(container.id)
