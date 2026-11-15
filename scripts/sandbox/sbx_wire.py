"""Wrap generated documents in the ingestion envelope (HubMessage); shared by seed and replay.

The worker validates every Event Hubs body as a ``HubMessage`` (``extra="forbid"``) before it looks
at ``data``, so a raw generator line is always ``invalid_wire`` (#162). ``sbx_seed_stack.hub_lines``
and ``sbx_cli.publish_events`` both build their messages here so the two cannot drift.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from neurosphere_core.payload import HubMessage, HubMessageKind

PRODUCER_ID = "sbx-seed-stack"
_REQUIRED = ("event_id", "cloud", "customer_id", "source_id")


def received_stamp(now: datetime | None = None) -> str:
    """Millisecond UTC ``received_at`` the envelope carries."""
    return (now or datetime.now(UTC)).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def envelope(
    doc: dict[str, Any],
    *,
    kind: str,
    event_id: str,
    received_at: str,
    producer_id: str = PRODUCER_ID,
) -> bytes:
    """One document as ``HubMessage`` bytes (telemetry is a gateway observation, cost billing)."""
    telemetry = kind == "telemetry"
    return HubMessage(
        kind=HubMessageKind(kind),
        event_id=event_id,
        cloud=doc["cloud"],
        customer_id=doc["customer_id"],
        source_id=doc["source_id"],
        producer_id=producer_id,
        received_at=received_at,
        request_id=doc.get("request_id"),
        observation_kind="gateway" if telemetry else "billing",
        data=doc,
    ).to_bytes()


def wrap_telemetry_line(line: bytes, received_at: str) -> bytes:
    """Wrap one raw telemetry line; a line that is not a JSON object with the envelope's
    identifying fields stays raw, so genuinely unparseable input is still quarantined as
    ``invalid_wire`` and the bad-event manifest keeps its meaning."""
    try:
        doc = json.loads(line)
    except ValueError:
        return line
    if not isinstance(doc, dict) or not all(isinstance(doc.get(k), str) for k in _REQUIRED):
        return line
    try:
        return envelope(doc, kind="telemetry", event_id=doc["event_id"], received_at=received_at)
    except ValueError:  # pydantic ValidationError is a ValueError: e.g. an unknown cloud value
        return line
