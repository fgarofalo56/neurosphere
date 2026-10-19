"""Repository protocols the runner depends on (Cosmos, in-memory, PRP-11 analytics adapters)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from neurosphere_core.migrations.models import MigrationLedger

__all__ = ["AnalyticsSchemaStore", "DocumentStore", "LedgerStore", "StoredDocument"]


@dataclass(frozen=True)
class StoredDocument:
    """A document without store system fields, plus its concurrency token."""

    document: dict[str, Any]
    etag: str


@runtime_checkable
class DocumentStore(Protocol):
    """Documents of one container."""

    def iter_documents(self) -> AsyncIterator[StoredDocument]:
        """Yield every document (system fields stripped) with its etag."""
        ...

    async def replace_document(self, document: dict[str, Any], *, etag: str) -> StoredDocument:
        """Replace if the stored etag still equals ``etag``; else raise ``StaleVersionError``."""
        ...


@runtime_checkable
class LedgerStore(Protocol):
    """Compare-and-swap storage for ledger documents."""

    async def read(self, ledger_id: str) -> MigrationLedger | None:
        """Return the ledger with its etag, or ``None`` when it does not exist."""
        ...

    async def write(self, ledger: MigrationLedger, *, expected_etag: str | None) -> MigrationLedger:
        """Create (``expected_etag is None``) or replace; ``StaleVersionError`` on a lost race."""
        ...


@runtime_checkable
class AnalyticsSchemaStore(Protocol):
    """Schema-version access that PRP-11 analytics adapters can implement.

    A schema is a plain dict carrying an int ``schema_version`` (0 when never migrated).
    """

    async def get_schema_version(self, name: str) -> int: ...

    async def get_schema(self, name: str) -> dict[str, Any]: ...

    async def set_schema(self, name: str, schema: dict[str, Any], *, expected_version: int) -> None:
        """Store ``schema``; raise ``StaleVersionError`` if the stored version is not expected."""
        ...
