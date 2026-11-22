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
from neurosphere_contracts.telemetry.v1.telemetry_event import TelemetryEvent
from neurosphere_core.catalog.protocol import CatalogEntity

from neurosphere_workers.projections.catalog.mapping import EdgeCandidate
from neurosphere_workers.projections.catalog.source import LoadedEvent

AGENT_IDENTITY_DERIVED: Final = "derived_from_external_id"
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


def agent_discovery_entity(
    item: LoadedEvent | TelemetryEvent, now_text: str
) -> CatalogEntity | None:
    """Draft ``Agent`` for the derived canonical id of a telemetry event (PRP-137 item 3).

    None unless the event carries a canonical agent id, an external agent id and a domain.
    The id is trusted as stamped by the resolver; ``Agent`` validation rejects a malformed one.
    """
    event = item.event if isinstance(item, LoadedEvent) else item
    if (
        event.canonical_agent_id is None
        or event.external_agent_id is None
        or event.domain_id is None
    ):
        return None
    entity_id = event.canonical_agent_id.root
    parts = entity_id.split(":", 4)
    if len(parts) != 5 or parts[3] != "agent":
        return None
    external = event.external_agent_id.root
    doc: dict[str, Any] = {
        "schema_version": "1.0.0",
        "id": entity_id,
        "entity_type": "agent",
        "version": 1,
        "etag": "pending",  # the repository assigns the real ETag
        "lifecycle_status": "draft",
        "created_at": now_text,
        "updated_at": now_text,
        "cloud": event.cloud,
        "customer_id": event.customer_id.root,
        "domain_id": event.domain_id.root,
        "attributes": {
            "discovered_from": DISCOVERED_FROM,
            "agent_identity": AGENT_IDENTITY_DERIVED,
        },
        "display_name": _display(external),
        "agent_kind": "unknown",
        "platform": UNKNOWN_TOKEN,
        "source_id": parts[2],
        "external_agent_id": external,
    }
    return Agent.model_validate(doc)
