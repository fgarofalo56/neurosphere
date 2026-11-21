"""``AccessEngine.dependents``: upstream impact grouped by depth with the relation path."""

from __future__ import annotations

import pytest
from catalog.graph_helpers import (  # pyright: ignore[reportMissingImports]
    NS,
    dom,
    edge,
    make_scope,
    nid,
    override_for,
    seed_chain,
)
from neurosphere_core.catalog.graph.access import AccessBudget, AccessQueryError
from neurosphere_core.catalog.repo import InMemoryCatalogRepository

from .access_helpers import SCOPE_AB, make_engine

SCOPE_A = make_scope(NS, [dom(NS, "a")])


async def _chain() -> InMemoryCatalogRepository:
    repo = InMemoryCatalogRepository()
    await seed_chain(repo, SCOPE_AB, ["n0", "n1", "n2", "n3"])
    return repo


async def test_dependents_grouped_by_depth_with_relation_path() -> None:
    repo = await _chain()
    result = await make_engine(repo).dependents(SCOPE_AB, nid("n3"), 3)
    assert [(r.accessor_id, r.depth) for r in result.rows] == [
        (nid("n2"), 1),
        (nid("n1"), 2),
        (nid("n0"), 3),
    ]
    far = result.rows[-1]
    assert far.asset_id == nid("n3")
    assert far.mode is None
    assert far.relation_path == ["invokes", "invokes", "invokes"]
    assert far.path_node_ids == [nid("n0"), nid("n1"), nid("n2"), nid("n3")]
    assert far.status in {"asserted", "inferred", "curated"}
    assert result.truncated is False
    groups = result.grouped_by_depth()
    assert list(groups) == [1, 2, 3]
    assert [r.accessor_id for r in groups[2]] == [nid("n1")]


async def test_walk_stops_at_the_depth_budget_and_says_so() -> None:
    repo = await _chain()
    result = await make_engine(repo).dependents(SCOPE_AB, nid("n3"), 1)
    assert [r.accessor_id for r in result.rows] == [nid("n2")]
    assert result.truncated is True
    assert result.truncated_reason == "max_depth"


async def test_depth_above_five_or_below_one_is_a_typed_error() -> None:
    repo = await _chain()
    engine = make_engine(repo)
    with pytest.raises(AccessQueryError) as high:
        await engine.dependents(SCOPE_AB, nid("n3"), 6)
    assert high.value.reason == "max_depth_exceeded"
    assert high.value.http_status == 422
    with pytest.raises(AccessQueryError) as low:
        await engine.dependents(SCOPE_AB, nid("n3"), 0)
    assert low.value.reason == "invalid_depth"
    ok = await engine.dependents(SCOPE_AB, nid("n3"), 5)
    assert len(ok.rows) == 3


async def test_rejected_edge_hides_the_dependent() -> None:
    repo = InMemoryCatalogRepository()
    edges = await seed_chain(repo, SCOPE_AB, ["n0", "n1", "n2"])
    await repo.put_override(SCOPE_AB, override_for(edges[1], "rej", "reject"))
    result = await make_engine(repo).dependents(SCOPE_AB, nid("n2"), 3)
    assert result.rows == []


async def test_out_of_scope_dependent_is_cut_and_not_counted() -> None:
    repo = InMemoryCatalogRepository()
    await seed_chain(repo, SCOPE_AB, ["n0"], domain="a")
    await seed_chain(repo, SCOPE_AB, ["n1"], domain="b")
    await seed_chain(repo, SCOPE_AB, ["n2"], domain="a")
    await repo.put_edge(SCOPE_AB, edge(NS, "n1-n2", "n1", "n2", "a"), None)
    await repo.put_edge(SCOPE_AB, edge(NS, "n0-n1", "n0", "n1", "a"), None)
    result = await make_engine(repo).dependents(SCOPE_A, nid("n2"), 3)
    assert result.rows == []  # n1 is in domain b, so the path to n0 is cut there
    assert nid("n1") not in result.model_dump_json()
    full = await make_engine(repo).dependents(SCOPE_AB, nid("n2"), 3)
    assert [r.accessor_id for r in full.rows] == [nid("n1"), nid("n0")]


async def test_unreadable_root_gives_an_empty_untruncated_result() -> None:
    repo = await _chain()
    scope_b = make_scope(NS, [dom(NS, "b")])
    result = await make_engine(repo).dependents(scope_b, nid("n3"), 3)
    assert result.rows == []
    assert result.truncated is False


async def test_request_budget_lowers_the_row_cap() -> None:
    repo = await _chain()
    result = await make_engine(repo).dependents(
        SCOPE_AB, nid("n3"), 3, AccessBudget(max_accessors=1)
    )
    assert len(result.rows) <= 1
    assert result.truncated is True
    assert result.truncated_reason == "max_accessors"
    assert result.bound.max_accessors == 1
    assert result.bound.max_depth == 3
