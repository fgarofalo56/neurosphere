"""Target adapters: catalog, archive, ledger, conversation and the pseudonym mapping store.

Each adapter is written against a small structural backend protocol that the owning store (or a
thin shim around it) satisfies. The lifecycle package imports nothing from the stores' internals
and nothing from ``neurosphere_api``/``neurosphere_workers`` (packages/core is a leaf). Wiring a
real store into a backend is the owning service's job; this module defines what it must offer.

The conversation backend mirrors ``neurosphere_api.copilot.store.ConversationStore``
(``get``/``delete``/``list_conversations``) without importing it.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any, Final, Protocol

from neurosphere_core.errors import CapabilityUnavailableError
from neurosphere_core.lifecycle.models import TargetRecord
from neurosphere_core.lifecycle.rules import is_audit_container

KIND_CATALOG: Final = "catalog"
KIND_ARCHIVE: Final = "archive"
KIND_LEDGER: Final = "ledger"
KIND_CONVERSATION: Final = "conversation"


class DocumentBackend(Protocol):
    """Generic document-shaped store surface.

    A document is a mapping with ``id``, ``data_class``, ``created_at`` (aware datetime) and
    optional ``subject_id``, ``doc_type``, ``customer_id``, ``domain_id``, ``pseudonymized``.
    """

    async def read(self, record_id: str) -> Mapping[str, Any] | None: ...

    async def remove(self, record_id: str) -> None: ...

    async def page(
        self, data_class: str, limit: int, after: str | None
    ) -> list[Mapping[str, Any]]: ...

    async def redact_subject(self, record_id: str) -> None: ...

    async def project(self, record_id: str) -> Mapping[str, Any]: ...


def _record(doc: Mapping[str, Any]) -> TargetRecord:
    return TargetRecord(
        record_id=str(doc["id"]),
        data_class=str(doc["data_class"]),
        created_at=doc["created_at"],
        subject_id=doc.get("subject_id"),
        doc_type=doc.get("doc_type"),
        customer_id=doc.get("customer_id"),
        domain_id=doc.get("domain_id"),
        pseudonymized=bool(doc.get("pseudonymized", False)),
    )


class BackendTarget:
    """LifecycleTarget over a DocumentBackend. The audit container is refused at construction."""

    def __init__(self, target_kind: str, container: str, backend: DocumentBackend) -> None:
        if is_audit_container(container):
            raise ValueError("the audit container cannot be a lifecycle target")
        self.target_kind = target_kind
        self.container = container
        self._backend = backend

    async def get(self, record_id: str) -> TargetRecord | None:
        doc = await self._backend.read(record_id)
        return None if doc is None else _record(doc)

    async def list_records(
        self, *, data_class: str, limit: int, after: str | None
    ) -> list[TargetRecord]:
        return [_record(d) for d in await self._backend.page(data_class, limit, after)]

    async def delete(self, record_id: str) -> None:
        await self._backend.remove(record_id)

    async def pseudonymize(self, record_id: str) -> None:
        await self._backend.redact_subject(record_id)

    async def export(self, record_id: str) -> Mapping[str, Any]:
        return await self._backend.project(record_id)


class CatalogTarget(BackendTarget):
    def __init__(self, container: str, backend: DocumentBackend) -> None:
        super().__init__(KIND_CATALOG, container, backend)


class ArchiveTarget(BackendTarget):
    def __init__(self, container: str, backend: DocumentBackend) -> None:
        super().__init__(KIND_ARCHIVE, container, backend)


class LedgerTarget(BackendTarget):
    def __init__(self, container: str, backend: DocumentBackend) -> None:
        super().__init__(KIND_LEDGER, container, backend)


class ConversationLike(Protocol):
    """The fields the adapter reads from a stored conversation."""

    @property
    def id(self) -> str: ...

    @property
    def owner(self) -> str: ...

    @property
    def created_at(self) -> datetime: ...

    @property
    def retention_class(self) -> str: ...


class ConversationBackend(Protocol):
    """Mirrors ``ConversationStore.get`` / ``delete`` (owner-scoped)."""

    async def get(
        self, owner: str, conversation_id: str, *, now: datetime
    ) -> ConversationLike | None: ...

    async def delete(self, owner: str, conversation_id: str) -> bool: ...


def _utc_now() -> datetime:
    return datetime.now(UTC)


class ConversationTarget:
    """Record ids are ``<owner>/<conversation_id>``; the owner is the subject.

    Conversations cannot be pseudonymized in place (the owner is the partition key), so that
    action is unsupported and reported as such rather than faked. Expiry sweeps cannot enumerate
    across owners through the owner-scoped store, so ``list_records`` is empty; the store's own
    ``expires_at`` and explicit per-record requests cover conversations.
    """

    target_kind = KIND_CONVERSATION

    def __init__(
        self,
        container: str,
        backend: ConversationBackend,
        *,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        if is_audit_container(container):
            raise ValueError("the audit container cannot be a lifecycle target")
        self.container = container
        self._backend = backend
        self._clock = clock

    @staticmethod
    def make_record_id(owner: str, conversation_id: str) -> str:
        return f"{owner}/{conversation_id}"

    @staticmethod
    def _split(record_id: str) -> tuple[str, str] | None:
        owner, sep, conversation_id = record_id.partition("/")
        return (owner, conversation_id) if sep and owner and conversation_id else None

    async def get(self, record_id: str) -> TargetRecord | None:
        parts = self._split(record_id)
        if parts is None:
            return None
        found = await self._backend.get(parts[0], parts[1], now=self._clock())
        if found is None:
            return None
        return TargetRecord(
            record_id=record_id,
            data_class=found.retention_class,
            created_at=found.created_at,
            subject_id=found.owner,
            doc_type="conversation",
        )

    async def list_records(
        self, *, data_class: str, limit: int, after: str | None
    ) -> list[TargetRecord]:
        return []

    async def delete(self, record_id: str) -> None:
        parts = self._split(record_id)
        if parts is not None:
            await self._backend.delete(parts[0], parts[1])

    async def pseudonymize(self, record_id: str) -> None:
        raise CapabilityUnavailableError("pseudonymize_unsupported")

    async def export(self, record_id: str) -> Mapping[str, Any]:
        record = await self.get(record_id)
        if record is None:
            return {}
        return {
            "conversation_id": record_id.partition("/")[2],
            "retention_class": record.data_class,
        }


class MappingBackend(Protocol):
    async def has(self, subject_id: str) -> bool: ...

    async def drop(self, subject_id: str) -> None: ...


class MappingStoreAdapter:
    """PseudonymMappingStore over a backend. Destroying the mapping is the erasure of a person."""

    def __init__(self, backend: MappingBackend) -> None:
        self._backend = backend

    async def exists(self, subject_id: str) -> bool:
        return await self._backend.has(subject_id)

    async def destroy(self, subject_id: str) -> None:
        await self._backend.drop(subject_id)
