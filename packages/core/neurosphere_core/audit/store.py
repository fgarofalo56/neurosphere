"""Storage port for the audit repository, and the in-memory fake used by unit tests.

The port is deliberately narrow: records can be CREATED (create-only; an existing id is a
conflict, never an overwrite), READ and QUERIED. The only replaceable document is the per-chain
tail pointer, and only under an ETag precondition. There is no record update, upsert, patch or
delete operation in this protocol, so no repository code path can mutate a written record.

Fork prevention (PRP-06 gotcha "hash chain concurrency"): the record document id is derived
from its sequence (``rec-<seq>``) inside the chain's partition, so two writers racing for the
same sequence cannot both succeed; the loser gets :class:`SequenceTakenError` and retries on
top of the winner. The ETag-guarded tail pointer only ever advances by one.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from typing import Any, Final, NamedTuple, Protocol

from neurosphere_core.audit.chain import TailPointer

RECORD_DOC_TYPE: Final = "audit_record"
TAIL_DOC_TYPE: Final = "audit_tail"
TAIL_ID: Final = "tail"


def record_document_id(sequence: int) -> str:
    """Deterministic id: one document per (chain partition, sequence)."""
    if sequence < 0:
        raise ValueError("sequence must be >= 0")
    return f"rec-{sequence:020d}"


class SequenceTakenError(Exception):
    """A record with this sequence already exists in the chain (another writer won)."""


class TailConflictError(Exception):
    """The tail pointer changed since it was read (ETag precondition failed)."""


class StoredTail(NamedTuple):
    tail: TailPointer
    etag: str


class AuditStore(Protocol):
    """Backend port. Implementations: :class:`InMemoryAuditStore`, ``CosmosAuditStore``."""

    async def read_tail(self, chain_id: str) -> StoredTail | None:
        """Current tail pointer and its ETag, or ``None`` for an empty chain."""
        ...

    async def create_record(
        self, chain_id: str, sequence: int, document: Mapping[str, Any]
    ) -> None:
        """Create-only insert. Raises :class:`SequenceTakenError` if the sequence exists."""
        ...

    async def read_record(self, chain_id: str, sequence: int) -> dict[str, Any] | None:
        """The stored record document (contract fields only), or ``None``."""
        ...

    async def write_tail(self, tail: TailPointer, *, if_match: str | None) -> None:
        """Create (``if_match=None``) or ETag-replace the tail; :class:`TailConflictError`."""
        ...

    async def query_range(self, chain_id: str, start: int, stop: int) -> list[dict[str, Any]]:
        """Record documents with ``start <= sequence < stop``, sorted by sequence."""
        ...


class InMemoryAuditStore:
    """Test double with Cosmos-like semantics (create-only ids, ETag preconditions).

    Every method yields to the event loop first, so concurrent ``asyncio`` writers genuinely
    interleave between "read tail" and "create record", as they would against a network store.
    Documents are stored serialized, so callers can never mutate stored state by reference.

    ``simulate_*`` methods model an attacker with raw database access (bypassing the
    repository). They exist only so tests can prove tampering is detected.
    """

    def __init__(self) -> None:
        self._docs: dict[tuple[str, str], str] = {}
        self._etags: dict[tuple[str, str], str] = {}
        self._etag_counter = 0
        self.sequence_conflicts = 0
        self.tail_conflicts = 0
        self.fail_with: Exception | None = None

    def _next_etag(self) -> str:
        self._etag_counter += 1
        return f'"etag-{self._etag_counter}"'

    async def _io(self) -> None:
        await asyncio.sleep(0)
        if self.fail_with is not None:
            raise self.fail_with

    async def read_tail(self, chain_id: str) -> StoredTail | None:
        await self._io()
        raw = self._docs.get((chain_id, TAIL_ID))
        if raw is None:
            return None
        doc = json.loads(raw)
        tail = TailPointer(
            chain_id=doc["chain_id"], sequence=doc["sequence"], record_hash=doc["record_hash"]
        )
        return StoredTail(tail, self._etags[(chain_id, TAIL_ID)])

    async def create_record(
        self, chain_id: str, sequence: int, document: Mapping[str, Any]
    ) -> None:
        await self._io()
        key = (chain_id, record_document_id(sequence))
        if key in self._docs:
            self.sequence_conflicts += 1
            raise SequenceTakenError(key[1])
        self._docs[key] = json.dumps(dict(document))
        self._etags[key] = self._next_etag()

    async def read_record(self, chain_id: str, sequence: int) -> dict[str, Any] | None:
        await self._io()
        raw = self._docs.get((chain_id, record_document_id(sequence)))
        return None if raw is None else json.loads(raw)

    async def write_tail(self, tail: TailPointer, *, if_match: str | None) -> None:
        await self._io()
        key = (tail.chain_id, TAIL_ID)
        current = self._etags.get(key)
        if (if_match is None and current is not None) or (
            if_match is not None and current != if_match
        ):
            self.tail_conflicts += 1
            raise TailConflictError(tail.chain_id)
        self._docs[key] = tail.model_dump_json()
        self._etags[key] = self._next_etag()

    async def query_range(self, chain_id: str, start: int, stop: int) -> list[dict[str, Any]]:
        await self._io()
        found: list[dict[str, Any]] = []
        for (chain, doc_id), raw in self._docs.items():
            if chain != chain_id or doc_id == TAIL_ID:
                continue
            doc = json.loads(raw)
            if start <= doc.get("sequence", -1) < stop:
                found.append(doc)
        found.sort(key=lambda d: d["sequence"])
        return found

    # -- tamper simulation (raw database access, not part of any repository API) -----------

    def simulate_overwrite(self, chain_id: str, sequence: int, document: Mapping[str, Any]) -> None:
        self._docs[(chain_id, record_document_id(sequence))] = json.dumps(dict(document))

    def simulate_remove(self, chain_id: str, sequence: int) -> None:
        del self._docs[(chain_id, record_document_id(sequence))]

    def simulate_insert(self, chain_id: str, doc_id: str, document: Mapping[str, Any]) -> None:
        self._docs[(chain_id, doc_id)] = json.dumps(dict(document))

    def raw_documents(self, chain_id: str) -> list[dict[str, Any]]:
        """Every stored record document of the chain (for scan tests)."""
        return [
            json.loads(raw)
            for (chain, doc_id), raw in self._docs.items()
            if chain == chain_id and doc_id != TAIL_ID
        ]
