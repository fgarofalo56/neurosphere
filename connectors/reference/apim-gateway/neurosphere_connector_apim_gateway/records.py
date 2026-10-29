"""Append-only store for apply records (ownership ledger per apply).

``ApplyResult.rollback_token`` is capped at 1024 characters, too small for prior documents, so
the token is the record id and the record lives here. The in-memory implementation backs the
unit tests; PRP-34 item 2 provides the durable gateway-store implementation of the same
protocol. Records are never edited: every change appends a new version, ``latest`` returns the
newest and ``history`` all of them.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from neurosphere_connector_apim_gateway.models import ApplyRecord

__all__ = ["ApplyRecordStore", "InMemoryApplyRecordStore"]


@runtime_checkable
class ApplyRecordStore(Protocol):
    async def append(self, record: ApplyRecord) -> None: ...

    async def latest(self, record_id: str) -> ApplyRecord | None: ...


class InMemoryApplyRecordStore:
    def __init__(self) -> None:
        self._versions: dict[str, list[ApplyRecord]] = {}

    async def append(self, record: ApplyRecord) -> None:
        self._versions.setdefault(record.id, []).append(record)

    async def latest(self, record_id: str) -> ApplyRecord | None:
        versions = self._versions.get(record_id)
        return versions[-1] if versions else None

    def history(self, record_id: str) -> tuple[ApplyRecord, ...]:
        return tuple(self._versions.get(record_id, ()))
