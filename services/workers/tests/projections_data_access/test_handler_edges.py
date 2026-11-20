"""Catalog handler with data-access edges (PRP-73 item 2): idempotence, quarantine, kill switch."""

from __future__ import annotations

from neurosphere_workers.projections.catalog import mapping
from projections.catalog_support import Doc, Rig, outbox_entry  # type: ignore[import-not-found]

from .support import asset_entity, asset_id, base_doc


def _rig(refs: list[dict[str, str]]) -> tuple[Rig, Doc]:
    doc = base_doc()
    doc["data_source_refs"] = refs
    return Rig([doc], [doc["domain_id"]]), doc


async def _edges(rig: Rig, relation: str) -> list[str]:
    scope = await rig.worker_scope()
    found = [await rig.inner.get_edge(scope, i) for i in dict.fromkeys(rig.repo.put_ids)]
    return [e.id for e in found if e is not None and e.relation_type == relation]


async def _seed_asset(rig: Rig, doc: Doc, entity_id: str) -> None:
    await rig.inner.create_entity(await rig.worker_scope(), asset_entity(doc, entity_id))


async def test_resolved_asset_gets_edges_and_replay_is_idempotent() -> None:
    doc = base_doc()
    read, write = asset_id(doc, "a"), asset_id(doc, "b")
    rig, doc = _rig([{"ref": read, "access": "read"}, {"ref": write, "access": "write"}])
    await _seed_asset(rig, doc, read)
    await _seed_asset(rig, doc, write)
    await rig.fill_outbox()
    await rig.drain()
    assert len(await _edges(rig, "reads")) == 1
    assert len(await _edges(rig, "writes")) == 1
    scope = await rig.worker_scope()
    edge = await rig.inner.get_edge(scope, (await _edges(rig, "reads"))[0])
    assert edge is not None
    assert edge.target_id == read

    # The same event projected again: still one edge each, nothing rewritten.
    written = rig.projection.stats.edges_written
    for item in rig.items:
        await rig.projection.handle(outbox_entry(item))
    assert rig.projection.stats.edges_written == written
    assert len(set(await _edges(rig, "reads"))) == 1
    assert len(set(await _edges(rig, "writes"))) == 1


async def test_unresolved_asset_is_quarantined_and_never_created() -> None:
    doc = base_doc()
    ref = asset_id(doc, "ghost")
    rig, _ = _rig([{"ref": ref, "access": "read"}])
    await rig.fill_outbox()
    await rig.drain()
    assert await _edges(rig, "reads") == []
    assert await rig.inner.get_entity(await rig.worker_scope(), ref) is None
    assert rig.projection.stats.skipped_unresolved_asset == 1
    records = list(rig.projection.quarantine.records.values())  # type: ignore[attr-defined]
    assert [r.reason for r in records] == ["asset_unresolved"]


async def test_skip_counters_surface_on_stats() -> None:
    doc = base_doc()
    rig, _ = _rig(
        [
            {"ref": asset_id(doc, "u"), "access": "unknown"},
            {"ref": "nope", "access": "read"},
            {"ref": asset_id(doc, "d", kind="data_asset"), "access": "read"},
            {"ref": f"{doc['cloud']}:othercust:synth:grounding_source:x", "access": "read"},
        ]
    )
    await rig.fill_outbox()
    await rig.drain()
    assert rig.projection.stats.data_access_skipped == {
        "unknown_access": 1,
        "not_canonical": 1,
        "wrong_type": 1,
        "foreign_owner": 1,
    }


async def test_kill_switch_silences_the_rule(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    doc = base_doc()
    ref = asset_id(doc)
    monkeypatch.setenv("NS_WORKER_CATALOG_DATA_ACCESS_EDGES", "false")
    rig, doc = _rig([{"ref": ref, "access": "read"}, {"ref": "x", "access": "unknown"}])
    await _seed_asset(rig, doc, ref)
    await rig.fill_outbox()
    await rig.drain()
    assert await _edges(rig, "reads") == []
    assert rig.projection.stats.data_access_skipped == {}
    assert mapping.DATA_SOURCE_RULE not in rig.projection.stats.by_rule
