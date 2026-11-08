"""PRP-10 item 9 (#54): lock, observation and review-queue semantics, one regression each."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from neurosphere_core.catalog import (
    EdgeFilter,
    InMemoryReviewQueue,
    merge_observation,
    observation_id,
    present_edge,
    review_item_id,
)
from neurosphere_core.catalog.repo import InMemoryCatalogRepository
from neurosphere_core.paging import PageRequest

from .repo_conformance import agent, dom, edge, edge_id
from .repo_conformance import make_scope as repo_scope
from .test_review_queue import FINANCE as QUEUE_DOMAIN
from .test_review_queue import make_scope as queue_scope
from .test_rules import (
    AFTER_EXPIRY,
    EDGE_ID,
    NOW,
    _new_observation,  # pyright: ignore[reportPrivateUsage]
    lock_override,
    make_edge,
    make_override,
)

RESOLVED_AT = "2026-10-17T11:00:00Z"
PERSON = "commercial:contoso:entra:person:psn_0123456789abcdef"


# 1. stale lineage after lock expiry


def test_presented_lineage_refreshes_from_newest_observation_after_lock_expiry() -> None:
    lock = lock_override()
    outcome = merge_observation(make_edge(), _new_observation(confidence=0.2), [lock], NOW)
    assert outcome.stored.confidence == 0.82  # frozen while locked

    stale = present_edge(outcome.stored, [lock], AFTER_EXPIRY)
    assert stale.confidence == 0.82  # no observation supplied: the old behaviour
    fresh = present_edge(outcome.stored, [lock], AFTER_EXPIRY, outcome.observation)
    assert fresh.confidence == 0.2
    assert fresh.validity == outcome.observation.validity
    # while the lock is active the observation never overrides the pin
    assert present_edge(outcome.stored, [lock], NOW, outcome.observation).confidence == 0.82


# 2. resolved review item must not swallow later conflicts


async def test_conflict_after_resolution_is_enqueued_and_open_duplicate_is_not() -> None:
    scope = queue_scope([QUEUE_DOMAIN])
    queue = InMemoryReviewQueue()
    lock = lock_override()

    first = merge_observation(make_edge(), _new_observation(confidence=0.2), [lock], NOW)
    assert first.review_item is not None
    assert await queue.enqueue(scope, first.review_item) is True
    assert await queue.enqueue(scope, first.review_item) is False  # replay

    again = merge_observation(
        first.stored,
        _new_observation(confidence=0.1, last_observed="2026-10-17T11:30:00Z"),
        [lock],
        NOW,
    )
    assert again.review_item is not None
    assert await queue.enqueue(scope, again.review_item) is False  # same conflict, still open

    await queue.resolve(
        scope,
        first.review_item.id,
        resolved_by=PERSON,
        resolution="kept_curation",
        resolved_at=RESOLVED_AT,
    )
    later = merge_observation(
        again.stored,
        _new_observation(confidence=0.05, last_observed="2026-10-17T11:45:00Z"),
        [lock],
        NOW,
    )
    assert later.review_item is not None
    assert later.review_item.id != first.review_item.id
    assert await queue.enqueue(scope, later.review_item) is True
    assert await queue.enqueue(scope, first.review_item) is False  # replaying the old one


def test_review_item_id_depends_on_generation() -> None:
    assert review_item_id("e", "r", "g", "t1") != review_item_id("e", "r", "g", "t2")
    assert review_item_id("e", "r", "g", "t1") == review_item_id("e", "r", "g", "t1")


# 3. expired lock set_confidence must not leak into a replacement lock


def test_expired_lock_confidence_does_not_carry_into_replacement_lock() -> None:
    early = make_override(
        "lock",
        "2026-10-10T00:00:00Z",
        ident="lock-a",
        expiry="2026-11-01T00:00:00Z",
        set_confidence=0.4,
    )
    replacement = make_override(
        "lock", "2026-11-02T00:00:00Z", ident="lock-b", expiry="2026-12-01T00:00:00Z"
    )
    now = datetime(2026, 11, 10, tzinfo=UTC)
    presented = present_edge(make_edge(), [early, replacement], now)
    assert presented.pinned
    assert presented.confidence == 0.82
    assert presented.override_ids == [replacement.id]


# 4. observation id includes confidence


def test_observation_id_distinguishes_confidence() -> None:
    args = (EDGE_ID, ["trace:a"], "2026-10-17T11:00:00Z")
    assert observation_id(*args, 0.2) != observation_id(*args, 0.9)
    assert observation_id(*args, 0.2) == observation_id(*args, 0.2)
    low = merge_observation(None, _new_observation(confidence=0.2), [], NOW)
    high = merge_observation(None, _new_observation(confidence=0.9), [], NOW)
    assert low.observation.id != high.observation.id


# 5. replay must not regress confidence or last_observed


def test_older_observation_after_newer_does_not_regress() -> None:
    newer = _new_observation(confidence=0.9, last_observed="2026-10-17T11:00:00Z")
    stored = merge_observation(make_edge(), newer, [], NOW).stored
    assert stored.confidence == 0.9

    older = _new_observation(
        confidence=0.1, evidence_ids=["trace:old"], last_observed="2026-10-17T08:00:00Z"
    )
    replay = merge_observation(stored, older, [], NOW)
    assert replay.stored.confidence == 0.9
    assert replay.stored.last_observed.root == "2026-10-17T11:00:00Z"
    assert "trace:old" in [e.root for e in replay.stored.evidence_ids]  # evidence still unions
    assert replay.observation.confidence == 0.1  # the raw observation is still recorded


# 6. domain-level edge listing


async def test_list_edges_by_domain_is_scoped_filtered_and_paged() -> None:
    ns = f"t{uuid.uuid4().hex[:10]}"
    repo = InMemoryCatalogRepository()
    sa = repo_scope(ns, [dom(ns, "a")])
    sb = repo_scope(ns, [dom(ns, "b")])
    sab = repo_scope(ns, [dom(ns, "a"), dom(ns, "b")])
    for name in ("n1", "n2", "n3"):
        await repo.create_entity(sa, agent(ns, name, "a"))
    await repo.create_entity(sb, agent(ns, "nb", "b"))
    await repo.put_edge(sa, edge(ns, "e12", "n1", "n2", "a"), None)
    await repo.put_edge(sa, edge(ns, "e13", "n1", "n3", "a", status="asserted"), None)
    await repo.put_edge(sa, edge(ns, "e23", "n2", "n3", "a"), None)
    await repo.put_edge(sb, edge(ns, "eb", "nb", "n1", "b"), None)

    listed = await repo.list_edges_by_domain(sa, dom(ns, "a"), EdgeFilter(), PageRequest())
    assert [e.id for e in listed.items] == [edge_id(ns, n) for n in ("e12", "e13", "e23")]
    assert (
        await repo.list_edges_by_domain(sa, dom(ns, "b"), EdgeFilter(), PageRequest())
    ).items == ()
    asserted = await repo.list_edges_by_domain(
        sa, dom(ns, "a"), EdgeFilter(statuses=["asserted"]), PageRequest()
    )
    assert [e.id for e in asserted.items] == [edge_id(ns, "e13")]
    first = await repo.list_edges_by_domain(
        sab, dom(ns, "a"), EdgeFilter(), PageRequest(page_size=2)
    )
    assert len(first.items) == 2 and first.next_cursor is not None
    second = await repo.list_edges_by_domain(
        sab, dom(ns, "a"), EdgeFilter(), PageRequest(page_size=2, cursor=first.next_cursor)
    )
    assert [e.id for e in second.items] == [edge_id(ns, "e23")]
    other = repo_scope(f"{ns}x", [dom(f"{ns}x", "a")])
    assert (
        await repo.list_edges_by_domain(other, dom(ns, "a"), EdgeFilter(), PageRequest())
    ).items == ()
