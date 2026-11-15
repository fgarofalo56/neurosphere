"""Lifecycle ``DocumentBackend`` over the catalog container (PRP-23 item 2).

A new module beside the catalog repository: the repository itself is not edited. It deletes
whole catalog documents (entities, edges and their satellite documents) by storage id, using the
partition key fields the repository wrote onto each document (``partition_key_paths(shape)``), so
the delete addresses exactly one partition. The backend is bound to one cloud and customer; every
read and listing filters on both, so it cannot reach another customer's documents.

Catalog documents are not keyed by data subject, so subject enumeration answers "none" and
in-place pseudonymization is reported as unsupported rather than faked. The audit container is
never accepted (the lifecycle target adapter refuses it as well).
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Final

from azure.cosmos.exceptions import CosmosResourceNotFoundError

from neurosphere_core.catalog.partitioning import PartitionKeyShape, partition_key_paths
from neurosphere_core.clients import translating
from neurosphere_core.errors import CapabilityUnavailableError
from neurosphere_core.lifecycle.adapters import CatalogTarget
from neurosphere_core.lifecycle.rules import is_audit_container

__all__ = ["CatalogLifecycleBackend", "catalog_target"]

DATA_CLASS_PREFIX: Final = "catalog_"
_DOC_TYPES: Final = frozenset({"entity", "edge", "observation", "override", "alias"})
_CREATED_KEYS: Final = ("created_at", "first_observed", "observed_at", "decided_at")
_EXPORT_KEYS: Final = ("id", "doc_type", "ref", "cloud", "customer_id", "domain_id")


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _created_at(doc: Mapping[str, Any]) -> datetime:
    body = doc.get("body")
    if isinstance(body, Mapping):
        for key in _CREATED_KEYS:
            parsed = _parse_time(body.get(key))
            if parsed is not None:
                return parsed
    # An undated document is treated as brand new: it can never look older than it is.
    return datetime.now(UTC)


def _data_class(doc: Mapping[str, Any]) -> str:
    return f"{DATA_CLASS_PREFIX}{doc.get('doc_type', 'entity')}"


class CatalogLifecycleBackend:
    """:class:`~neurosphere_core.lifecycle.adapters.DocumentBackend` for one customer's catalog."""

    def __init__(
        self,
        container: Any,
        *,
        shape: PartitionKeyShape,
        cloud: str,
        customer_id: str,
    ) -> None:
        self._container = container
        self._paths = tuple(p.lstrip("/") for p in partition_key_paths(shape))
        self._cloud = cloud
        self._customer = customer_id

    def _base(self) -> tuple[str, list[dict[str, Any]]]:
        return (
            "c.cloud = @cloud AND c.customer_id = @customer",
            [
                {"name": "@cloud", "value": self._cloud},
                {"name": "@customer", "value": self._customer},
            ],
        )

    async def _find(self, record_id: str) -> dict[str, Any] | None:
        where, params = self._base()
        sql = f"SELECT TOP @n * FROM c WHERE c.id = @id AND {where}"  # noqa: S608
        params = [{"name": "@n", "value": 1}, {"name": "@id", "value": record_id}, *params]
        with translating():
            async for row in self._container.query_items(sql, parameters=params):
                return dict(row)
        return None

    @staticmethod
    def _mapping(doc: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "id": doc["id"],
            "data_class": _data_class(doc),
            "created_at": _created_at(doc),
            "doc_type": doc.get("doc_type"),
            "customer_id": doc.get("customer_id"),
            "domain_id": doc.get("domain_id"),
        }

    async def read(self, record_id: str) -> Mapping[str, Any] | None:
        doc = await self._find(record_id)
        return None if doc is None else self._mapping(doc)

    async def remove(self, record_id: str) -> None:
        doc = await self._find(record_id)
        if doc is None:
            return  # already gone: deleting nothing is not an error
        key = [doc[path] for path in self._paths]
        with translating():
            try:
                await self._container.delete_item(item=record_id, partition_key=key)
            except CosmosResourceNotFoundError:
                return

    async def page(self, data_class: str, limit: int, after: str | None) -> list[Mapping[str, Any]]:
        if not data_class.startswith(DATA_CLASS_PREFIX):
            return []
        doc_type = data_class[len(DATA_CLASS_PREFIX) :]
        if doc_type not in _DOC_TYPES:
            return []
        where, params = self._base()
        clauses = [where, "c.doc_type = @doc_type"]
        params = [
            {"name": "@n", "value": max(1, limit)},
            {"name": "@doc_type", "value": doc_type},
            *params,
        ]
        if after is not None:
            clauses.append("c.id > @after")
            params.append({"name": "@after", "value": after})
        sql = f"SELECT TOP @n * FROM c WHERE {' AND '.join(clauses)} ORDER BY c.id ASC"  # noqa: S608
        rows: list[Mapping[str, Any]] = []
        with translating():
            async for row in self._container.query_items(sql, parameters=params):
                rows.append(self._mapping(row))
        return rows

    async def page_by_subject(
        self, subject_id: str, limit: int, after: str | None
    ) -> list[Mapping[str, Any]]:
        # Catalog documents are not keyed by a data subject: nothing to enumerate.
        return []

    async def redact_subject(self, record_id: str) -> None:
        raise CapabilityUnavailableError("pseudonymize_unsupported")

    async def project(self, record_id: str) -> Mapping[str, Any]:
        doc = await self._find(record_id)
        if doc is None:
            return {}
        return {key: doc[key] for key in _EXPORT_KEYS if key in doc}


def catalog_target(container_name: str, backend: CatalogLifecycleBackend) -> CatalogTarget:
    """The registry-ready target. Refuses the audit container by name."""
    if is_audit_container(container_name):
        raise ValueError("the audit container cannot be a lifecycle target")
    return CatalogTarget(container_name, backend)
