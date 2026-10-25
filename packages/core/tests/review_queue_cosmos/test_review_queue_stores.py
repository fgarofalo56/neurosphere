"""Catalog ReviewQueue: one contract, two backends (in-memory, Cosmos over an in-process fake).

The fake container lives in ``hitl_cosmos`` (shared by the three PRP-29 item 3 suites). The
emulator run is ``tests/integration/stores_hitl`` (marked ``integration``; not run in CI).
"""

from __future__ import annotations

import pytest
from azure.cosmos.exceptions import CosmosAccessConditionFailedError
from hitl_cosmos.fake_container import FakeContainer, throttled
from neurosphere_core.catalog import InMemoryReviewQueue, ReviewQueue
from neurosphere_core.catalog.review_queue_cosmos import (
    DEFAULT_REVIEW_QUEUE_CONTAINER,
    REVIEW_QUEUE_PARTITION_KEY_PATHS,
    CosmosReviewQueue,
)
from neurosphere_core.errors import DependencyTransientError, RateLimitedError, StaleVersionError

from .contract import FINANCE, RETAIL, STEWARD, ReviewQueueContract, make_item, make_scope


def cosmos_queue() -> tuple[CosmosReviewQueue, FakeContainer]:
    container = FakeContainer(REVIEW_QUEUE_PARTITION_KEY_PATHS)
    return CosmosReviewQueue(container), container  # type: ignore[arg-type]


@pytest.fixture(params=["memory", "cosmos-fake"])
def queue(request: pytest.FixtureRequest) -> ReviewQueue:
    if request.param == "memory":
        return InMemoryReviewQueue()
    return cosmos_queue()[0]


class TestReviewQueueContract(ReviewQueueContract):
    pass


def test_container_constants_match_the_wire_contract() -> None:
    assert DEFAULT_REVIEW_QUEUE_CONTAINER == "catalog_review_queue"
    from neurosphere_core.stores import containers

    spec = {c.name: c for c in containers.CONTAINERS}[DEFAULT_REVIEW_QUEUE_CONTAINER]
    assert REVIEW_QUEUE_PARTITION_KEY_PATHS == ("/customer_id", "/domain_id")
    assert spec.partition_key_paths == REVIEW_QUEUE_PARTITION_KEY_PATHS


async def test_items_are_partitioned_by_customer_and_domain() -> None:
    queue, container = cosmos_queue()
    await queue.enqueue(make_scope([FINANCE]), make_item())
    ((partition, doc_id),) = container.docs
    assert partition == ("contoso", FINANCE)
    assert "domain" not in container.docs[(partition, doc_id)]
    assert doc_id == "review:one"


async def test_reads_are_bounded_by_the_scope_domains_cloud_and_customer() -> None:
    queue, container = cosmos_queue()
    scope = make_scope([FINANCE])
    await queue.enqueue(scope, make_item())
    await queue.list_open(scope, limit=5)
    sql, params, partition = container.queries[-1]
    assert partition is None
    assert "ARRAY_CONTAINS(@domains, c.domain_id)" in sql
    assert "c.customer_id = @customer" in sql
    assert "TOP @limit" in sql
    assert params["@limit"] == 5
    assert params["@domains"] == [FINANCE]
    assert params["@customer"] == "contoso"


async def test_get_with_one_allowed_domain_is_a_point_read() -> None:
    queue, container = cosmos_queue()
    scope = make_scope([FINANCE])
    await queue.enqueue(scope, make_item())
    assert (await queue.get(scope, "review:one")) is not None
    assert await queue.get(scope, "review:missing") is None
    assert container.queries == []


async def test_get_with_several_allowed_domains_is_a_bounded_scoped_query() -> None:
    queue, container = cosmos_queue()
    scope = make_scope([FINANCE, RETAIL])
    await queue.enqueue(scope, make_item())
    assert (await queue.get(scope, "review:one")) is not None
    sql, _, _ = container.queries[-1]
    assert "TOP 1" in sql
    assert "ARRAY_CONTAINS(@domains, c.domain_id)" in sql


async def test_an_empty_scope_issues_no_query() -> None:
    queue, container = cosmos_queue()
    assert await queue.list_open(make_scope([])) == ()
    assert await queue.get(make_scope([]), "review:one") is None
    assert container.queries == []


async def test_resolve_retries_after_losing_an_etag_race() -> None:
    queue, container = cosmos_queue()
    scope = make_scope([FINANCE])
    await queue.enqueue(scope, make_item())
    real = container.replace_item
    attempts = 0

    async def flaky(item: str, body: dict, **kw: object) -> dict:  # type: ignore[type-arg]
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise CosmosAccessConditionFailedError(status_code=412, message="etag")
        return await real(item, body, **kw)

    container.replace_item = flaky  # type: ignore[method-assign]
    resolved = await queue.resolve(
        scope,
        "review:one",
        resolved_by=STEWARD,
        resolution="kept_curation",
        resolved_at="2026-10-18T09:00:00Z",
    )
    assert resolved.status == "resolved"
    assert attempts == 2


async def test_resolve_gives_up_with_stale_version_when_the_race_never_ends() -> None:
    queue, container = cosmos_queue()
    scope = make_scope([FINANCE])
    await queue.enqueue(scope, make_item())

    async def always_stale(item: str, body: dict, **kw: object) -> dict:  # type: ignore[type-arg]
        raise CosmosAccessConditionFailedError(status_code=412, message="etag")

    container.replace_item = always_stale  # type: ignore[method-assign]
    with pytest.raises(StaleVersionError):
        await queue.resolve(
            scope,
            "review:one",
            resolved_by=STEWARD,
            resolution="kept_curation",
            resolved_at="2026-10-18T09:00:00Z",
        )


async def test_outage_and_throttle_are_mapped_without_leaking_sdk_text() -> None:
    queue, container = cosmos_queue()
    scope = make_scope([FINANCE])
    container.fail = RuntimeError("secret sdk detail")
    with pytest.raises(DependencyTransientError) as outage:
        await queue.get(scope, "review:one")
    assert "secret" not in str(outage.value)
    container.fail = throttled()
    with pytest.raises(RateLimitedError):
        await queue.enqueue(scope, make_item())
