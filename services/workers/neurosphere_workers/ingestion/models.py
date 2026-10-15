"""Pipeline models (Pydantic v2, frozen, extra forbidden)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from neurosphere_contracts.cost.v1.cost_record import CostRecord
from neurosphere_contracts.telemetry.v1.telemetry_event import TelemetryEvent
from neurosphere_core.payload import HubMessage, HubMessageKind, find_body_fields
from pydantic import BaseModel, ConfigDict, Field, model_validator

from neurosphere_workers.ingestion.reasons import QuarantineReason
from neurosphere_workers.runtime import BatchOutcome


def compute_doc_id(customer_id: str, source_id: str, event_id: str) -> str:
    """Deterministic document id: sha256 of ``customer_id|source_id|event_id`` (hex)."""
    return hashlib.sha256(f"{customer_id}|{source_id}|{event_id}".encode()).hexdigest()


def parse_timestamp(value: str) -> datetime:
    """Parse a contract RFC 3339 UTC timestamp (``...Z``, optional fraction, leap second)."""
    text = value.strip()
    leap = len(text) >= 19 and text[17:19] == "60"
    if leap:
        text = f"{text[:17]}59{text[19:]}"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        raise ValueError("timestamp has no timezone")
    parsed = parsed.astimezone(UTC)
    return parsed + timedelta(seconds=1) if leap else parsed


def format_timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class EventKey:
    """Dedupe identity (PRP-07 C6): ``event_id`` within ``source_id`` within ``customer_id``."""

    customer_id: str
    source_id: str
    event_id: str

    @property
    def doc_id(self) -> str:
        return compute_doc_id(self.customer_id, self.source_id, self.event_id)


class RawMessage(BaseModel):
    """One Event Hubs record as the pipeline sees it (SDK types stop at ``consumer.py``)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    body: bytes
    partition_id: str
    offset: str
    sequence_number: int
    enqueued_time: datetime

    @property
    def checkpoint(self) -> str:
        return f"{self.partition_id}:{self.offset}"


class NormalizedEvent(BaseModel):
    """An accepted, validated message. Optional contract fields stay null; nothing defaults to 0."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    message: HubMessage
    contract: TelemetryEvent | CostRecord
    event_time: datetime  # telemetry: event_time; cost: usage_end, usage_start or recorded_at
    ingestion_time: datetime  # the edge's ``received_at`` (stable across redelivery)
    late: bool
    doc_id: str = Field(min_length=64, max_length=64)
    partition_id: str
    offset: str
    sequence_number: int

    @property
    def key(self) -> EventKey:
        m = self.message
        return EventKey(m.customer_id, m.source_id, m.event_id)

    @model_validator(mode="after")
    def _kind_matches_contract(self) -> NormalizedEvent:
        is_telemetry = isinstance(self.contract, TelemetryEvent)
        if is_telemetry != (self.message.kind is HubMessageKind.TELEMETRY):
            raise ValueError("contract type does not match message kind")
        return self


class QuarantineRecord(BaseModel):
    """What the quarantine sink stores. Never carries a prompt/response body.

    ``payload`` is ``drop_body_fields(parsed)`` when the bytes parsed as JSON. When they did not
    parse, no body is stored at all, only ``payload_sha256`` and ``payload_bytes``.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    doc_id: str
    reason: QuarantineReason
    attempts: int = Field(ge=1)
    partition_id: str
    offset: str
    sequence_number: int
    enqueued_time: datetime
    quarantined_at: datetime
    customer_id: str | None = None
    source_id: str | None = None
    event_id: str | None = None
    payload: dict[str, Any] | list[Any] | None = None
    payload_sha256: str | None = None
    payload_bytes: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _no_body_and_exclusive(self) -> QuarantineRecord:
        if self.payload is not None and find_body_fields(self.payload):
            raise ValueError("quarantine payload contains body fields")
        if self.payload is not None and self.payload_sha256 is not None:
            raise ValueError("store either a payload or its sha256, never both")
        if self.payload is None and self.payload_sha256 is None:
            raise ValueError("store either a payload or its sha256")
        return self


class BatchResult(BaseModel):
    """Outcome of one batch. ``checkpoint`` is safe to commit once ``process_batch`` returned."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    accepted: int = 0
    duplicates: int = 0
    late: int = 0  # subset of ``accepted``
    quarantined: dict[QuarantineReason, int] = Field(default_factory=dict)
    outcome: BatchOutcome = BatchOutcome.ACCEPTED
    checkpoint: str | None = None  # last message of the batch; None for an empty batch

    @property
    def quarantined_total(self) -> int:
        return sum(self.quarantined.values())
