"""Interaction metadata index: Cosmos NoSQL container ``interaction_index`` and its twin (PRP-102).

One document per interaction: the PRP-99 ``InteractionRecord`` (metadata only, no content
property) plus the Cosmos ``id`` (= ``interaction_id``). Partition key ``/customer_id``,
``/domain_id`` (MultiHash; matches ``neurosphere_core.stores.containers``). Creation is
create-only (a duplicate is ``interaction_exists``).

Queries are parameterised with fixed clause text only. :meth:`query` is partition-scoped
(customer and domain are required), filters by agent, principal pseudonym, captured-at range,
tool, data asset, sensitivity category and detected category, orders by ``captured_at``
descending and returns at most :data:`MAX_QUERY_PAGE_SIZE` records with an opaque continuation
bound to the exact query. :class:`InMemoryInteractionIndex` has the same semantics for tests and
``NS_ENV=local``. Errors are reason codes; no document or SDK text reaches a message.
"""

from __future__ import annotations

import builtins
from collections.abc import Mapping
from typing import Any, Final, NoReturn, Protocol, runtime_checkable

from azure.cosmos import PartitionKey
from azure.cosmos.aio import ContainerProxy, CosmosClient, DatabaseProxy
from azure.cosmos.exceptions import (
    CosmosHttpResponseError,
    CosmosResourceExistsError,
    CosmosResourceNotFoundError,
)
from neurosphere_contracts.interactions.v1.interaction_record import InteractionRecord

from neurosphere_core.errors import NeuroSphereError, RateLimitedError
from neurosphere_core.interactions.models import (
    INTERACTION_EXISTS,
    INTERACTION_NOT_FOUND,
    INTERACTION_STORE_UNAVAILABLE,
    INVALID_QUERY,
    MAX_QUERY_PAGE_SIZE,
    IndexPage,
    InteractionQuery,
    InteractionStoreError,
    decode_continuation,
    encode_continuation,
    format_timestamp,
    index_document,
    record_from_document,
)

__all__ = [
    "DEFAULT_INTERACTION_INDEX_CONTAINER",
    "PARTITION_KEY_PATHS",
    "CosmosInteractionIndex",
    "InMemoryInteractionIndex",
    "IndexBackend",
    "create_interaction_index_container",
]

DEFAULT_INTERACTION_INDEX_CONTAINER: Final = "interaction_index"
PARTITION_KEY_PATHS: Final = ("/customer_id", "/domain_id")


def _check_limit(limit: int) -> None:
    if not 1 <= limit <= MAX_QUERY_PAGE_SIZE:
        raise InteractionStoreError(INVALID_QUERY)


@runtime_checkable
class IndexBackend(Protocol):
    """Where interaction index documents live."""

    async def get(
        self, customer_id: str, domain_id: str, interaction_id: str
    ) -> InteractionRecord | None: ...

    async def create(self, record: InteractionRecord) -> None:
        """Create-only; an existing document is ``interaction_exists``."""
        ...

    async def replace(self, record: InteractionRecord) -> None:
        """Replace an existing document (``interaction_not_found`` when absent)."""
        ...

    async def delete(self, customer_id: str, domain_id: str, interaction_id: str) -> bool:
        """Idempotent; ``True`` when a document was removed."""
        ...

    async def query(self, query: InteractionQuery) -> IndexPage:
        """Partition-scoped, filtered, newest first, at most ``query.page_size`` records."""
        ...

    async def list_records(
        self,
        *,
        limit: int,
        after: str | None = None,
        customer_id: str | None = None,
        principal_id: str | None = None,
    ) -> builtins.list[InteractionRecord]:
        """Bounded page ordered by ``interaction_id`` ascending, after ``after`` (lifecycle)."""
        ...


# --- in-memory twin ------------------------------------------------------------------------------


def _matches(doc: Mapping[str, Any], query: InteractionQuery) -> bool:
    if doc.get("customer_id") != query.customer_id or doc.get("domain_id") != query.domain_id:
        return False
    for field, wanted in (
        ("agent_id", query.agent_id),
        ("principal_id", query.principal_id),
        ("tool_id", query.tool_id),
    ):
        if wanted is not None and doc.get(field) != wanted:
            return False
    if query.data_asset_id is not None and query.data_asset_id not in (
        doc.get("data_asset_ids") or []
    ):
        return False
    if query.sensitivity_category is not None and query.sensitivity_category not in (
        doc.get("sensitivity_categories") or []
    ):
        return False
    if query.detected_category is not None and not any(
        isinstance(f, Mapping) and f.get("category") == query.detected_category
        for f in doc.get("findings_summary") or []
    ):
        return False
    captured = str(doc.get("captured_at"))
    if query.captured_from is not None and captured < format_timestamp(query.captured_from):
        return False
    return not (
        query.captured_before is not None and captured >= format_timestamp(query.captured_before)
    )


def _sort_key(doc: Mapping[str, Any]) -> tuple[str, str]:
    return (str(doc.get("captured_at")), str(doc.get("id")))


class InMemoryInteractionIndex:
    """In-memory :class:`IndexBackend`; documents are stored exactly as Cosmos would hold them."""

    def __init__(self) -> None:
        self.documents: dict[tuple[str, str, str], dict[str, Any]] = {}

    async def get(
        self, customer_id: str, domain_id: str, interaction_id: str
    ) -> InteractionRecord | None:
        doc = self.documents.get((customer_id, domain_id, interaction_id))
        return None if doc is None else record_from_document(doc)

    async def create(self, record: InteractionRecord) -> None:
        doc = index_document(record)
        key = (doc["customer_id"], doc["domain_id"], doc["id"])
        if key in self.documents:
            raise InteractionStoreError(INTERACTION_EXISTS)
        self.documents[key] = doc

    async def replace(self, record: InteractionRecord) -> None:
        doc = index_document(record)
        key = (doc["customer_id"], doc["domain_id"], doc["id"])
        if key not in self.documents:
            raise InteractionStoreError(INTERACTION_NOT_FOUND)
        self.documents[key] = doc

    async def delete(self, customer_id: str, domain_id: str, interaction_id: str) -> bool:
        return self.documents.pop((customer_id, domain_id, interaction_id), None) is not None

    async def query(self, query: InteractionQuery) -> IndexPage:
        position = decode_continuation(query)
        rows = sorted(
            (d for d in self.documents.values() if _matches(d, query)), key=_sort_key, reverse=True
        )
        if position is not None:
            if not (
                isinstance(position, list)
                and len(position) == 2
                and all(isinstance(p, str) for p in position)
            ):
                raise InteractionStoreError(INVALID_QUERY)
            after = (position[0], position[1])
            rows = [d for d in rows if _sort_key(d) < after]
        page = rows[: query.page_size]
        token = (
            encode_continuation(query, list(_sort_key(page[-1])))
            if len(rows) > query.page_size
            else None
        )
        return IndexPage(items=tuple(record_from_document(d) for d in page), continuation=token)

    async def list_records(
        self,
        *,
        limit: int,
        after: str | None = None,
        customer_id: str | None = None,
        principal_id: str | None = None,
    ) -> builtins.list[InteractionRecord]:
        _check_limit(limit)
        rows = sorted(
            (
                d
                for d in self.documents.values()
                if (after is None or d["id"] > after)
                and (customer_id is None or d["customer_id"] == customer_id)
                and (principal_id is None or d.get("principal_id") == principal_id)
            ),
            key=lambda d: str(d["id"]),
        )
        return [record_from_document(d) for d in rows[:limit]]


# --- Cosmos ------------------------------------------------------------------------------------


async def create_interaction_index_container(
    database: DatabaseProxy, container_id: str = DEFAULT_INTERACTION_INDEX_CONTAINER
) -> ContainerProxy:
    """Create (or open) the index container (MultiHash on customer, domain). Local/tests only."""
    return await database.create_container_if_not_exists(
        id=container_id,
        partition_key=PartitionKey(path=list(PARTITION_KEY_PATHS), kind="MultiHash"),
    )


def _raise_mapped(exc: Exception) -> NoReturn:
    if isinstance(exc, InteractionStoreError | NeuroSphereError):
        raise exc
    if isinstance(exc, CosmosHttpResponseError) and exc.status_code == 429:
        raise RateLimitedError(
            1, "interaction index throttled the request", reason="interaction_index_throttled"
        ) from None
    if isinstance(exc, CosmosHttpResponseError) and exc.status_code == 400:
        raise InteractionStoreError(INVALID_QUERY) from None
    raise InteractionStoreError(INTERACTION_STORE_UNAVAILABLE) from None


def _query_sql(query: InteractionQuery) -> tuple[str, builtins.list[dict[str, Any]]]:
    clauses = ["c.customer_id = @customer_id", "c.domain_id = @domain_id"]
    params: builtins.list[dict[str, Any]] = [
        {"name": "@customer_id", "value": query.customer_id},
        {"name": "@domain_id", "value": query.domain_id},
    ]
    for field, value in (
        ("agent_id", query.agent_id),
        ("principal_id", query.principal_id),
        ("tool_id", query.tool_id),
    ):
        if value is not None:
            clauses.append(f"c.{field} = @{field}")
            params.append({"name": f"@{field}", "value": value})
    if query.data_asset_id is not None:
        clauses.append("ARRAY_CONTAINS(c.data_asset_ids, @data_asset_id)")
        params.append({"name": "@data_asset_id", "value": query.data_asset_id})
    if query.sensitivity_category is not None:
        clauses.append("ARRAY_CONTAINS(c.sensitivity_categories, @sensitivity_category)")
        params.append({"name": "@sensitivity_category", "value": query.sensitivity_category})
    if query.detected_category is not None:
        clauses.append(
            "EXISTS(SELECT VALUE f FROM f IN c.findings_summary WHERE f.category = @detected)"
        )
        params.append({"name": "@detected", "value": query.detected_category})
    if query.captured_from is not None:
        clauses.append("c.captured_at >= @captured_from")
        params.append({"name": "@captured_from", "value": format_timestamp(query.captured_from)})
    if query.captured_before is not None:
        clauses.append("c.captured_at < @captured_before")
        params.append(
            {"name": "@captured_before", "value": format_timestamp(query.captured_before)}
        )
    # Only fixed clause text and parameter placeholders are interpolated.
    sql = (
        "SELECT * FROM c WHERE "  # noqa: S608
        + " AND ".join(clauses)
        + " ORDER BY c.captured_at DESC"
    )
    return sql, params


class CosmosInteractionIndex:
    """:class:`IndexBackend` on the ``interaction_index`` Cosmos container (azure-cosmos aio)."""

    def __init__(self, container: ContainerProxy) -> None:
        self._container = container

    @classmethod
    def from_client(
        cls,
        client: CosmosClient,
        *,
        database: str,
        container: str = DEFAULT_INTERACTION_INDEX_CONTAINER,
    ) -> CosmosInteractionIndex:
        return cls(client.get_database_client(database).get_container_client(container))

    async def get(
        self, customer_id: str, domain_id: str, interaction_id: str
    ) -> InteractionRecord | None:
        try:
            row = await self._container.read_item(
                item=interaction_id, partition_key=[customer_id, domain_id]
            )
        except CosmosResourceNotFoundError:
            return None
        except Exception as exc:
            _raise_mapped(exc)
        record = record_from_document(row)
        if record.customer_id.root != customer_id or record.domain_id.root != domain_id:
            return None
        return record

    async def create(self, record: InteractionRecord) -> None:
        try:
            await self._container.create_item(body=index_document(record))
        except CosmosResourceExistsError:
            raise InteractionStoreError(INTERACTION_EXISTS) from None
        except Exception as exc:
            _raise_mapped(exc)

    async def replace(self, record: InteractionRecord) -> None:
        body = index_document(record)
        try:
            await self._container.replace_item(item=body["id"], body=body)
        except CosmosResourceNotFoundError:
            raise InteractionStoreError(INTERACTION_NOT_FOUND) from None
        except Exception as exc:
            _raise_mapped(exc)

    async def delete(self, customer_id: str, domain_id: str, interaction_id: str) -> bool:
        try:
            await self._container.delete_item(
                item=interaction_id, partition_key=[customer_id, domain_id]
            )
        except CosmosResourceNotFoundError:
            return False
        except Exception as exc:
            _raise_mapped(exc)
        return True

    async def query(self, query: InteractionQuery) -> IndexPage:
        position = decode_continuation(query)
        if position is not None and not isinstance(position, str):
            raise InteractionStoreError(INVALID_QUERY)
        sql, params = _query_sql(query)
        try:
            pages = self._container.query_items(
                sql,
                parameters=params,
                partition_key=[query.customer_id, query.domain_id],
                max_item_count=query.page_size,
            ).by_page(position)
            try:
                page = await anext(pages)
            except StopAsyncIteration:
                return IndexPage(items=())
            rows = [row async for row in page]
            native = getattr(pages, "continuation_token", None)
        except Exception as exc:
            _raise_mapped(exc)
        # The service bounds a page by max_item_count; the slice is a second, local bound.
        records = tuple(record_from_document(row) for row in rows[: query.page_size])
        if any(
            r.customer_id.root != query.customer_id or r.domain_id.root != query.domain_id
            for r in records
        ):
            raise InteractionStoreError(INTERACTION_STORE_UNAVAILABLE)
        token = encode_continuation(query, native) if native else None
        return IndexPage(items=records, continuation=token)

    async def list_records(
        self,
        *,
        limit: int,
        after: str | None = None,
        customer_id: str | None = None,
        principal_id: str | None = None,
    ) -> builtins.list[InteractionRecord]:
        _check_limit(limit)
        clauses = ["IS_DEFINED(c.interaction_id)"]
        params: builtins.list[dict[str, Any]] = [{"name": "@limit", "value": limit}]
        if after is not None:
            clauses.append("c.id > @after")
            params.append({"name": "@after", "value": after})
        if customer_id is not None:
            clauses.append("c.customer_id = @customer_id")
            params.append({"name": "@customer_id", "value": customer_id})
        if principal_id is not None:
            clauses.append("c.principal_id = @principal_id")
            params.append({"name": "@principal_id", "value": principal_id})
        sql = (
            "SELECT TOP @limit * FROM c WHERE "  # noqa: S608
            + " AND ".join(clauses)
            + " ORDER BY c.id ASC"
        )
        try:
            rows = [row async for row in self._container.query_items(sql, parameters=params)]
        except Exception as exc:
            _raise_mapped(exc)
        return [record_from_document(row) for row in rows]
