"""Outbox models (PRP-07 C5).

Two entry kinds, both with DETERMINISTIC ids so a retry never duplicates:

* ``event``: one per accepted event, ``id == NormalizedEvent.doc_id``.
* ``ledger_change``: one per ledger entry/allocation state, ``id == hash(entity id + content
  hash)``. Re-applying the same state produces the same id; a changed entry produces a new one.

Entries carry no wall-clock field: a redelivered write produces an equal document. Ordering comes
from the store (``StoredOutboxEntry.ts``), see ``store.py``.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


def event_outbox_id(event_doc_id: str) -> str:
    return event_doc_id


def ledger_change_outbox_id(entity_id: str, content_hash: str) -> str:
    return hashlib.sha256(f"ledger_change|{entity_id}|{content_hash}".encode()).hexdigest()


class OutboxEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    customer_id: str = Field(min_length=1)
    kind: Literal["event", "ledger_change"]
    # event kind: the event's doc_id. ledger_change: the entry / allocation id.
    ref_id: str = Field(min_length=1)
    entity: Literal["event", "ledger_entry", "allocation"]
    content_hash: str | None = None  # ledger_change only
    source_id: str | None = None
    request_id: str | None = None
    event_kind: Literal["telemetry", "cost"] | None = None  # event only
    occurred_at: str | None = None  # event time, fixed-width UTC string


class StoredOutboxEntry(BaseModel):
    """An entry plus the store-assigned ordering stamp ``ts``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    entry: OutboxEntry
    ts: int

    @property
    def cursor(self) -> Cursor:
        return Cursor(self.ts, self.entry.id)


@dataclass(frozen=True, order=True, slots=True)
class Cursor:
    """Total order position ``(ts, entry_id)``."""

    ts: int
    entry_id: str
