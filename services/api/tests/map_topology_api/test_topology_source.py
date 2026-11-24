"""TopologySource (PRP-74 item 4): scoped snapshots, fingerprint, diff to a MapTopologyChange,
shared scan per key, TTL and entry cap."""

import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import topology_push_helpers as th  # pyright: ignore[reportMissingImports]
from neurosphere_api.map.settings import MapSettings
from neurosphere_api.map.topology import (
    MAX_CHANGE_IDS,
    TopologySource,
    diff_snapshots,
)
from neurosphere_core.catalog import EntityFilter
from neurosphere_core.catalog.repo import InMemoryCatalogRepository
from neurosphere_core.paging import Page, PageRequest
from neurosphere_core.scope import IdentityScope

NOW = datetime(2027, 1, 15, 8, 30, tzinfo=UTC)


def _ids(change: Any) -> list[str]:
    return list(change.model_dump(mode="json")["entity_ids"])


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class CountingRepo(InMemoryCatalogRepository):
    def __init__(self) -> None:
        super().__init__()
        self.entity_scans = 0

    async def list_entities(
        self, scope: IdentityScope, flt: EntityFilter, page: PageRequest
    ) -> Page[Any]:
        self.entity_scans += 1
        return await super().list_entities(scope, flt, page)


@dataclass
class World:
    repo: CountingRepo
    clock: Clock
    source: TopologySource
    steward: IdentityScope
    alice: IdentityScope
    bob: IdentityScope


async def make_world(**source_args: Any) -> World:
    h = th.harness(*th.policies())
    repo = CountingRepo()
    clock = Clock()
    return World(
        repo=repo,
        clock=clock,
        source=TopologySource(repo, MapSettings(), clock=clock, **source_args),
        steward=await th.scope_of(h, th.STEWARD),
        alice=await th.scope_of(h, th.ALICE),
        bob=await th.scope_of(h, th.BOB),
    )


async def test_unchanged_graph_has_the_same_fingerprint_and_no_notice() -> None:
    w = await make_world()
    await th.seed(w.repo, w.steward, th.agent_doc("a1"))
    first = await w.source.snapshot(w.alice, th.FINANCE)
    w.clock.advance(10)
    second = await w.source.snapshot(w.alice, th.FINANCE)
    assert first.fingerprint == second.fingerprint
    assert (first.node_count, first.edge_count) == (1, 0)
    assert diff_snapshots(first, second, th.FINANCE, NOW) is None


async def test_added_agent_and_added_edge() -> None:
    w = await make_world()
    await th.seed(w.repo, w.steward, th.agent_doc("a1"))
    baseline = await w.source.snapshot(w.alice, th.FINANCE)

    await th.seed(w.repo, w.steward, th.agent_doc("a2"))
    w.clock.advance(10)
    with_agent = await w.source.snapshot(w.alice, th.FINANCE)
    change = diff_snapshots(baseline, with_agent, th.FINANCE, NOW)
    assert change is not None
    assert change.change_kinds == ["node_added"]
    assert _ids(change) == [th.agent_id("a2")]
    assert change.refetch is True
    assert change.truncated is False
    assert change.domain_id.root == th.FINANCE

    edge = th.make_edge("a1-a2", th.agent_id("a1"), th.agent_id("a2"))
    await th.seed_edges(w.repo, w.steward, edge)
    w.clock.advance(10)
    with_edge = await w.source.snapshot(w.alice, th.FINANCE)
    change = diff_snapshots(with_agent, with_edge, th.FINANCE, NOW)
    assert change is not None
    assert change.change_kinds == ["edge_added"]
    assert _ids(change) == [edge.id]


async def test_tag_change_bumps_the_version_and_is_node_updated() -> None:
    w = await make_world()
    await th.seed(w.repo, w.steward, th.agent_doc("a1"))
    before = await w.source.snapshot(w.alice, th.FINANCE)
    await th.retag(w.repo, w.steward, th.agent_id("a1"), "pii")
    w.clock.advance(10)
    after = await w.source.snapshot(w.alice, th.FINANCE)
    assert after.nodes[th.agent_id("a1")][0] == before.nodes[th.agent_id("a1")][0] + 1
    change = diff_snapshots(before, after, th.FINANCE, NOW)
    assert change is not None
    assert change.change_kinds == ["node_updated"]
    assert _ids(change) == [th.agent_id("a1")]


async def test_removals_give_the_removed_kinds() -> None:
    w = await make_world()
    await th.seed(w.repo, w.steward, th.agent_doc("a1"), th.agent_doc("a2"))
    await th.seed_edges(
        w.repo, w.steward, th.make_edge("a1-a2", th.agent_id("a1"), th.agent_id("a2"))
    )
    before = await w.source.snapshot(w.alice, th.FINANCE)
    assert before.edge_count == 1
    await th.retire(w.repo, w.steward, th.agent_id("a2"))
    w.clock.advance(10)
    after = await w.source.snapshot(w.alice, th.FINANCE)
    change = diff_snapshots(before, after, th.FINANCE, NOW)
    assert change is not None
    assert change.change_kinds == ["node_removed", "edge_removed"]
    assert th.agent_id("a2") in _ids(change)


async def test_more_than_fifty_ids_are_truncated_with_refetch() -> None:
    w = await make_world()
    empty = await w.source.snapshot(w.alice, th.FINANCE)
    await th.seed(w.repo, w.steward, *(th.agent_doc(f"bulk{i:03d}") for i in range(55)))
    w.clock.advance(10)
    full = await w.source.snapshot(w.alice, th.FINANCE)
    change = diff_snapshots(empty, full, th.FINANCE, NOW)
    assert change is not None
    assert len(_ids(change)) == MAX_CHANGE_IDS
    assert change.truncated is True
    assert change.refetch is True


async def test_two_scopes_never_share_a_snapshot_or_see_each_others_ids() -> None:
    w = await make_world()
    await th.seed(
        w.repo,
        w.steward,
        th.agent_doc("fin"),
        th.agent_doc("ops", th.OPERATIONS),
    )
    assert TopologySource.cache_key(w.alice, th.OPERATIONS) != TopologySource.cache_key(
        w.bob, th.OPERATIONS
    )
    alice_ops = await w.source.snapshot(w.alice, th.OPERATIONS)
    bob_ops = await w.source.snapshot(w.bob, th.OPERATIONS)  # Bob cannot read Operations
    assert set(alice_ops.nodes) == {th.agent_id("ops")}
    assert bob_ops.nodes == {}
    assert bob_ops.fingerprint != alice_ops.fingerprint
    bob_fin = await w.source.snapshot(w.bob, th.FINANCE)
    assert set(bob_fin.nodes) == {th.agent_id("fin")}
    assert w.source.cache_size == 3  # three (scope, domain) keys, three entries


async def test_one_scan_per_key_per_interval_is_shared() -> None:
    w = await make_world()
    await th.seed(w.repo, w.steward, th.agent_doc("a1"))
    await w.source.snapshot(w.alice, th.FINANCE)
    await w.source.snapshot(w.alice, th.FINANCE)
    assert w.repo.entity_scans == 1
    w.clock.advance(MapSettings().topology_poll_seconds)
    await w.source.snapshot(w.alice, th.FINANCE)
    assert w.repo.entity_scans == 2


async def test_cache_ttl_and_entry_cap_evict() -> None:
    w = await make_world(max_entries=2)
    await w.source.snapshot(w.alice, th.FINANCE)
    await w.source.snapshot(w.alice, th.OPERATIONS)
    await w.source.snapshot(w.bob, th.FINANCE)
    assert w.source.cache_size == 2  # cap: the least recently used key went

    w.clock.advance(MapSettings().topology_poll_seconds * 10 + 1)
    await w.source.snapshot(w.alice, th.FINANCE)
    assert w.source.cache_size == 1  # TTL: the stale entries were purged
