"""PRP-43 item 4: the Cosmos review queue's open-conflict marker (fake container, no emulator)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from hitl_cosmos.fake_container import FakeContainer  # pyright: ignore[reportMissingImports]
from neurosphere_core.catalog import ReviewItem
from neurosphere_core.catalog.review_queue_cosmos import (
    REVIEW_QUEUE_PARTITION_KEY_PATHS,
    CosmosReviewQueue,
)

from .graph_helpers import NS, dom, make_scope, nid

DOMAIN = dom(NS, "a")
EDGE = f"commercial:{NS}:foundry:invokes:e-0001"
OVERRIDE = f"commercial:{NS}:foundry:edge_override:lock-1"
NOW = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)


def _item(item_id: str, at: str = "2026-10-17T10:00:00Z") -> ReviewItem:
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
        created_at=at,
    )


def _queue(clock: list[datetime] | None = None) -> tuple[CosmosReviewQueue, FakeContainer]:
    container = FakeContainer(REVIEW_QUEUE_PARTITION_KEY_PATHS)
    ticks = clock if clock is not None else [NOW]
    return CosmosReviewQueue(container, now=lambda: ticks[0]), container  # type: ignore[arg-type]


async def test_concurrent_enqueues_leave_exactly_one_open_item() -> None:
    queue, _ = _queue()
    scope = make_scope(NS, [DOMAIN])
    results = await asyncio.gather(
        *(queue.enqueue(scope, _item(f"review:{i}", f"2026-10-17T10:00:0{i}Z")) for i in range(5))
    )
    assert results.count(True) == 1
    assert len(await queue.list_open(scope)) == 1


async def test_resolve_frees_the_conflict_for_a_later_item() -> None:
    queue, _ = _queue()
    scope = make_scope(NS, [DOMAIN])
    assert await queue.enqueue(scope, _item("review:1"))
    assert not await queue.enqueue(scope, _item("review:2"))
    await queue.resolve(
        scope,
        "review:1",
        resolved_by=nid("steward"),
        resolution="kept_curation",
        resolved_at="2026-10-17T11:00:00Z",
    )
    assert await queue.enqueue(scope, _item("review:3", "2026-10-17T12:00:00Z"))
    assert [i.id for i in await queue.list_open(scope)] == ["review:3"]


async def test_markers_are_never_listed_or_readable_as_items() -> None:
    queue, container = _queue()
    scope = make_scope(NS, [DOMAIN])
    await queue.enqueue(scope, _item("review:1"))
    markers = [k for k in container.docs if k[1].startswith("open-")]
    assert len(markers) == 1
    assert await queue.get(scope, markers[0][1]) is None
    assert [i.id for i in await queue.list_open(scope)] == ["review:1"]


async def test_item_stored_before_markers_existed_still_deduplicates() -> None:
    queue, container = _queue()
    scope = make_scope(NS, [DOMAIN])
    legacy = _item("review:legacy")
    body = legacy.model_dump(mode="json")
    body["sort_key"] = f"{legacy.created_at}|{legacy.id}"
    await container.create_item(body=body)
    assert not await queue.enqueue(scope, _item("review:new"))
    assert len(await queue.list_open(scope)) == 1


async def test_orphan_marker_is_taken_over_after_the_stale_window() -> None:
    ticks = [NOW]
    queue, container = _queue(ticks)
    scope = make_scope(NS, [DOMAIN])
    # a crash between the marker write and the item write leaves a marker with no item
    original = container.create_item
    calls = {"n": 0}

    async def crash_on_item(body: dict[str, object], **kw: object) -> object:
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("crash")
        return await original(body=body, **kw)

    container.create_item = crash_on_item  # type: ignore[method-assign]
    try:
        await queue.enqueue(scope, _item("review:1"))
    except Exception:  # noqa: S110
        pass
    container.create_item = original  # type: ignore[method-assign]
    assert not await queue.enqueue(scope, _item("review:2"))  # fresh orphan still holds
    ticks[0] = NOW + timedelta(minutes=5)
    assert await queue.enqueue(scope, _item("review:2"))
