"""Outbox and checkpoint stores: protocols, in-memory, and Cosmos (container clients injected).

ORDERING (decision): entries are ordered by ``(ts, id)``, where ``ts`` is assigned by the STORE at
first insert (Cosmos ``_ts``, epoch seconds, server clock; in memory a monotonic counter) and
``id`` breaks ties. Rationale: Cosmos has no sequence generator, the emulator is not a faithful
change feed, and a client clock would race between workers. Known limit: ``_ts`` has one-second
resolution and commits are not strictly visible in ``_ts`` order, so a reader could pass an entry
that becomes visible late. Two mitigations: (1) ``CosmosOutboxStore`` hides entries younger than
``settle_seconds`` (default 5) from reads; (2) sinks MUST be idempotent by outbox entry id (the
event/ledger-change ids are deterministic), so an occasional replay is harmless. Checkpoints are
per (sink, customer_id) because the outbox partition key is ``/customer_id`` and every read is a
single-partition query.

Cosmos queries sort on ``_ts`` only (multi-field ORDER BY needs a composite index, which the vNext
emulator lacks); the id tie-break is applied client-side after whole ``_ts`` groups are fetched.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Final, Protocol, runtime_checkable

from azure.core import MatchConditions
from azure.cosmos.exceptions import (
    CosmosAccessConditionFailedError,
    CosmosResourceExistsError,
    CosmosResourceNotFoundError,
)
from neurosphere_core.clients import translating
from neurosphere_core.errors import DependencyTransientError

from neurosphere_workers.projections.outbox.models import Cursor, OutboxEntry, StoredOutboxEntry

DEFAULT_SETTLE_SECONDS: Final = 5
_MAX_CHECKPOINT_ATTEMPTS: Final = 5


@runtime_checkable
class OutboxStore(Protocol):
    async def append(self, entry: OutboxEntry) -> bool:
        """Create-if-absent by ``entry.id``. True if newly created, False if it already existed."""
        raise NotImplementedError

    async def read_after(
        self, customer_id: str, after: Cursor | None, limit: int
    ) -> list[StoredOutboxEntry]:
        """Up to ``limit`` entries strictly after ``after`` in ``(ts, id)`` order."""
        raise NotImplementedError


@runtime_checkable
class CheckpointStore(Protocol):
    async def get(self, sink: str, customer_id: str) -> Cursor | None:
        raise NotImplementedError

    async def advance(self, sink: str, customer_id: str, cursor: Cursor) -> None:
        """Monotonic: a cursor not beyond the stored one is ignored."""
        raise NotImplementedError


class InMemoryOutboxStore:
    def __init__(self) -> None:
        self._items: dict[tuple[str, str], StoredOutboxEntry] = {}
        self._counter = 0
        self.append_calls = 0

    async def append(self, entry: OutboxEntry) -> bool:
        self.append_calls += 1
        slot = (entry.customer_id, entry.id)
        if slot in self._items:
            return False
        self._counter += 1
        self._items[slot] = StoredOutboxEntry(entry=entry, ts=self._counter)
        return True

    async def read_after(
        self, customer_id: str, after: Cursor | None, limit: int
    ) -> list[StoredOutboxEntry]:
        mine = sorted(
            (s for (cust, _), s in self._items.items() if cust == customer_id),
            key=lambda s: s.cursor,
        )
        return [s for s in mine if after is None or s.cursor > after][:limit]

    def entries(self, customer_id: str) -> list[OutboxEntry]:
        return [
            s.entry
            for s in sorted(self._items.values(), key=lambda s: s.cursor)
            if s.entry.customer_id == customer_id
        ]


class InMemoryCheckpointStore:
    def __init__(self) -> None:
        self._cursors: dict[tuple[str, str], Cursor] = {}

    async def get(self, sink: str, customer_id: str) -> Cursor | None:
        return self._cursors.get((sink, customer_id))

    async def advance(self, sink: str, customer_id: str, cursor: Cursor) -> None:
        current = self._cursors.get((sink, customer_id))
        if current is None or cursor > current:
            self._cursors[(sink, customer_id)] = cursor


class CosmosOutboxStore:
    def __init__(
        self,
        container: Any,
        *,
        settle_seconds: int = DEFAULT_SETTLE_SECONDS,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._container = container
        self._settle = settle_seconds
        self._clock = clock or (lambda: datetime.now(UTC))

    async def append(self, entry: OutboxEntry) -> bool:
        with translating():
            try:
                await self._container.create_item(body=entry.model_dump(mode="json"))
            except CosmosResourceExistsError:
                return False
        return True

    async def read_after(
        self, customer_id: str, after: Cursor | None, limit: int
    ) -> list[StoredOutboxEntry]:
        max_ts = int(self._clock().timestamp()) - self._settle
        query = (
            "SELECT * FROM c WHERE c.customer_id = @customer AND c._ts >= @ts AND c._ts <= @max "
            "ORDER BY c._ts"
        )
        parameters = [
            {"name": "@customer", "value": customer_id},
            {"name": "@ts", "value": 0 if after is None else after.ts},
            {"name": "@max", "value": max_ts},
        ]
        collected: list[StoredOutboxEntry] = []
        with translating():
            async for doc in self._container.query_items(
                query=query, parameters=parameters, partition_key=customer_id
            ):
                ts = int(doc["_ts"])
                # Whole _ts groups only: stop at the first new group once we have enough
                # entries beyond the cursor.
                if len(collected) >= limit and ts != collected[-1].ts:
                    break
                body = {k: v for k, v in doc.items() if not k.startswith("_")}
                stored = StoredOutboxEntry(entry=OutboxEntry.model_validate(body), ts=ts)
                if after is None or stored.cursor > after:
                    collected.append(stored)
        collected.sort(key=lambda s: s.cursor)
        return collected[:limit]


def _checkpoint_id(sink: str) -> str:
    return "ckpt-" + hashlib.sha256(sink.encode()).hexdigest()[:40]


class CosmosCheckpointStore:
    def __init__(self, container: Any) -> None:
        self._container = container

    async def get(self, sink: str, customer_id: str) -> Cursor | None:
        with translating():
            try:
                doc = await self._container.read_item(
                    item=_checkpoint_id(sink), partition_key=customer_id
                )
            except CosmosResourceNotFoundError:
                return None
        return Cursor(int(doc["ts"]), str(doc["entry_id"]))

    async def advance(self, sink: str, customer_id: str, cursor: Cursor) -> None:
        doc_id = _checkpoint_id(sink)
        body = {
            "id": doc_id,
            "customer_id": customer_id,
            "sink": sink,
            "ts": cursor.ts,
            "entry_id": cursor.entry_id,
        }
        with translating():
            for _ in range(_MAX_CHECKPOINT_ATTEMPTS):
                try:
                    doc = await self._container.read_item(item=doc_id, partition_key=customer_id)
                except CosmosResourceNotFoundError:
                    try:
                        await self._container.create_item(body=body)
                    except CosmosResourceExistsError:
                        continue
                    return
                if Cursor(int(doc["ts"]), str(doc["entry_id"])) >= cursor:
                    return
                try:
                    await self._container.replace_item(
                        item=doc_id,
                        body=body,
                        etag=doc["_etag"],
                        match_condition=MatchConditions.IfNotModified,
                    )
                except CosmosAccessConditionFailedError:
                    continue
                return
        raise DependencyTransientError(
            "outbox checkpoint contention", reason="checkpoint_contention"
        )
