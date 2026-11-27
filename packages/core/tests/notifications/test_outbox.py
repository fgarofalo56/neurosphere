"""Outbox contract: runs against the in-memory store and the Cosmos store on a fake container."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from neurosphere_contracts.notifications.v1.notification import NotificationDelivery
from neurosphere_core.errors import DependencyTransientError, StaleVersionError
from neurosphere_core.notifications import (
    InMemoryOutboxStore,
    NotificationPublisher,
    Outbox,
    RetryPolicy,
)
from neurosphere_core.notifications.cosmos_store import PARTITION_KEY_PATH, CosmosOutboxStore
from neurosphere_core.notifications.outbox import parse_timestamp

from .fake_container import FakeContainer, throttled
from .helpers import CUSTOMER, DOMAIN_A, OWNER, Rig, make_event


@pytest.fixture(params=["memory", "cosmos-fake"])
def store(request: pytest.FixtureRequest) -> Any:
    if request.param == "memory":
        return InMemoryOutboxStore()
    return CosmosOutboxStore(FakeContainer((PARTITION_KEY_PATH,)))  # type: ignore[arg-type]


async def _rig(store: Any) -> Rig:
    rig = Rig(store)
    await rig.add_channel("chan-a", DOMAIN_A)
    await rig.add_subscription("sub-a", "chan-a", DOMAIN_A)
    rig.grants.grant(OWNER, CUSTOMER, DOMAIN_A, "data.read")
    return rig


async def test_same_event_twice_is_one_row(store: Any) -> None:
    rig = await _rig(store)
    assert len(await rig.publisher.publish(make_event())) == 1
    assert await rig.publisher.publish(make_event()) == []
    assert len(await store.list_deliveries(CUSTOMER)) == 1


async def test_dedup_survives_restart_and_bucket_boundary(store: Any) -> None:
    rig = await _rig(store)
    await rig.publisher.publish(make_event(window=900))
    rig.clock.advance(899)  # inside the window but (likely) across a bucket edge
    # A new process: fresh Outbox and publisher over the same durable store.
    again = NotificationPublisher(rig.resolver, Outbox(store, clock=rig.clock), rig.registry)
    assert await again.publish(make_event(window=900)) == []
    rig.clock.advance(2)  # now outside the window
    assert len(await again.publish(make_event(window=900))) == 1
    assert len(await store.list_deliveries(CUSTOMER)) == 2


async def test_concurrent_publish_collapses_to_one_row(store: Any) -> None:
    rig = await _rig(store)
    results = await asyncio.gather(*(rig.publisher.publish(make_event()) for _ in range(5)))
    assert sum(len(r) for r in results) == 1
    assert len(await store.list_deliveries(CUSTOMER)) == 1


async def test_different_dedup_keys_are_different_rows(store: Any) -> None:
    rig = await _rig(store)
    await rig.publisher.publish(make_event(dedup_key="a"))
    await rig.publisher.publish(make_event(dedup_key="b"))
    assert len(await store.list_deliveries(CUSTOMER)) == 2


async def test_claim_race_second_claim_fails(store: Any) -> None:
    rig = await _rig(store)
    await rig.publisher.publish(make_event())
    (entry,) = await store.due(now=rig.clock(), limit=10)
    first = await rig.outbox.claim(entry)
    second = await rig.outbox.claim(entry)  # same stale ETag: a second worker
    assert first is not None and first.delivery.status == "sending"
    assert first.delivery.attempts == 1
    assert second is None


async def test_lease_expiry_allows_reclaim_and_not_before(store: Any) -> None:
    rig = await _rig(store)
    await rig.publisher.publish(make_event())
    (entry,) = await store.due(now=rig.clock(), limit=10)
    claimed = await rig.outbox.claim(entry)
    assert claimed is not None
    assert await rig.outbox.claim(claimed) is None  # lease still running
    assert await store.due(now=rig.clock(), limit=10) == []
    rig.clock.advance(301)
    (again,) = await store.due(now=rig.clock(), limit=10)
    reclaimed = await rig.outbox.claim(again)
    assert reclaimed is not None and reclaimed.delivery.attempts == 2


async def test_deliver_path_records_status_not_body(store: Any) -> None:
    rig = await _rig(store)
    await rig.publisher.publish(make_event())
    (entry,) = await store.due(now=rig.clock(), limit=10)
    claimed = await rig.outbox.claim(entry)
    assert claimed is not None
    done = await rig.outbox.mark_delivered(claimed, status_code=204)
    assert done is not None
    assert done.delivery.status == "delivered"
    assert done.delivery.last_error_code is not None
    assert done.delivery.last_error_code.root == "http_204"
    assert done.delivery.delivered_at is not None
    assert await store.due(now=rig.clock(), limit=10) == []


async def test_backoff_doubles_caps_and_attempt_cap_fails(store: Any) -> None:
    rig = await _rig(store)
    policy = RetryPolicy(max_attempts=8, retry_base_seconds=30)
    assert [policy.backoff_seconds(n) for n in range(1, 8)] == [30, 60, 120, 240, 480, 900, 900]
    await rig.publisher.publish(make_event())
    seen: list[int] = []
    final = None
    for _ in range(8):
        (entry,) = await store.due(now=rig.clock(), limit=10)
        claimed = await rig.outbox.claim(entry)
        assert claimed is not None
        result = await rig.outbox.mark_attempt_failed(
            claimed, reason="http_500", retryable=True, policy=policy
        )
        assert result is not None
        final = result
        if result.delivery.status == "pending":
            assert result.delivery.next_attempt_at is not None
            delay = (parse_timestamp(result.delivery.next_attempt_at.root) - rig.clock()).seconds
            seen.append(delay)
            assert await store.due(now=rig.clock(), limit=10) == []
            rig.clock.advance(delay)
    assert seen == [30, 60, 120, 240, 480, 900, 900]
    assert final is not None
    assert final.delivery.status == "failed" and final.delivery.attempts == 8
    assert final.delivery.last_error_code is not None
    assert final.delivery.last_error_code.root == "http_500"


async def test_permanent_failure_goes_straight_to_failed(store: Any) -> None:
    rig = await _rig(store)
    await rig.publisher.publish(make_event())
    (entry,) = await store.due(now=rig.clock(), limit=10)
    claimed = await rig.outbox.claim(entry)
    assert claimed is not None
    result = await rig.outbox.mark_attempt_failed(
        claimed, reason="blocked_host", retryable=False, policy=RetryPolicy()
    )
    assert result is not None and result.delivery.status == "failed"
    dead = await rig.outbox.dead_letter(result)
    assert dead is not None and dead.delivery.status == "dead_lettered"


async def test_illegal_transitions_are_refused(store: Any) -> None:
    rig = await _rig(store)
    await rig.publisher.publish(make_event())
    (entry,) = await store.due(now=rig.clock(), limit=10)
    with pytest.raises(StaleVersionError) as caught:
        await rig.outbox.mark_delivered(entry)  # pending -> delivered
    assert caught.value.reason == "invalid_transition"
    suppressed = await rig.outbox.suppress(entry)
    assert suppressed is not None
    assert suppressed.delivery.status == "suppressed"
    assert suppressed.delivery.last_error_code is not None
    assert suppressed.delivery.last_error_code.root == "scope"
    assert await rig.outbox.claim(suppressed) is None


async def test_final_rows_cannot_move(store: Any) -> None:
    rig = await _rig(store)
    await rig.publisher.publish(make_event())
    (entry,) = await store.due(now=rig.clock(), limit=10)
    suppressed = await rig.outbox.suppress(entry)
    assert suppressed is not None
    for call in (rig.outbox.dead_letter, rig.outbox.suppress):
        with pytest.raises(StaleVersionError):
            await call(suppressed)


async def test_get_and_status_listing(store: Any) -> None:
    rig = await _rig(store)
    (row,) = await rig.publisher.publish(make_event())
    got = await store.get(CUSTOMER, row.notification_id.root)
    assert got is not None and got.delivery == row
    assert await store.get(CUSTOMER, "00000000-0000-4000-8000-000000000000") is None
    assert len(await store.list_deliveries(CUSTOMER, status="pending")) == 1
    assert await store.list_deliveries(CUSTOMER, status="delivered") == []
    assert await store.list_deliveries("other") == []


async def test_channel_counts_error_code_and_channel_filter(store: Any) -> None:
    rig = await _rig(store)
    await rig.add_channel("chan-b", DOMAIN_A)
    await rig.add_subscription("sub-b", "chan-b", DOMAIN_A)
    rig.grants.grant(OWNER, CUSTOMER, DOMAIN_A, "data.read")
    await rig.publisher.publish(make_event(dedup_key="one"))
    rows = await rig.publisher.publish(make_event(dedup_key="two"))
    assert len(rows) == 2  # one row per subscribed channel
    for status in ("pending", "delivered"):
        expected = 2 if status == "pending" else 0
        count = await store.count_deliveries(CUSTOMER, channel_id="chan-a", status=status)
        assert count == expected
    assert await store.count_deliveries("other", channel_id="chan-a", status="pending") == 0
    assert await store.last_error_code(CUSTOMER, "chan-a") is None
    entries = await store.due(now=rig.clock(), limit=10)
    target = next(e for e in entries if e.delivery.channel_id.root == "chan-a")
    claimed = await rig.outbox.claim(target)
    assert claimed is not None
    failed = await rig.outbox.mark_attempt_failed(
        claimed, reason="http_410", retryable=False, policy=RetryPolicy()
    )
    assert failed is not None and failed.delivery.status == "failed"
    assert await store.last_error_code(CUSTOMER, "chan-a") == "http_410"
    assert await store.last_error_code(CUSTOMER, "chan-b") is None
    assert await store.count_deliveries(CUSTOMER, channel_id="chan-a", status="failed") == 1
    only_a = await store.list_deliveries(CUSTOMER, channel_id="chan-a", newest_first=True)
    assert {e.delivery.channel_id.root for e in only_a} == {"chan-a"}
    assert len(only_a) == 2
    assert only_a[0].delivery.created_at.root >= only_a[1].delivery.created_at.root


async def test_cosmos_store_rows_carry_ttl_and_no_extra_fields() -> None:
    container = FakeContainer((PARTITION_KEY_PATH,))
    rig = await _rig(CosmosOutboxStore(container, row_ttl_seconds=3600))  # type: ignore[arg-type]
    await rig.publisher.publish(make_event())
    (doc,) = container.docs.values()
    assert doc["ttl"] == 3600
    assert doc["id"] == doc["notification_id"]
    assert set(doc) - {"id", "ttl", "_etag", "_ts"} <= set(NotificationDelivery.model_fields)
    assert container.calls.count("replace_item") == 0


async def test_cosmos_errors_are_mapped() -> None:
    container = FakeContainer((PARTITION_KEY_PATH,))
    rig = await _rig(CosmosOutboxStore(container))  # type: ignore[arg-type]
    container.fail = throttled()
    with pytest.raises(Exception) as caught:
        await rig.publisher.publish(make_event())
    assert type(caught.value).__name__ == "RateLimitedError"
    container.fail = RuntimeError("boom with secret text")
    with pytest.raises(DependencyTransientError) as transient:
        await rig.publisher.publish(make_event())
    assert "secret text" not in str(transient.value)
    assert transient.value.reason == "notification_store_unavailable"
