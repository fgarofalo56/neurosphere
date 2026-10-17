"""Cosmos NoSQL catalog repository (azure-cosmos aio) over the shared engine (PRP-10 item 1).

* Partition key: ONLY from ``neurosphere_core.catalog.partitioning``. ``partition_key_definition``
  builds the container key (hierarchical ``MultiHash`` or flat) from a resolved shape, and the
  engine writes the matching fields onto every document.
* Concurrency: the engine compares the contract ``etag`` and ALSO sends the stored document's
  Cosmos ``_etag`` as an ``If-Match`` precondition, so a race between read and replace fails
  with 412 and is surfaced as ``StaleVersionError``.
* Reads: ``build_sql`` turns a ``Query`` into parameterized SQL. Field names come from an
  allowlist; every value (including the scope's cloud, customer and domain list) is a
  parameter. Queries are cross-partition and bounded by ``TOP @limit``; the emulator has no
  composite or range-index tuning, so only single-field ``ORDER BY`` is used.
* Container creation is only ever for NEW containers (hierarchical keys cannot be converted in
  place; ADR-0005).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from azure.core import MatchConditions
from azure.cosmos import PartitionKey
from azure.cosmos.aio import ContainerProxy, DatabaseProxy
from azure.cosmos.exceptions import (
    CosmosAccessConditionFailedError,
    CosmosHttpResponseError,
    CosmosResourceExistsError,
    CosmosResourceNotFoundError,
)

from neurosphere_core.catalog.partitioning import (
    DEFAULT_SHARD_COUNT,
    PartitionKeyShape,
    partition_key_paths,
)
from neurosphere_core.catalog.repo.backend import (
    FIELDS,
    DocConflictError,
    DocPreconditionFailedError,
    Query,
)
from neurosphere_core.catalog.repo.engine import CatalogEngine
from neurosphere_core.errors.taxonomy import DependencyTransientError, RateLimitedError

_SYSTEM_PROPERTIES = ("_rid", "_self", "_etag", "_attachments", "_ts")
_TRANSIENT = frozenset({408, 500, 502, 503, 504})


def partition_key_definition(shape: PartitionKeyShape) -> PartitionKey:
    """Container key definition for ``shape``: hierarchical (``MultiHash``) or flat."""
    paths = partition_key_paths(shape)
    if len(paths) == 1:
        return PartitionKey(path=paths[0])
    return PartitionKey(path=list(paths), kind="MultiHash")


async def create_catalog_container(
    database: DatabaseProxy, container_id: str, shape: PartitionKeyShape
) -> ContainerProxy:
    """Create (or open) the catalog container with the key definition of ``shape``.

    ``shape`` must be the RESOLVED shape (``resolve_shape``): this function never decides
    whether hierarchical keys are available. Use only for new containers.
    """
    return await database.create_container_if_not_exists(
        id=container_id, partition_key=partition_key_definition(shape)
    )


def build_sql(query: Query) -> tuple[str, list[dict[str, Any]]]:
    """Parameterized SQL for ``query``. No caller-supplied text reaches the statement."""
    params: list[dict[str, Any]] = []

    def param(value: Any) -> str:
        name = f"@p{len(params)}"
        params.append({"name": name, "value": value})
        return name

    def column(name: str) -> str:
        if name not in FIELDS:  # defence in depth: Query already validated
            raise ValueError(f"field {name!r} is not allowlisted")
        return f"c.{name}"

    clauses = [
        f"c.doc_type = {param(query.doc_type)}",
        f"c.cloud = {param(query.scope.cloud)}",
        f"c.customer_id = {param(query.scope.customer_id)}",
    ]
    if query.scope.domains is not None:
        clauses.append(f"ARRAY_CONTAINS({param(list(query.scope.domains))}, c.domain_id)")
    clauses.extend(f"{column(field)} = {param(value)}" for field, value in query.eq)
    clauses.extend(
        f"ARRAY_CONTAINS({param(list(values))}, {column(field)})" for field, values in query.any_of
    )
    if query.either:
        group = " OR ".join(f"{column(field)} = {param(value)}" for field, value in query.either)
        clauses.append(f"({group})")
    if query.order is not None and query.after is not None:
        op = "<" if query.descending else ">"
        clauses.append(f"{column(query.order)} {op} {param(query.after)}")
    limit = param(query.limit)
    # Only allowlisted column names and parameter placeholders are interpolated.
    sql = f"SELECT TOP {limit} * FROM c WHERE " + " AND ".join(clauses)  # noqa: S608
    if query.order is not None:
        sql += f" ORDER BY {column(query.order)} {'DESC' if query.descending else 'ASC'}"
    return sql, params


def _translate(exc: CosmosHttpResponseError) -> Exception:
    status = exc.status_code
    if status == 429:
        return RateLimitedError(1)
    if status in _TRANSIENT:
        return DependencyTransientError(reason="cosmos_unavailable")
    return exc


class CosmosBackend:
    """``DocBackend`` over one Cosmos container."""

    def __init__(self, container: ContainerProxy) -> None:
        self._container = container

    async def query(self, query: Query) -> Sequence[dict[str, Any]]:
        sql, params = build_sql(query)
        try:
            return [row async for row in self._container.query_items(sql, parameters=params)]
        except CosmosHttpResponseError as exc:
            raise _translate(exc) from exc

    async def insert(self, doc: dict[str, Any]) -> dict[str, Any]:
        try:
            return dict(await self._container.create_item(doc))
        except CosmosResourceExistsError as exc:
            raise DocConflictError from exc
        except CosmosHttpResponseError as exc:
            raise _translate(exc) from exc

    async def replace(self, doc: dict[str, Any], if_match: str) -> dict[str, Any]:
        clean = {k: v for k, v in doc.items() if k not in _SYSTEM_PROPERTIES}
        try:
            return dict(
                await self._container.replace_item(
                    clean["id"],
                    clean,
                    etag=if_match,
                    match_condition=MatchConditions.IfNotModified,
                )
            )
        except (CosmosAccessConditionFailedError, CosmosResourceNotFoundError) as exc:
            raise DocPreconditionFailedError from exc
        except CosmosHttpResponseError as exc:
            raise _translate(exc) from exc


class CosmosCatalogRepository(CatalogEngine):
    """``CatalogRepository`` on a Cosmos container created for ``shape``.

    ``shape`` must equal the shape the container was created with (the document key fields
    must match the container's key paths).
    """

    def __init__(
        self,
        container: ContainerProxy,
        shape: PartitionKeyShape = PartitionKeyShape.FLAT_DOMAIN,
        *,
        shard_count: int = DEFAULT_SHARD_COUNT,
    ) -> None:
        super().__init__(CosmosBackend(container), shape, shard_count=shard_count)
