"""Catalog projection entity discovery + candidate quarantine (PRP-10 item 8)."""

from __future__ import annotations

import pytest
from neurosphere_contracts.query.v1.budget import Budget
from neurosphere_core.catalog import EntityFilter, NeighborsRequest
from neurosphere_core.catalog.graph import RepositoryGraphQuery
from neurosphere_core.errors import InvalidSchemaError
from neurosphere_core.paging import PageRequest
from neurosphere_workers.projections.catalog import InMemoryCandidateQuarantine

from .catalog_support import Doc, Rig, domains_of, outbox_entry, trace_with_delegation


@pytest.fixture
def docs() -> list[Doc]:
    return trace_with_delegation()


@pytest.fixture
def rig(docs: list[Doc]) -> Rig:
    return Rig(docs, domains_of(docs))


class _NoSearch:
    async def search(self, *_args: object, **_kwargs: object) -> object:
        raise NotImplementedError


async def _all_entities(rig: Rig) -> dict[str, object]:
    scope = await rig.worker_scope()
    page = await rig.inner.list_entities(scope, EntityFilter(), PageRequest(page_size=200))
    return {e.id: e for e in page.items}


async def test_empty_repository_gets_entities_and_edges_visible_to_in_scope_caller(
    rig: Rig,
) -> None:
    await rig.fill_outbox()
    result = await rig.drain()
    assert result.ok

    entities = await _all_entities(rig)
    types = {eid.split(":")[3] for eid in entities}
    assert {"agent", "model_deployment", "tool"} <= types
    assert sum(1 for eid in entities if eid.split(":")[3] == "agent") >= 2  # parent + child

    for entity in entities.values():
        assert entity.lifecycle_status.root == "draft"  # type: ignore[attr-defined]
        attrs = entity.attributes.root  # type: ignore[attr-defined]
        assert attrs["discovered_from"] == "telemetry"

    scope = await rig.worker_scope()
    query = RepositoryGraphQuery(rig.inner, _NoSearch())  # type: ignore[arg-type]
    budget = Budget.model_validate({"timeout_ms": 5000, "limit": 100, "max_depth": 3})
    seen_relations: set[tuple[str, str]] = set()
    for edge_id in dict.fromkeys(rig.repo.put_ids):
        edge = await rig.inner.get_edge(scope, edge_id)
        assert edge is not None
        got = await query.neighbors(
            scope, NeighborsRequest(node_id=edge.source_id, direction="out", budget=budget)
        )
        node_ids = {n.id for n in got.nodes}
        assert edge.target_id in node_ids, "edge target must be a visible node"
        assert any(p.edge_id == edge_id for p in got.edges)
        seen_relations.add((edge.relation_type, edge.target_id.split(":")[3]))
    assert ("uses_model", "model_deployment") in seen_relations
    assert ("invokes", "tool") in seen_relations
    assert ("invokes", "agent") in seen_relations


async def test_replay_creates_no_duplicates_and_changes_nothing(rig: Rig) -> None:
    await rig.fill_outbox()
    await rig.drain()
    scope = await rig.worker_scope()
    before = await _all_entities(rig)
    created = rig.projection.stats.entities_created
    assert created == len(before)
    puts = rig.repo.puts

    for item in rig.items:
        await rig.projection.handle(outbox_entry(item))
    after = await _all_entities(rig)
    assert after.keys() == before.keys()
    for eid, entity in before.items():
        assert after[eid] == entity  # version and etag untouched
        assert (await rig.inner.get_entity(scope, eid)) == entity
    assert rig.projection.stats.entities_created == created
    assert rig.repo.puts == puts


async def test_preexisting_declared_entity_is_not_modified(rig: Rig) -> None:
    probe = Rig(rig.docs, rig.domains)
    await probe.fill_outbox()
    await probe.drain()
    scope = await probe.worker_scope()
    target_id = next(iter(sorted(await _all_entities(probe))))
    declared = await probe.inner.get_entity(scope, target_id)
    assert declared is not None

    fresh = Rig(rig.docs, rig.domains)
    seeded = declared.model_copy(
        update={"lifecycle_status": declared.lifecycle_status.model_copy(update={"root": "active"})}
    )
    # seed through the repository under its own scope: a declared, active entity
    fresh_scope = await fresh.worker_scope()
    stored = await fresh.inner.create_entity(fresh_scope, seeded)
    await fresh.fill_outbox()
    result = await fresh.drain()
    assert result.ok
    now = await fresh.inner.get_entity(fresh_scope, target_id)
    assert now == stored
    assert now is not None
    assert now.lifecycle_status.root == "active"
    assert now.version.root == 1


async def test_out_of_scope_candidate_is_quarantined_and_counted(docs: list[Doc]) -> None:
    other = ["commercial:synthco:sandbox:domain:not-in-this-trace"]
    rig = Rig(docs, other)
    await rig.fill_outbox()
    result = await rig.drain()
    assert result.ok and result.delivered == len(docs)  # checkpoint advanced after quarantine
    quarantine = rig.projection.quarantine
    assert isinstance(quarantine, InMemoryCandidateQuarantine)
    assert rig.projection.stats.skipped_out_of_scope > 0
    assert quarantine.records
    for record in quarantine.records.values():
        assert record.reason == "out_of_scope"
        assert record.outbox_entry_id is not None
    assert rig.repo.puts == 0
    assert rig.projection.stats.entities_created == 0


async def test_checkpoint_holds_when_quarantine_write_fails(docs: list[Doc]) -> None:
    class Failing:
        async def write(self, record: object) -> None:
            raise InvalidSchemaError("injected quarantine outage")

    rig = Rig(docs, ["commercial:synthco:sandbox:domain:not-in-this-trace"])
    rig.projection.quarantine = Failing()  # type: ignore[assignment]
    await rig.fill_outbox()
    result = await rig.drain()
    assert not result.ok
    assert rig.projection.stats.skipped_out_of_scope == 0
