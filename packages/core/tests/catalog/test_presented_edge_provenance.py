"""PRP-43 item 4: ``present_edge`` copies the stored edge's provenance."""

from __future__ import annotations

from neurosphere_core.catalog.rules import present_edge

from .graph_helpers import NOW, NS, edge


def test_present_edge_carries_the_stored_provenance() -> None:
    stored = edge(NS, "a-b", "a", "b", "a")
    presented = present_edge(stored, [], NOW)
    assert presented.provenance == stored.provenance
    assert presented.provenance is not stored.provenance  # a copy, not an alias
    assert presented.model_dump(mode="json")["provenance"]["method"]
