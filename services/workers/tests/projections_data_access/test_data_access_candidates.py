"""``data_access_candidates`` (PRP-73 item 2): reads/writes edges from ``data_source_refs``."""

from __future__ import annotations

from neurosphere_workers.projections.catalog import mapping
from neurosphere_workers.projections.catalog.mapping import (
    CONFIDENCE_OK,
    build_edge,
    data_access_candidates,
)

from .support import asset_id, base_doc, event_with_refs


def test_read_and_write_refs_yield_reads_and_writes_candidates() -> None:
    doc = base_doc()
    read, write = asset_id(doc, "a"), asset_id(doc, "b")
    _, item = event_with_refs([(read, "read"), (write, "write")])
    skipped: dict[str, int] = {}
    found = data_access_candidates(item, skipped)
    assert {(c.relation_type, c.target_id) for c in found} == {("reads", read), ("writes", write)}
    assert skipped == {}
    for candidate in found:
        assert candidate.rule == "data_source_ref"
        assert candidate.source_id == item.event.canonical_agent_id.root  # type: ignore[union-attr]
        assert candidate.confidence in (CONFIDENCE_OK, mapping.CONFIDENCE_FAILED)
        assert f"event:{item.doc_id}" in candidate.evidence_ids
        edge = build_edge(candidate, "2026-11-01T12:00:00Z")
        assert edge.relation_type == candidate.relation_type
        assert edge.status.root == "inferred"


def test_duplicate_refs_collapse_to_one_candidate() -> None:
    ref = asset_id(base_doc())
    _, item = event_with_refs([(ref, "read"), (ref, "read")])
    assert len(data_access_candidates(item)) == 1


def test_unknown_access_is_counted_not_inferred() -> None:
    ref = asset_id(base_doc())
    _, item = event_with_refs([(ref, "unknown")])
    skipped: dict[str, int] = {}
    assert data_access_candidates(item, skipped) == []
    assert skipped == {"unknown_access": 1}


def test_foreign_cloud_and_customer_are_counted() -> None:
    doc = base_doc()
    other_cloud = "government" if doc["cloud"] == "commercial" else "commercial"
    foreign_cloud = f"{other_cloud}:{doc['customer_id']}:synth:grounding_source:x"
    foreign_customer = f"{doc['cloud']}:othercust:synth:grounding_source:x"
    _, item = event_with_refs([(foreign_cloud, "read"), (foreign_customer, "write")])
    skipped: dict[str, int] = {}
    assert data_access_candidates(item, skipped) == []
    assert skipped == {"foreign_owner": 2}


def test_non_canonical_refs_are_counted() -> None:
    _, item = event_with_refs([("https://example.invalid/index", "read"), ("not a ref", "write")])
    skipped: dict[str, int] = {}
    assert data_access_candidates(item, skipped) == []
    assert skipped == {"not_canonical": 2}


def test_other_entity_types_including_data_asset_are_counted_wrong_type() -> None:
    doc = base_doc()
    refs = [
        (asset_id(doc, "t", kind="tool"), "read"),
        (asset_id(doc, "d", kind="data_asset"), "write"),
    ]
    _, item = event_with_refs(refs)
    skipped: dict[str, int] = {}
    assert data_access_candidates(item, skipped) == []
    assert skipped == {"wrong_type": 2}


def test_no_refs_and_no_counter_argument_are_safe() -> None:
    doc = base_doc()
    _, empty = event_with_refs([])
    assert data_access_candidates(empty) == []
    _, mixed = event_with_refs([(asset_id(doc), "unknown")])
    assert data_access_candidates(mixed) == []  # skipped=None must not raise
