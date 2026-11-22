"""Resolver statuses, cross-tenant safety, errors and the TTL cache."""

from __future__ import annotations

import pytest
from neurosphere_core.agent_identity import AgentIdentityResolver, derive_agent_id

from .helpers import FakeClock, StubLookup

OWN = "commercial:acme:foundry:agent:real"


def _resolver(
    lookup: StubLookup, clock: FakeClock | None = None, **kw: int
) -> tuple[AgentIdentityResolver, FakeClock]:
    clock = clock or FakeClock()
    return AgentIdentityResolver(lookup, clock=clock, **kw), clock


async def _resolve(r: AgentIdentityResolver, external: str | None, canonical: str | None = None):
    return await r.resolve("commercial", "acme", "foundry", external, canonical)


async def test_declared_is_unchanged_and_skips_lookup() -> None:
    lookup = StubLookup()
    r, _ = _resolver(lookup)
    res = await _resolve(r, "ext", OWN)
    assert (res.status, res.canonical_id) == ("declared", OWN)
    assert lookup.calls == []


async def test_none_when_no_ids() -> None:
    r, _ = _resolver(StubLookup())
    res = await _resolve(r, None)
    assert (res.status, res.canonical_id) == ("none", None)
    assert (await _resolve(r, "")).status == "none"
    assert r.stats.no_agent_id == 2


async def test_alias_hit() -> None:
    r, _ = _resolver(StubLookup({"ext": OWN}))
    res = await _resolve(r, "ext")
    assert (res.status, res.canonical_id) == ("alias", OWN)


async def test_missing_alias_derives() -> None:
    r, _ = _resolver(StubLookup())
    res = await _resolve(r, "Ext One")
    assert res.status == "derived"
    assert res.canonical_id == derive_agent_id("commercial", "acme", "foundry", "Ext One")
    assert res.reason is None


@pytest.mark.parametrize(
    "target",
    [
        "government:acme:foundry:agent:real",
        "commercial:other:foundry:agent:real",
        "commercial:acme:foundry:tool:real",
        "garbage",
    ],
)
async def test_invalid_alias_target_derives_and_is_counted(target: str) -> None:
    r, _ = _resolver(StubLookup({"ext": target}))
    res = await _resolve(r, "ext")
    assert res.status == "derived"
    assert res.canonical_id != target
    assert res.reason == "alias_target_invalid"
    assert r.stats.alias_target_invalid == 1


async def test_canonical_not_owned_is_treated_as_absent() -> None:
    foreign = "commercial:other:foundry:agent:real"
    r, _ = _resolver(StubLookup({"ext": OWN}))
    res = await _resolve(r, "ext", foreign)
    assert (res.status, res.canonical_id, res.reason) == ("alias", OWN, "canonical_not_owned")
    only = await _resolve(r, None, foreign)
    assert (only.status, only.canonical_id, only.reason) == ("none", None, "canonical_not_owned")
    assert r.stats.alias_target_invalid == 2


async def test_lookup_error_propagates_and_is_counted_and_not_cached() -> None:
    lookup = StubLookup()
    lookup.error = RuntimeError("down")
    r, _ = _resolver(lookup)
    with pytest.raises(RuntimeError):
        await _resolve(r, "ext")
    assert r.stats.lookup_failures == 1
    assert r.stats.derived == 0
    lookup.error = None
    assert (await _resolve(r, "ext")).status == "derived"


async def test_positive_ttl_edges() -> None:
    lookup = StubLookup({"ext": OWN})
    r, clock = _resolver(lookup, positive_ttl_seconds=60, negative_ttl_seconds=15)
    await _resolve(r, "ext")
    clock.now += 59.9
    await _resolve(r, "ext")
    assert len(lookup.calls) == 1
    clock.now += 0.1  # exactly at expiry: refreshed
    await _resolve(r, "ext")
    assert len(lookup.calls) == 2


async def test_negative_ttl_picks_up_new_alias() -> None:
    lookup = StubLookup()
    r, clock = _resolver(lookup, positive_ttl_seconds=60, negative_ttl_seconds=15)
    assert (await _resolve(r, "ext")).status == "derived"
    lookup.values["ext"] = OWN
    clock.now += 14.9
    assert (await _resolve(r, "ext")).status == "derived"
    assert len(lookup.calls) == 1
    clock.now += 0.1
    assert (await _resolve(r, "ext")).status == "alias"
    assert len(lookup.calls) == 2


async def test_cache_is_scoped_by_cloud_and_customer() -> None:
    lookup = StubLookup({"ext": OWN})
    r, _ = _resolver(lookup)
    await r.resolve("commercial", "acme", "foundry", "ext", None)
    res = await r.resolve("commercial", "other", "foundry", "ext", None)
    assert len(lookup.calls) == 2
    assert res.status == "derived"  # OWN belongs to acme, not other


async def test_cache_is_bounded() -> None:
    lookup = StubLookup()
    r, _ = _resolver(lookup, max_entries=3)
    for i in range(10):
        await _resolve(r, f"e{i}")
    assert len(r._cache) <= 3
    await _resolve(r, "e9")  # newest kept
    assert len(lookup.calls) == 10
    await _resolve(r, "e0")  # oldest evicted
    assert len(lookup.calls) == 11


async def test_eviction_prefers_expired_entries() -> None:
    lookup = StubLookup({"keep": OWN})
    r, clock = _resolver(lookup, max_entries=2, positive_ttl_seconds=100, negative_ttl_seconds=1)
    await _resolve(r, "keep")
    await _resolve(r, "miss")
    clock.now += 2  # "miss" expired
    await _resolve(r, "new")
    n = len(lookup.calls)
    await _resolve(r, "keep")
    assert len(lookup.calls) == n  # still cached


def test_stats_snapshot_has_only_counters() -> None:
    r, _ = _resolver(StubLookup())
    snap = r.stats.snapshot()
    assert set(snap) == {
        "resolved_alias",
        "derived",
        "declared",
        "no_agent_id",
        "alias_target_invalid",
        "lookup_failures",
        "drafts_created",
        "contributions_moved",
    }
    assert all(v == 0 for v in snap.values())


async def test_stats_count_each_status() -> None:
    r, _ = _resolver(StubLookup({"a": OWN}))
    await _resolve(r, "a")
    await _resolve(r, "b")
    await _resolve(r, None)
    await _resolve(r, "c", OWN)
    snap = r.stats.snapshot()
    assert (snap["resolved_alias"], snap["derived"], snap["no_agent_id"], snap["declared"]) == (
        1,
        1,
        1,
        1,
    )
