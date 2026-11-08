"""Entity documents for endpoints an inferred edge points at (PRP-10 item 8). Pure: no I/O.

Entities are built only from the canonical IDs already validated by ``mapping`` (no span
attribute is copied). They are created as ``draft`` with ``attributes.discovered_from =
"telemetry"`` so a steward can tell them from declared or curated entities, and so nothing
claims they were reviewed.
"""

from __future__ import annotations

from typing import Any, Final

from neurosphere_contracts.catalog.v1.agent import Agent
from neurosphere_contracts.catalog.v1.model_deployment import ModelDeployment
from neurosphere_contracts.catalog.v1.tool import Tool
from neurosphere_core.catalog.protocol import CatalogEntity

from neurosphere_workers.projections.catalog.mapping import EdgeCandidate

DISCOVERED_FROM: Final = "telemetry"
UNKNOWN_TOKEN: Final = "unknown"  # noqa: S105 - contract Token value, not a secret
_DISPLAY_MAX: Final = 256


def _display(ident: str) -> str:
    return ident[:_DISPLAY_MAX]


def _base(entity_id: str, candidate: EdgeCandidate, now_text: str) -> dict[str, Any]:
    entity_type = entity_id.split(":", 4)[3]
    return {
        "schema_version": "1.0.0",
        "id": entity_id,
        "entity_type": entity_type,
        "version": 1,
        "etag": "pending",  # the repository assigns the real ETag
        "lifecycle_status": "draft",
        "created_at": now_text,
        "updated_at": now_text,
        "cloud": candidate.cloud,
        "customer_id": candidate.customer_id,
        "domain_id": candidate.domain_id,
        "attributes": {"discovered_from": DISCOVERED_FROM, "discovery_rule": candidate.rule},
    }


def build_entity(entity_id: str, candidate: EdgeCandidate, now_text: str) -> CatalogEntity | None:
    """The discovered entity for ``entity_id``, or None for a type that is not discoverable."""
    _cloud, _customer, source, entity_type, ident = entity_id.split(":", 4)
    doc = _base(entity_id, candidate, now_text)
    if entity_type == "agent":
        doc.update(
            display_name=_display(ident),
            agent_kind="unknown",
            platform=UNKNOWN_TOKEN,
            source_id=source,
        )
        return Agent.model_validate(doc)
    if entity_type == "model_deployment":
        doc.update(
            provider=UNKNOWN_TOKEN,
            model_name=_display(ident),
            deployment_name=_display(ident),
        )
        return ModelDeployment.model_validate(doc)
    if entity_type == "tool":
        doc.update(
            display_name=_display(ident),
            tool_kind="unknown",
            side_effects="unknown",
            source_id=source,
        )
        return Tool.model_validate(doc)
    return None


def referenced_entity_ids(candidate: EdgeCandidate) -> tuple[str, ...]:
    """Both endpoints, source first (an edge source is always an agent)."""
    return (candidate.source_id, candidate.target_id)
