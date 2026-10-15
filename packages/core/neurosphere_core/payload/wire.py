"""Event Hubs wire format shared by the ingest edge (producer) and the normalizer (consumer)."""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Annotated, Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from neurosphere_core.payload.guard import (
    DEFAULT_MAX_DEPTH,
    find_body_fields,
    raw_json_exceeds_depth,
)

CLOUDEVENT_TYPE_TELEMETRY: Final = "com.neurosphere.telemetry.v1"
CLOUDEVENT_TYPE_COST: Final = "com.neurosphere.cost.v1"
# CloudEvents extension attribute carrying request_id for cost events (CostRecord has no field).
REQUEST_ID_EXTENSION: Final = "nsrequestid"

_Id = Annotated[str, Field(min_length=1, max_length=256)]


class HubMessageKind(StrEnum):
    TELEMETRY = "telemetry"
    COST = "cost"


class HubMessage(BaseModel):
    """One telemetry or cost message on the hub. `data` is contract JSON, already redacted."""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    wire_version: Literal["1"] = "1"
    kind: HubMessageKind
    event_id: _Id  # TelemetryEvent.event_id, or CostRecord.cost_id for cost
    cloud: Literal["commercial", "government"]
    customer_id: _Id
    source_id: _Id
    producer_id: _Id
    received_at: str  # UTC ISO-8601 with Z
    request_id: str | None = None
    # Stamped by the edge from the source's producer registration, never trusted from the payload.
    observation_kind: Literal["gateway", "application", "billing"] | None = None
    dropped_field_counts: dict[str, int] = Field(default_factory=dict)
    data: dict[str, Any]

    @field_validator("data")
    @classmethod
    def _no_body_fields(cls, value: dict[str, Any]) -> dict[str, Any]:
        # Defense in depth: paths only, never values, in the error.
        if find_body_fields(value):
            raise ValueError("data contains prompt/response body fields")
        return value

    def partition_key(self) -> str:
        """Per-source ordering key."""
        return f"{self.customer_id}|{self.source_id}"

    def dedupe_key(self) -> tuple[str, str, str]:
        return (self.customer_id, self.source_id, self.event_id)

    def to_bytes(self) -> bytes:
        """Compact UTF-8 JSON."""
        return json.dumps(
            self.model_dump(mode="json"), separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")

    @classmethod
    def from_bytes(cls, raw: bytes) -> HubMessage:
        """Parse a hub message; raises ValueError (before parsing) if nested too deeply."""
        if raw_json_exceeds_depth(raw, DEFAULT_MAX_DEPTH):
            raise ValueError(f"message exceeds max JSON depth {DEFAULT_MAX_DEPTH}")
        return cls.model_validate(json.loads(raw))
