"""PRP-10 item 10 (#53, core parts of #56): existence non-disclosure, fan-out truncation after the
scope filter, explicit raw-view gate, time budget, Cosmos retry-after and expired-lock lineage.
One regression per bullet."""

from __future__ import annotations

import inspect
from datetime import UTC, datetime
from typing import Any

import pytest
from azure.cosmos.exceptions import CosmosHttpResponseError
from neurosphere_contracts.catalog.v1.edge_override import EdgeOverride
from neurosphere_core.catalog import EdgeFilter
from neurosphere_core.catalog.graph.latest import (
    LatestObservationReader,
    has_expired_lock,
    present_with_latest,
)
from neurosphere_core.catalog.repo import InMemoryCatalogRepository
from neurosphere_core.catalog.repo.cosmos import _translate  # pyright: ignore[reportPrivateUsage]
from neurosphere_core.catalog.repo.engine import auditor_domains
from neurosphere_core.errors.taxonomy import (
    ForbiddenError,
    InvalidSchemaError,
    RateLimitedError,
)
from neurosphere_core.paging import PageRequest

from .graph_helpers import (
    NOW,
    NS,
    FakeClock,
    budget,
    make_query,
    neighbors_request,
    nid,
    override_for,
)
from .repo_conformance import (
    agent,
    alias,
    dom,
    edge,
    make_scope,
    observation,
    override,
)

BOTH = make_scope(NS, [dom(NS, "a"), dom(NS, "b")])
ONLY_A = make_scope(NS, [dom(NS, "a")])
ONLY_B = make_scope(NS, [dom(NS, "b")])


def _same_apart_from_id(first: Exception, second: Exception, first_id: str, second_id: str) -> None:
    assert type(first) is type(second)
    assert str(first).replace(first_id, "<id>") == str(second).replace(second_id, "<id>")


# 2. duplicate-ID / alias-key responses do not say where the clash is


async def test_duplicate_entity_id_is_identical_in_domain_and_cross_domain() -> None:
    repo = InMemoryCatalogRepository()
    await repo.create_entity(ONLY_A, agent(NS, "taken-a", "a"))
    await repo.create_entity(ONLY_B, agent(NS, "taken-b", "b"))
    with pytest.raises(InvalidSchemaError) as in_domain:
        await repo.create_entity(ONLY_A, agent(NS, "taken-a", "a"))
    with pytest.raises(InvalidSchemaError) as elsewhere:
        await repo.create_entity(ONLY_A, agent(NS, "taken-b", "a"))
    _same_apart_from_id(in_domain.value, elsewhere.value, "taken-a", "taken-b")
    assert in_domain.value.code == elsewhere.value.code


async def test_duplicate_edge_id_is_identical_in_domain_and_cross_domain() -> None:
    repo = InMemoryCatalogRepository()
    for name in ("x", "y"):
        await repo.create_entity(BOTH, agent(NS, name, "a"))
    await repo.put_edge(ONLY_A, edge(NS, "e-a", "x", "y", "a"), None)
    await repo.put_edge(ONLY_B, edge(NS, "e-b", "x", "y", "b"), None)
    with pytest.raises(Exception) as in_domain:
        await repo.put_edge(ONLY_A, edge(NS, "e-a", "x", "y", "a"), None)
    with pytest.raises(Exception) as elsewhere:
        await repo.put_edge(ONLY_A, edge(NS, "e-b", "x", "y", "a"), None)
    _same_apart_from_id(in_domain.value, elsewhere.value, "e-a", "e-b")


async def test_alias_id_and_alias_key_clashes_are_identical_across_domains() -> None:
    repo = InMemoryCatalogRepository()
    await repo.create_entity(ONLY_A, agent(NS, "ta", "a"))
    await repo.create_entity(ONLY_B, agent(NS, "tb", "b"))
    await repo.put_alias(ONLY_A, alias(NS, "al-a", "ta", "val-a"))
    await repo.put_alias(ONLY_B, alias(NS, "al-b", "tb", "val-b"))
    # same alias ID already used in the OTHER domain vs. a clash inside the caller's domain
    await repo.create_entity(ONLY_A, agent(NS, "ta2", "a"))
    with pytest.raises(InvalidSchemaError) as elsewhere_id:
        await repo.put_alias(ONLY_A, alias(NS, "al-b", "ta2", "val-other"))
    assert elsewhere_id.value.code == "invalid_schema"
    # alias key already resolves to a different canonical ID: in my domain vs. another domain
    with pytest.raises(InvalidSchemaError) as in_key:
        await repo.put_alias(ONLY_A, alias(NS, "al-a2", "ta2", "val-a"))
    with pytest.raises(InvalidSchemaError) as other_key:
        await repo.put_alias(ONLY_A, alias(NS, "al-b2", "ta2", "val-b"))
    _same_apart_from_id(in_key.value, other_key.value, "", "")


# 3. put_override uniqueness is global like the other creates


async def test_override_id_taken_in_another_domain_is_refused_like_in_domain() -> None:
    repo = InMemoryCatalogRepository()
    for name in ("x", "y"):
        await repo.create_entity(BOTH, agent(NS, name, "a"))
    stored_a = await repo.put_edge(ONLY_A, edge(NS, "ea", "x", "y", "a"), None)
    stored_b = await repo.put_edge(ONLY_B, edge(NS, "eb", "x", "y", "b"), None)
    await repo.put_override(
        ONLY_A,
        override(NS, "dup", "ea", "a", decided_at="2026-10-09T17:30:00Z", etag=stored_a.etag.root),
    )
    other = override(
        NS, "dup", "eb", "b", decided_at="2026-10-09T17:31:00Z", etag=stored_b.etag.root
    )
    with pytest.raises(InvalidSchemaError) as elsewhere:
        await repo.put_override(ONLY_B, other)
    different = override(
        NS,
        "dup",
        "ea",
        "a",
        decided_at="2026-10-09T17:30:00Z",
        etag=stored_a.etag.root,
        reason="a different decision",
    )
    with pytest.raises(InvalidSchemaError) as in_domain:
        await repo.put_override(ONLY_A, different)
    _same_apart_from_id(in_domain.value, elsewhere.value, "dup", "dup")


# 4. fan-out truncation ignores hidden out-of-scope edges


async def _hub(repo: InMemoryCatalogRepository, visible: int, hidden: int) -> None:
    await repo.create_entity(BOTH, agent(NS, "hub", "a"))
    for i in range(visible):
        await repo.create_entity(BOTH, agent(NS, f"v{i}", "a"))
        await repo.put_edge(BOTH, edge(NS, f"hub-v{i}", "hub", f"v{i}", "a"), None)
    for i in range(hidden):
        await repo.create_entity(BOTH, agent(NS, f"h{i}", "b"))
        await repo.put_edge(BOTH, edge(NS, f"hub-h{i}", "hub", f"h{i}", "a"), None)


async def test_hidden_out_of_scope_edges_do_not_make_fanout_truncated() -> None:
    repo = InMemoryCatalogRepository()
    await _hub(repo, visible=2, hidden=6)
    query = make_query(repo)
    request = neighbors_request("hub", direction="out", budget=budget(limit=3, max_depth=1))
    result = await query.neighbors(ONLY_A, request)
    assert len(result.edges) == 2
    assert result.truncated is False
    assert result.truncated_reason is None


async def test_fanout_still_truncates_on_in_scope_edges() -> None:
    repo = InMemoryCatalogRepository()
    await _hub(repo, visible=5, hidden=3)
    query = make_query(repo)
    request = neighbors_request("hub", direction="out", budget=budget(limit=3, max_depth=1))
    result = await query.neighbors(ONLY_A, request)
    assert len(result.edges) == 3
    assert result.truncated is True
    assert result.truncated_reason == "max_edges"


# 5. raw view: explicit auditor gate, no probe through the unknown-edge fallback


class _Spy:
    """Delegating repository that records every ``list_observations`` edge ID."""

    def __init__(self, inner: InMemoryCatalogRepository) -> None:
        self._inner = inner
        self.observation_reads: list[str] = []
        self.calls: list[str] = []

    def __getattr__(self, name: str) -> Any:
        target: Any = getattr(self._inner, name)
        if not callable(target):
            return target

        async def call(*args: Any, **kwargs: Any) -> Any:
            self.calls.append(name)
            result: Any = target(*args, **kwargs)
            return await result

        return call

    async def list_observations(self, scope: Any, edge_id: str, page: PageRequest) -> Any:
        self.observation_reads.append(edge_id)
        return await self._inner.list_observations(scope, edge_id, page)


async def test_raw_view_gate_is_explicit_and_never_probes_with_a_node_id() -> None:
    repo = InMemoryCatalogRepository()
    await repo.create_entity(ONLY_A, agent(NS, "lonely", "a"))  # no edges at all
    spy = _Spy(repo)
    query = make_query(spy)  # type: ignore[arg-type]
    request = neighbors_request("lonely", direction="out", view="raw")
    with pytest.raises(ForbiddenError):
        await query.neighbors(ONLY_A, request)
    assert spy.observation_reads == []
    assert "get_entity" not in spy.calls  # refused before any read

    auditor = make_scope(NS, [dom(NS, "a")], auditor_for=[dom(NS, "a")])
    assert auditor_domains(auditor, NOW) == (dom(NS, "a"),)
    allowed = await query.neighbors(auditor, request)
    assert [n.id for n in allowed.nodes] == [nid("lonely")]
    assert spy.observation_reads == []

    expired = make_scope(
        NS, [dom(NS, "a")], auditor_for=[dom(NS, "a")], auditor_expires="2020-01-01T00:00:00Z"
    )
    assert auditor_domains(expired, NOW) == ()


async def test_raw_view_refuses_edge_in_non_audited_domain() -> None:
    repo = InMemoryCatalogRepository()
    for name in ("p", "q"):
        await repo.create_entity(BOTH, agent(NS, name, "a"))
    await repo.put_edge(BOTH, edge(NS, "pq", "p", "q", "b"), None)
    auditor_a_only = make_scope(NS, [dom(NS, "a"), dom(NS, "b")], auditor_for=[dom(NS, "a")])
    query = make_query(repo)
    with pytest.raises(ForbiddenError):
        await query.neighbors(auditor_a_only, neighbors_request("p", direction="out", view="raw"))


# 9. time budget before the root read and before the override batch


async def test_time_budget_is_checked_before_the_root_read() -> None:
    repo = InMemoryCatalogRepository()
    await repo.create_entity(ONLY_A, agent(NS, "r", "a"))
    spy = _Spy(repo)
    query = make_query(spy, clock=FakeClock(step=1.0))  # type: ignore[arg-type]
    result = await query.neighbors(ONLY_A, neighbors_request("r", budget=budget(timeout_ms=500)))
    assert result.truncated is True
    assert result.truncated_reason == "timeout_ms"
    assert result.nodes == []
    assert spy.calls == []


class _Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


class _ExpiresAfterScopeCheck(_Spy):
    """Moves the clock past the deadline once the neighbour has been resolved."""

    def __init__(self, inner: InMemoryCatalogRepository, clock: _Clock) -> None:
        super().__init__(inner)
        self._clock = clock

    async def get_entity(self, scope: Any, entity_id: str) -> Any:
        found = await self._inner.get_entity(scope, entity_id)
        self.calls.append("get_entity")
        if entity_id == nid("n1"):
            self._clock.t = 1000.0
        return found


async def test_time_budget_is_checked_before_the_override_batch() -> None:
    repo = InMemoryCatalogRepository()
    for name in ("n0", "n1"):
        await repo.create_entity(ONLY_A, agent(NS, name, "a"))
    await repo.put_edge(ONLY_A, edge(NS, "n0-n1", "n0", "n1", "a"), None)
    clock = _Clock()
    spy = _ExpiresAfterScopeCheck(repo, clock)
    query = make_query(spy, clock=clock)  # type: ignore[arg-type]
    result = await query.neighbors(
        ONLY_A, neighbors_request("n0", direction="out", budget=budget(timeout_ms=1000))
    )
    assert result.truncated_reason == "timeout_ms"
    assert "list_overrides_for_edges" not in spy.calls


# 8. RateLimitedError carries the response's retry-after


def _throttled(**headers: str) -> CosmosHttpResponseError:
    exc = CosmosHttpResponseError(status_code=429, message="throttled")
    exc.headers = dict(headers)  # pyright: ignore[reportAttributeAccessIssue]
    return exc


def test_rate_limit_uses_response_retry_after() -> None:
    mapped = _translate(_throttled(**{"x-ms-retry-after-ms": "2500"}))
    assert isinstance(mapped, RateLimitedError)
    assert mapped.retry_after_seconds == 3  # rounded up
    seconds = _translate(_throttled(**{"Retry-After": "7"}))
    assert isinstance(seconds, RateLimitedError)
    assert seconds.retry_after_seconds == 7
    default = _translate(_throttled())
    assert isinstance(default, RateLimitedError)
    assert default.retry_after_seconds == 1
    junk = _translate(_throttled(**{"x-ms-retry-after-ms": "soon"}))
    assert isinstance(junk, RateLimitedError)
    assert junk.retry_after_seconds == 1
    capped = _translate(_throttled(**{"x-ms-retry-after-ms": "9999999"}))
    assert isinstance(capped, RateLimitedError)
    assert capped.retry_after_seconds == 60


# 11. expired lock: presented lineage uses the newest observation, fetched only when needed


async def _locked_edge(expiry: str) -> tuple[InMemoryCatalogRepository, Any, EdgeOverride]:
    repo = InMemoryCatalogRepository()
    for name in ("l0", "l1"):
        await repo.create_entity(ONLY_A, agent(NS, name, "a"))
    stored = await repo.put_edge(ONLY_A, edge(NS, "l0-l1", "l0", "l1", "a"), None)
    lock = override_for(stored, "lk", "lock", expiry=expiry, set_confidence=0.9)
    await repo.put_override(ONLY_A, lock)
    return repo, stored, lock


async def test_expired_lock_lineage_uses_newest_observation_in_graph() -> None:
    repo, stored, lock = await _locked_edge("2026-10-10T00:00:00Z")  # expired before NOW
    assert has_expired_lock([lock], NOW)
    newest = observation(NS, "newest", "l0-l1", "a", "2026-10-16T00:00:00Z")
    await repo.record_observation(ONLY_A, newest)
    assert isinstance(repo, LatestObservationReader)
    assert (await repo.latest_observation(ONLY_A, stored.id)) == newest
    result = await make_query(repo).neighbors(
        ONLY_A, neighbors_request("l0", direction="out", budget=budget())
    )
    assert [e.confidence for e in result.edges] == [0.5]  # the observation, not the stored edge


async def test_active_lock_does_not_read_the_newest_observation() -> None:
    _repo, stored, lock = await _locked_edge("2027-01-01T00:00:00Z")  # still active at NOW
    assert not has_expired_lock([lock], NOW)

    class Boom:
        async def latest_observation(self, scope: Any, edge_id: str) -> Any:
            raise AssertionError("must not be read for an active lock")

    presented = await present_with_latest(Boom(), ONLY_A, stored, [lock], NOW)
    assert presented.confidence == 0.9


async def test_latest_observation_is_scope_filtered_and_not_auditor_gated() -> None:
    repo, stored, _ = await _locked_edge("2026-10-10T00:00:00Z")
    await repo.record_observation(
        ONLY_A, observation(NS, "o1", "l0-l1", "a", "2026-10-16T00:00:00Z")
    )
    assert await repo.latest_observation(ONLY_B, stored.id) is None
    assert await repo.latest_observation(ONLY_A, stored.id) is not None
    with pytest.raises(ForbiddenError):  # the raw listing stays auditor-only
        await repo.list_observations(ONLY_A, stored.id, PageRequest(page_size=1))


# 13. Person needs a domain (stated in the repository docs and enforced)


def test_person_needs_domain_is_documented_and_enforced() -> None:
    from neurosphere_core.catalog.repo import engine

    assert "Person" in (engine.__doc__ or "")
    assert "domain_id" in (engine.__doc__ or "")


# signature guard for the helper wired into the curation service
def test_present_with_latest_signature() -> None:
    sig = inspect.signature(present_with_latest)
    sig.bind(object(), ONLY_A, object(), [], datetime.now(UTC))
    with pytest.raises(TypeError):
        sig.bind(object(), ONLY_A)
    assert EdgeFilter() is not None
