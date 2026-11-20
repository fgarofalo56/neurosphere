"""Shared builders for the data-access edge tests (PRP-73 item 2)."""

from __future__ import annotations

import copy
from typing import Any

from neurosphere_contracts.catalog.v1.grounding_source import GroundingSource
from neurosphere_workers.projections.catalog import LoadedEvent
from projections.catalog_support import Doc, loaded, trace_with_delegation  # type: ignore[import-not-found]


def base_doc() -> Doc:
    """A sandbox tool_call span (it has a canonical agent and domain) with its refs cleared."""
    doc = copy.deepcopy(next(d for d in trace_with_delegation() if d["span_kind"] == "tool_call"))
    doc["data_source_refs"] = []
    return doc


def asset_id(doc: Doc, name: str = "docs-index", *, kind: str = "grounding_source") -> str:
    return f"{doc['cloud']}:{doc['customer_id']}:synth:{kind}:{name}"


def event_with_refs(refs: list[tuple[str, str]]) -> tuple[Doc, LoadedEvent]:
    doc = base_doc()
    doc["data_source_refs"] = [{"ref": ref, "access": access} for ref, access in refs]
    return doc, loaded(doc)


def asset_entity(doc: Doc, entity_id: str) -> GroundingSource:
    now: Any = "2026-11-01T12:00:00Z"
    return GroundingSource.model_validate(
        {
            "schema_version": "1.0.0",
            "id": entity_id,
            "entity_type": "grounding_source",
            "version": 1,
            "etag": "pending",
            "lifecycle_status": "active",
            "created_at": now,
            "updated_at": now,
            "cloud": doc["cloud"],
            "customer_id": doc["customer_id"],
            "domain_id": doc["domain_id"],
            "display_name": "Docs index",
            "asset_kind": "search_index",
            "source_id": "synth",
        }
    )
