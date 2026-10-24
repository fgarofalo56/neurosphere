"""In-memory implementations of the lifecycle protocols (test doubles and local runs)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from neurosphere_core.errors import CapabilityUnavailableError
from neurosphere_core.lifecycle.models import LegalHold, TargetRecord
from neurosphere_core.lifecycle.targets import QueuedRequest


class InMemoryTarget:
    """A target with a dict behind it.

    ``ignore_deletes`` simulates a store that acknowledges a delete but keeps the record, which
    only the read-back can catch.
    """

    def __init__(self, target_kind: str, container: str, *, ignore_deletes: bool = False) -> None:
        self.target_kind = target_kind
        self.container = container
        self.ignore_deletes = ignore_deletes
        self.records: dict[str, TargetRecord] = {}
        self.content: dict[str, dict[str, Any]] = {}
        self.delete_calls = 0
        #: Simulates a store that cannot enumerate its records by subject.
        self.cannot_enumerate_subjects = False

    def put(self, record: TargetRecord, content: Mapping[str, Any] | None = None) -> None:
        self.records[record.record_id] = record
        self.content[record.record_id] = dict(content or {"kind": self.target_kind})

    async def get(self, record_id: str) -> TargetRecord | None:
        return self.records.get(record_id)

    async def list_records(
        self, *, data_class: str, limit: int, after: str | None
    ) -> list[TargetRecord]:
        ids = sorted(i for i, r in self.records.items() if r.data_class == data_class)
        if after is not None:
            ids = [i for i in ids if i > after]
        return [self.records[i] for i in ids[:limit]]

    async def list_by_subject(
        self, subject_id: str, *, limit: int, after: str | None
    ) -> list[TargetRecord]:
        if self.cannot_enumerate_subjects:
            raise CapabilityUnavailableError("subject_enumeration_unsupported")
        ids = sorted(i for i, r in self.records.items() if r.subject_id == subject_id)
        if after is not None:
            ids = [i for i in ids if i > after]
        return [self.records[i] for i in ids[:limit]]

    async def delete(self, record_id: str) -> None:
        self.delete_calls += 1
        if self.ignore_deletes:
            return
        self.records.pop(record_id, None)
        self.content.pop(record_id, None)

    async def pseudonymize(self, record_id: str) -> None:
        record = self.records[record_id]
        self.records[record_id] = record.model_copy(
            update={"subject_id": None, "pseudonymized": True}
        )

    async def export(self, record_id: str) -> Mapping[str, Any]:
        return dict(self.content[record_id])


class InMemoryMappingStore:
    def __init__(self, subjects: set[str] | None = None) -> None:
        self.subjects = set(subjects or ())
        self.ignore_destroy = False

    async def exists(self, subject_id: str) -> bool:
        return subject_id in self.subjects

    async def destroy(self, subject_id: str) -> None:
        if not self.ignore_destroy:
            self.subjects.discard(subject_id)


class InMemoryHoldRegistry:
    def __init__(self) -> None:
        self._holds: dict[str, LegalHold] = {}

    async def place(self, hold: LegalHold) -> None:
        self._holds[hold.hold_id] = hold

    async def release(self, hold_id: str) -> bool:
        return self._holds.pop(hold_id, None) is not None

    async def active(self) -> list[LegalHold]:
        return list(self._holds.values())


class InMemoryRequestQueue:
    def __init__(self) -> None:
        self._items: dict[str, QueuedRequest] = {}

    async def enqueue(self, item: QueuedRequest) -> bool:
        key = item.request.dedupe_key
        if any(q.request.dedupe_key == key for q in self._items.values()):
            return False
        self._items[item.request.request_id] = item
        return True

    async def pending(self) -> list[QueuedRequest]:
        return list(self._items.values())

    async def remove(self, request_id: str) -> None:
        self._items.pop(request_id, None)
