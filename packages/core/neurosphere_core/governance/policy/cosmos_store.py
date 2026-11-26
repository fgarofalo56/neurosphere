"""Cosmos NoSQL policy engine stores (azure-cosmos aio). Owner module of the PRP-102 containers
``policy_definitions``, ``policy_violations`` and ``policy_exceptions`` (partition key
``/customer_id`` + ``/domain_id``, MultiHash).

The store logic is the shared ``Document*Store`` code in :mod:`.store`; this module supplies
:class:`CosmosDocumentBackend`:

* create is ``create_item`` (409 -> :class:`~.store.DocumentExistsError`); replace is
  ``replace_item`` with the ETag and ``IfNotModified`` (412 or 404 ->
  :class:`~.store.DocumentConflictError`);
* a :class:`~.store.DocumentQuery` becomes parameterized SQL assembled ONLY from the fixed
  clause constants below (one per queryable field); values are always ``@`` parameters, never
  text. ORDER BY names one property (``c.sort_key``): Cosmos refuses a multi-property ORDER BY
  without a composite index, and none is declared;
* 429 -> ``rate_limited``; other failures -> ``dependency_transient``
  (``govpolicy_store_unavailable``); messages never echo SDK text or documents.

Bindings use :class:`~neurosphere_core.admin.cosmos_store.CosmosAdminConfigRepository`.
"""

from __future__ import annotations

import builtins
from collections.abc import Mapping
from typing import Any, Final, NoReturn

from azure.core import MatchConditions
from azure.cosmos import PartitionKey
from azure.cosmos.aio import ContainerProxy, CosmosClient, DatabaseProxy
from azure.cosmos.exceptions import (
    CosmosAccessConditionFailedError,
    CosmosHttpResponseError,
    CosmosResourceExistsError,
    CosmosResourceNotFoundError,
)

from neurosphere_core.admin.cosmos_store import CosmosAdminConfigRepository
from neurosphere_core.errors import NeuroSphereError, RateLimitedError
from neurosphere_core.governance.policy.store import (
    GOVPOLICY_THROTTLED,
    PARTITION_KEY_PATHS,
    POLICY_DEFINITIONS_CONTAINER,
    POLICY_EXCEPTIONS_CONTAINER,
    POLICY_VIOLATIONS_CONTAINER,
    BindingStore,
    DocumentConflictError,
    DocumentEvaluationStatusStore,
    DocumentExceptionStore,
    DocumentExistsError,
    DocumentPolicyDefinitionStore,
    DocumentQuery,
    DocumentViolationStore,
    store_unavailable,
)

__all__ = [
    "CosmosBindingStore",
    "CosmosDocumentBackend",
    "CosmosEvaluationStatusStore",
    "CosmosExceptionStore",
    "CosmosPolicyDefinitionStore",
    "CosmosViolationStore",
    "build_query",
    "create_policy_containers",
]

#: One fixed clause per equality field (the closed list ``QUERY_EQ_FIELDS``).
_EQ_CLAUSES: Final[Mapping[str, str]] = {
    "doc_kind": "c.doc_kind = @doc_kind",
    "policy_id": "c.policy_id = @policy_id",
    "policy_version": "c.policy_version = @policy_version",
    "status": "c.status = @status",
    "superseded": "c.superseded = @superseded",
    "rule_id": "c.rule_id = @rule_id",
    "dedup_key": "c.dedup_key = @dedup_key",
    "subject_id": "c.subject_id = @subject_id",
    "severity": "c.severity = @severity",
    "violation_id": "c.violation_id = @violation_id",
}
#: One fixed clause per membership field (``QUERY_IN_FIELDS``).
_IN_CLAUSES: Final[Mapping[str, tuple[str, str]]] = {
    "domain_id": ("ARRAY_CONTAINS(@domain_id_any, c.domain_id)", "@domain_id_any"),
    "status": ("ARRAY_CONTAINS(@status_any, c.status)", "@status_any"),
}
_SELECT: Final = "SELECT TOP @limit * FROM c WHERE c.customer_id = @customer_id"
_AFTER_ASC: Final = "c.sort_key > @after"
_AFTER_DESC: Final = "c.sort_key < @after"
_ORDER_ASC: Final = " ORDER BY c.sort_key ASC"
_ORDER_DESC: Final = " ORDER BY c.sort_key DESC"


def build_query(query: DocumentQuery) -> tuple[str, builtins.list[dict[str, Any]]]:
    """SQL and parameters for ``query``: fixed clause constants joined by AND, values as
    parameters. Exposed for tests; nothing else builds SQL for these containers."""
    clauses = [_SELECT]
    params: builtins.list[dict[str, Any]] = [
        {"name": "@limit", "value": query.limit},
        {"name": "@customer_id", "value": query.customer_id},
    ]
    for name, value in query.equals:
        clauses.append(_EQ_CLAUSES[name])
        params.append({"name": "@" + name, "value": value})
    for name, values in query.any_of:
        clause, param = _IN_CLAUSES[name]
        clauses.append(clause)
        params.append({"name": param, "value": list(values)})
    if query.after is not None:
        clauses.append(_AFTER_DESC if query.descending else _AFTER_ASC)
        params.append({"name": "@after", "value": query.after})
    sql = " AND ".join(clauses) + (_ORDER_DESC if query.descending else _ORDER_ASC)
    return sql, params


async def create_policy_containers(
    database: DatabaseProxy,
    containers: tuple[str, ...] = (
        POLICY_DEFINITIONS_CONTAINER,
        POLICY_VIOLATIONS_CONTAINER,
        POLICY_EXCEPTIONS_CONTAINER,
    ),
) -> builtins.list[ContainerProxy]:
    """Create (or open) the three containers (MultiHash ``/customer_id`` + ``/domain_id``)."""
    return [
        await database.create_container_if_not_exists(
            id=name, partition_key=PartitionKey(path=list(PARTITION_KEY_PATHS), kind="MultiHash")
        )
        for name in containers
    ]


def _raise_mapped(exc: Exception) -> NoReturn:
    if isinstance(exc, NeuroSphereError):
        raise exc
    if isinstance(exc, CosmosHttpResponseError) and exc.status_code == 429:
        raise RateLimitedError(
            1, "governance policy store throttled the request", reason=GOVPOLICY_THROTTLED
        ) from exc
    raise store_unavailable() from exc


class CosmosDocumentBackend:
    """:class:`~.store.DocumentBackend` on one Cosmos container."""

    def __init__(self, container: ContainerProxy) -> None:
        self._container = container

    @classmethod
    def from_client(
        cls, client: CosmosClient, *, database: str, container: str
    ) -> CosmosDocumentBackend:
        return cls(client.get_database_client(database).get_container_client(container))

    async def create(self, document: Mapping[str, Any]) -> dict[str, Any]:
        try:
            return dict(await self._container.create_item(body=dict(document)))
        except CosmosResourceExistsError:
            raise DocumentExistsError from None
        except Exception as exc:
            _raise_mapped(exc)

    async def read(self, customer_id: str, domain_id: str, doc_id: str) -> dict[str, Any] | None:
        try:
            row = await self._container.read_item(
                item=doc_id, partition_key=[customer_id, domain_id]
            )
        except CosmosResourceNotFoundError:
            return None
        except Exception as exc:
            _raise_mapped(exc)
        return dict(row)

    async def replace(self, document: Mapping[str, Any], *, if_match: str) -> dict[str, Any]:
        try:
            row = await self._container.replace_item(
                item=str(document["id"]),
                body=dict(document),
                etag=if_match,
                match_condition=MatchConditions.IfNotModified,
            )
        except (CosmosAccessConditionFailedError, CosmosResourceNotFoundError):
            raise DocumentConflictError from None
        except Exception as exc:
            _raise_mapped(exc)
        return dict(row)

    async def upsert(self, document: Mapping[str, Any]) -> dict[str, Any]:
        try:
            return dict(await self._container.upsert_item(body=dict(document)))
        except Exception as exc:
            _raise_mapped(exc)

    async def query(self, query: DocumentQuery) -> builtins.list[dict[str, Any]]:
        sql, params = build_query(query)
        try:
            if query.domain_id is None:
                rows = [row async for row in self._container.query_items(sql, parameters=params)]
            else:
                rows = [
                    row
                    async for row in self._container.query_items(
                        sql,
                        parameters=params,
                        partition_key=[query.customer_id, query.domain_id],
                    )
                ]
        except Exception as exc:
            _raise_mapped(exc)
        rows = [dict(r) for r in rows]
        # Cosmos already orders by the one ORDER BY term; re-sort defensively (stable, same key).
        rows.sort(key=lambda r: str(r.get("sort_key", "")), reverse=query.descending)
        return rows


class CosmosPolicyDefinitionStore(DocumentPolicyDefinitionStore):
    """Policy versions on ``policy_definitions``."""

    def __init__(self, container: ContainerProxy) -> None:
        super().__init__(CosmosDocumentBackend(container))

    @classmethod
    def from_client(
        cls,
        client: CosmosClient,
        *,
        database: str,
        container: str = POLICY_DEFINITIONS_CONTAINER,
    ) -> CosmosPolicyDefinitionStore:
        return cls(client.get_database_client(database).get_container_client(container))


class CosmosEvaluationStatusStore(DocumentEvaluationStatusStore):
    """Run-status documents on ``policy_definitions`` (``doc_kind: evaluation_status``)."""

    def __init__(self, container: ContainerProxy) -> None:
        super().__init__(CosmosDocumentBackend(container))

    @classmethod
    def from_client(
        cls,
        client: CosmosClient,
        *,
        database: str,
        container: str = POLICY_DEFINITIONS_CONTAINER,
    ) -> CosmosEvaluationStatusStore:
        return cls(client.get_database_client(database).get_container_client(container))


class CosmosViolationStore(DocumentViolationStore):
    """Violations on ``policy_violations``."""

    def __init__(self, container: ContainerProxy) -> None:
        super().__init__(CosmosDocumentBackend(container))

    @classmethod
    def from_client(
        cls,
        client: CosmosClient,
        *,
        database: str,
        container: str = POLICY_VIOLATIONS_CONTAINER,
    ) -> CosmosViolationStore:
        return cls(client.get_database_client(database).get_container_client(container))


class CosmosExceptionStore(DocumentExceptionStore):
    """Exceptions on ``policy_exceptions``."""

    def __init__(self, container: ContainerProxy) -> None:
        super().__init__(CosmosDocumentBackend(container))

    @classmethod
    def from_client(
        cls,
        client: CosmosClient,
        *,
        database: str,
        container: str = POLICY_EXCEPTIONS_CONTAINER,
    ) -> CosmosExceptionStore:
        return cls(client.get_database_client(database).get_container_client(container))


class CosmosBindingStore(BindingStore):
    """:class:`~.store.BindingStore` over the Cosmos ``admin_config`` repository."""

    def __init__(self, repository: CosmosAdminConfigRepository) -> None:
        super().__init__(repository)
