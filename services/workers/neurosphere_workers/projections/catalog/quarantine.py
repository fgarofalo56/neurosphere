"""Quarantine for edge candidates the worker scope does not cover (PRP-10 item 8).

An out-of-scope candidate used to be counted and dropped. It is now written to a durable
quarantine record first, so an operator can see what was skipped and why. The record holds
identifiers only (candidate edge ID, endpoints, domain, rule): no span attributes, no payloads.
The in-memory implementation is the test/local one; a hosted sink implements the same protocol.
"""

from __future__ import annotations

from datetime import datetime
from typing import Final, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

REASON_OUT_OF_SCOPE: Final = "out_of_scope"


class CandidateQuarantineRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    """Deterministic: the candidate edge ID, so a replay overwrites rather than duplicates."""
    reason: str
    relation_type: str
    source_id: str
    target_id: str
    cloud: str
    customer_id: str
    domain_id: str
    rule: str
    outbox_entry_id: str | None = None
    quarantined_at: datetime


@runtime_checkable
class CandidateQuarantine(Protocol):
    async def write(self, record: CandidateQuarantineRecord) -> None:
        """Persist ``record``. Idempotent by ``record.id``; a failure fails the entry."""
        raise NotImplementedError


class InMemoryCandidateQuarantine:
    def __init__(self) -> None:
        self.records: dict[str, CandidateQuarantineRecord] = {}
        self.writes = 0

    async def write(self, record: CandidateQuarantineRecord) -> None:
        self.writes += 1
        self.records[record.id] = record
