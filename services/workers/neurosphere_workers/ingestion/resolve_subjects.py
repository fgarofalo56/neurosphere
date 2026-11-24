"""Canonical tool and service ids for telemetry events (PRP-100). Pure: no I/O, no catalog lookup.

A producer-supplied canonical id is used only when it is owned (same cloud and server-derived
customer, right type segment). Otherwise the id is derived from the external id with NO slugging
and NO hash suffix: a URL, query string or credential must never become an id, so anything outside
``[a-z0-9._/=-]`` resolves to ``None``.
"""

from __future__ import annotations

import re
from typing import Final

from neurosphere_contracts.telemetry.v1.telemetry_event import TelemetryEvent
from neurosphere_core.agent_identity.keys import slug

__all__ = ["canonical_service_id", "canonical_tool_id"]

_CANONICAL: Final = re.compile(
    r"(commercial|government):[a-z0-9._-]+:[a-z0-9._-]+:[a-z0-9._-]+:[a-z0-9._/=-]+"
)
_SEGMENT: Final = re.compile(r"[a-z0-9._-]+")
_EXTERNAL: Final = re.compile(r"[a-z0-9._/=-]+")
_MAX_ID: Final = 512


def _owned(value: str | None, event: TelemetryEvent, customer_id: str, type_: str) -> bool:
    if value is None or len(value) > _MAX_ID or not _CANONICAL.fullmatch(value):
        return False
    cloud, customer, _source, kind, _ident = value.split(":", 4)
    return cloud == event.cloud and customer == customer_id and kind == type_


def _derive(
    event: TelemetryEvent, customer_id: str, type_: str, external: str | None
) -> str | None:
    if external is None or not _SEGMENT.fullmatch(customer_id):
        return None
    ident = external.lower()
    if not _EXTERNAL.fullmatch(ident):
        return None
    source = slug(event.source_id.root, "trace")
    result = f"{event.cloud}:{customer_id}:{source}:{type_}:{ident}"
    return result if len(result) <= _MAX_ID and _CANONICAL.fullmatch(result) else None


def canonical_tool_id(event: TelemetryEvent, customer_id: str) -> str | None:
    """Owned producer id, else ``<cloud>:<customer>:<source>:tool:<external id>``, else ``None``."""
    tool = event.tool
    if tool is None:
        return None
    produced = tool.canonical_tool_id.root if tool.canonical_tool_id is not None else None
    if _owned(produced, event, customer_id, "tool"):
        return produced
    external = (
        tool.external_tool_id.root
        if tool.external_tool_id is not None
        else (tool.tool_name.root if tool.tool_name is not None else None)
    )
    return _derive(event, customer_id, "tool", external)


def canonical_service_id(event: TelemetryEvent, customer_id: str) -> str | None:
    """Owned producer id, else ``<cloud>:<customer>:<source>:service:<external id>``, else None."""
    service = event.service
    if service is None:
        return None
    produced = service.canonical_service_id.root if service.canonical_service_id else None
    if _owned(produced, event, customer_id, "service"):
        return produced
    external = service.external_service_id.root if service.external_service_id else None
    return _derive(event, customer_id, "service", external)
