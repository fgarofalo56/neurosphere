"""In-memory stores used by unit tests and as the analytics fixture implementation.

Each read yields to the event loop once so ``asyncio.gather`` runners genuinely interleave;
check-and-set sections contain no await, so they are atomic like a server-side ETag check.
"""

from __future__ import annotations

import asyncio
import copy
from typing import TYPE_CHECKING, Any

from neurosphere_core.errors import StaleVersionError
from neurosphere_core.migrations.models import MigrationLedger
from neurosphere_core.migrations.protocols import StoredDocument

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterable

__all__ = ["InMemoryAnalyticsSchemaStore", "InMemoryDocumentStore", "InMemoryLedgerStore"]


class InMemoryDocumentStore:
    """``DocumentStore`` over a dict; counts writes for no-op assertions."""

    def __init__(self, documents: Iterable[dict[str, Any]] = ()) -> None:
        self._docs: dict[str, tuple[dict[str, Any], int]] = {}
        self.replace_count = 0
        for doc in documents:
            self._docs[doc["id"]] = (copy.deepcopy(doc), 1)

    def snapshot(self) -> list[dict[str, Any]]:
        """Deep copies of the current documents, ordered by id."""
        return [copy.deepcopy(self._docs[key][0]) for key in sorted(self._docs)]

    def mutate_behind_runner(self, doc_id: str, **changes: Any) -> None:
        """Test hook: change a document and bump its etag, as a concurrent writer would."""
        doc, version = self._docs[doc_id]
        self._docs[doc_id] = ({**doc, **changes}, version + 1)

    async def iter_documents(self) -> AsyncIterator[StoredDocument]:
        await asyncio.sleep(0)
        for key in sorted(self._docs):
            doc, version = self._docs[key]
            yield StoredDocument(copy.deepcopy(doc), str(version))

    async def replace_document(self, document: dict[str, Any], *, etag: str) -> StoredDocument:
        await asyncio.sleep(0)
        current = self._docs.get(document["id"])
        if current is None or str(current[1]) != etag:
            raise StaleVersionError("document changed since it was read")
        version = current[1] + 1
        self._docs[document["id"]] = (copy.deepcopy(document), version)
        self.replace_count += 1
        return StoredDocument(copy.deepcopy(document), str(version))


class InMemoryLedgerStore:
    """``LedgerStore`` with integer etags; counts writes."""

    def __init__(self) -> None:
        self._ledgers: dict[str, tuple[MigrationLedger, int]] = {}
        self.write_count = 0

    async def read(self, ledger_id: str) -> MigrationLedger | None:
        await asyncio.sleep(0)
        found = self._ledgers.get(ledger_id)
        if found is None:
            return None
        ledger, version = found
        return ledger.model_copy(deep=True, update={"etag": str(version)})

    async def write(self, ledger: MigrationLedger, *, expected_etag: str | None) -> MigrationLedger:
        await asyncio.sleep(0)
        found = self._ledgers.get(ledger.id)
        if expected_etag is None:
            if found is not None:
                raise StaleVersionError("ledger already exists")
            version = 1
        else:
            if found is None or str(found[1]) != expected_etag:
                raise StaleVersionError("ledger changed since it was read")
            version = found[1] + 1
        stored = ledger.model_copy(deep=True, update={"etag": None})
        self._ledgers[ledger.id] = (stored, version)
        self.write_count += 1
        return stored.model_copy(update={"etag": str(version)})


class InMemoryAnalyticsSchemaStore:
    """Fixture ``AnalyticsSchemaStore``; real adapters arrive with PRP-11 follow-ups."""

    def __init__(self, schemas: dict[str, dict[str, Any]] | None = None) -> None:
        self._schemas = {k: copy.deepcopy(v) for k, v in (schemas or {}).items()}
        self.set_count = 0

    async def get_schema_version(self, name: str) -> int:
        return int(self._schemas.get(name, {}).get("schema_version", 0))

    async def get_schema(self, name: str) -> dict[str, Any]:
        await asyncio.sleep(0)
        return copy.deepcopy(self._schemas.get(name, {"schema_version": 0}))

    async def set_schema(self, name: str, schema: dict[str, Any], *, expected_version: int) -> None:
        await asyncio.sleep(0)
        if await self.get_schema_version(name) != expected_version:
            raise StaleVersionError("analytics schema changed since it was read")
        self._schemas[name] = copy.deepcopy(schema)
        self.set_count += 1
