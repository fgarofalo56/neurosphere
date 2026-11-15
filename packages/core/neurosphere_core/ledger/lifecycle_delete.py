"""Lifecycle ``DocumentBackend`` over the cost-ledger container (PRP-23 item 2).

A new module beside the ledger store: the store itself is not edited. The container's partition
key is ``/customer_id`` and the backend is bound to one customer, so every operation is a
single-partition point read, point delete or in-partition query. Only per-request entries
(``doc_type="entry"``, data class ``ledger_entry``) are lifecycle records; allocation records are
not touched here (they carry no timestamp a retention rule could use).

Ledger entries hold cost and token metadata, no person identifiers: subject enumeration answers
"none" and pseudonymization is reported as unsupported rather than faked.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Final

from azure.cosmos.exceptions import CosmosResourceNotFoundError

from neurosphere_core.clients import translating
from neurosphere_core.errors import CapabilityUnavailableError
from neurosphere_core.lifecycle.adapters import LedgerTarget
from neurosphere_core.lifecycle.rules import is_audit_container

__all__ = ["DATA_CLASS_ENTRY", "LedgerLifecycleBackend", "ledger_target"]

DATA_CLASS_ENTRY: Final = "ledger_entry"
_EXPORT_KEYS: Final = (
    "id",
    "doc_type",
    "cloud",
    "customer_id",
    "domain_id",
    "cost_category",
    "provider",
    "model",
    "occurred_at",
    "observed_at",
    "estimated_amount",
    "estimated_currency",
    "authoritative_amount",
    "authoritative_currency",
)


def _parse_time(value: object) -> datetime:
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return datetime.now(UTC)  # unparsable: never looks older than it is
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
    return datetime.now(UTC)


class LedgerLifecycleBackend:
    """:class:`~neurosphere_core.lifecycle.adapters.DocumentBackend` for one customer's ledger."""

    def __init__(self, container: Any, *, customer_id: str) -> None:
        self._container = container
        self._customer = customer_id

    @staticmethod
    def _mapping(doc: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "id": doc["id"],
            "data_class": DATA_CLASS_ENTRY,
            "created_at": _parse_time(doc.get("occurred_at")),
            "doc_type": doc.get("doc_type"),
            "customer_id": doc.get("customer_id"),
            "domain_id": doc.get("domain_id"),
        }

    async def _read_doc(self, record_id: str) -> dict[str, Any] | None:
        with translating():
            try:
                doc = await self._container.read_item(item=record_id, partition_key=self._customer)
            except CosmosResourceNotFoundError:
                return None
        return dict(doc) if doc.get("doc_type") == "entry" else None

    async def read(self, record_id: str) -> Mapping[str, Any] | None:
        doc = await self._read_doc(record_id)
        return None if doc is None else self._mapping(doc)

    async def remove(self, record_id: str) -> None:
        if await self._read_doc(record_id) is None:
            return  # absent, or not an entry: nothing to delete
        with translating():
            try:
                await self._container.delete_item(item=record_id, partition_key=self._customer)
            except CosmosResourceNotFoundError:
                return

    async def page(self, data_class: str, limit: int, after: str | None) -> list[Mapping[str, Any]]:
        if data_class != DATA_CLASS_ENTRY:
            return []
        clauses = ["c.customer_id = @customer", "c.doc_type = @doc_type"]
        params: list[dict[str, Any]] = [
            {"name": "@n", "value": max(1, limit)},
            {"name": "@customer", "value": self._customer},
            {"name": "@doc_type", "value": "entry"},
        ]
        if after is not None:
            clauses.append("c.id > @after")
            params.append({"name": "@after", "value": after})
        sql = f"SELECT TOP @n * FROM c WHERE {' AND '.join(clauses)} ORDER BY c.id ASC"  # noqa: S608
        rows: list[Mapping[str, Any]] = []
        with translating():
            async for row in self._container.query_items(
                sql, parameters=params, partition_key=self._customer
            ):
                rows.append(self._mapping(row))
        return rows

    async def page_by_subject(
        self, subject_id: str, limit: int, after: str | None
    ) -> list[Mapping[str, Any]]:
        # Ledger entries carry no person identifier: nothing to enumerate.
        return []

    async def redact_subject(self, record_id: str) -> None:
        raise CapabilityUnavailableError("pseudonymize_unsupported")

    async def project(self, record_id: str) -> Mapping[str, Any]:
        doc = await self._read_doc(record_id)
        if doc is None:
            return {}
        return {key: doc[key] for key in _EXPORT_KEYS if key in doc}


def ledger_target(container_name: str, backend: LedgerLifecycleBackend) -> LedgerTarget:
    """The registry-ready target. Refuses the audit container by name."""
    if is_audit_container(container_name):
        raise ValueError("the audit container cannot be a lifecycle target")
    return LedgerTarget(container_name, backend)
