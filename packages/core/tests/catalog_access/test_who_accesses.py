"""``AccessEngine.who_accesses``: scope, presented edges, hidden edges, modes."""

from __future__ import annotations

import pytest
from catalog.graph_helpers import NS  # pyright: ignore[reportMissingImports]
from neurosphere_core.catalog.graph.access import AccessQuery, AccessQueryError

from .access_helpers import (
    SCOPE_A,
    SCOPE_AB,
    SCOPE_B,
    asset_id,
    build_world,
    make_engine,
    reject,
)

CUSTOMERS = asset_id("customers")


def _agent(name: str) -> str:
    return f"commercial:{NS}:foundry:agent:{name}"


async def test_writers_of_an_asset_carry_edge_facts() -> None:
    world = await build_world()
    result = await make_engine(world.repo).who_accesses(
        SCOPE_AB, AccessQuery(asset_ids=[CUSTOMERS], modes=["write"])
    )
    assert [r.accessor_id for r in result.rows] == [_agent("a1")]
    row = result.rows[0]
    assert row.mode == "write"
    assert row.relation == "writes"
    assert row.asset_id == CUSTOMERS
    assert row.status == "inferred"
    assert 0.0 <= row.confidence <= 1.0
    assert row.provenance_method
    assert row.provenance_source_id
    assert row.evidence_ids
    assert row.last_observed.endswith("Z")
    assert row.relation_path == ["writes"]
    assert row.path_node_ids == [_agent("a1"), CUSTOMERS]
    assert result.truncated is False
    assert result.truncated_reason is None
    assert result.assets_scanned == 1


async def test_both_modes_by_default_and_read_only_on_request() -> None:
    world = await build_world()
    engine = make_engine(world.repo)
    both = await engine.who_accesses(SCOPE_AB, AccessQuery(asset_ids=[CUSTOMERS]))
    assert {(r.accessor_id, r.mode) for r in both.rows} == {
        (_agent("a1"), "write"),
        (_agent("a2"), "read"),
        (_agent("b1"), "read"),
    }
    reads = await engine.who_accesses(SCOPE_AB, AccessQuery(asset_ids=[CUSTOMERS], modes=["read"]))
    assert {r.accessor_id for r in reads.rows} == {_agent("a2"), _agent("b1")}


async def test_accessor_outside_scope_never_appears_or_counts() -> None:
    world = await build_world()
    engine = make_engine(world.repo)
    result = await engine.who_accesses(SCOPE_A, AccessQuery(asset_ids=[CUSTOMERS]))
    # b1 reads customers through an edge stored in domain a, but b1 itself is in domain b.
    assert {r.accessor_id for r in result.rows} == {_agent("a1"), _agent("a2")}
    assert len(result.rows) == 2
    assert _agent("b1") not in result.model_dump_json()
    assert result.truncated is False


async def test_assets_outside_scope_are_not_scanned() -> None:
    world = await build_world()
    engine = make_engine(world.repo)
    scoped = await engine.who_accesses(SCOPE_A, AccessQuery())
    assert scoped.assets_scanned == 4  # customers, claims, mystery, public (domain a only)
    assert asset_id("ledger") not in scoped.model_dump_json()
    other = await engine.who_accesses(SCOPE_B, AccessQuery(asset_ids=[CUSTOMERS]))
    assert other.rows == []
    assert other.assets_scanned == 0
    assert other.assets == []


async def test_hidden_rejected_edge_is_omitted() -> None:
    world = await build_world()
    await world.repo.put_override(SCOPE_AB, reject(world.edges["w-a1-customers"], "rej-1"))
    result = await make_engine(world.repo).who_accesses(
        SCOPE_AB, AccessQuery(asset_ids=[CUSTOMERS], modes=["write"])
    )
    assert result.rows == []


async def test_asset_filter_by_domain_ids() -> None:
    world = await build_world()
    result = await make_engine(world.repo).who_accesses(
        SCOPE_AB, AccessQuery(domain_ids=[f"commercial:{NS}:neurosphere:domain:b"])
    )
    assert [a.id for a in result.assets] == [asset_id("ledger")]
    assert [r.accessor_id for r in result.rows] == [_agent("b2")]


async def test_too_many_asset_ids_is_a_typed_error() -> None:
    world = await build_world()
    ids = [asset_id(f"x{i}") for i in range(51)]
    with pytest.raises(AccessQueryError) as caught:
        await make_engine(world.repo).who_accesses(SCOPE_AB, AccessQuery(asset_ids=ids))
    assert caught.value.reason == "too_many_assets"
    assert caught.value.http_status == 422
    fifty = await make_engine(world.repo).who_accesses(SCOPE_AB, AccessQuery(asset_ids=ids[:50]))
    assert fifty.rows == []


async def test_non_asset_ids_are_ignored() -> None:
    world = await build_world()
    result = await make_engine(world.repo).who_accesses(
        SCOPE_AB, AccessQuery(asset_ids=[_agent("a1")])
    )
    assert result.rows == []
    assert result.assets == []
