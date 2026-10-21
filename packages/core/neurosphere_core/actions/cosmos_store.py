"""Cosmos NoSQL intent store and execution-control store (azure-cosmos aio).

Intent container: hierarchical partition key ``/customer_id``, ``/domain_id`` (``MultiHash``,
delta D7). Documents per partition:

* ``doc_type = action_intent``, ``id = <intent_id>``: :meth:`StoredIntent.to_document` plus the
  query fields ``state``, ``sort_key`` (creation order) and ``due_key`` (fixed-width ``due_at``,
  absent when nothing is due). The Cosmos ``_etag`` is the store ETag.
* ``doc_type = idempotency``, ``id = idem-<sha256(principal_id, key)>`` in the per-customer
  partition ``(customer_id, "__idempotency__")``: ``payload_digest`` and the intent's address.
  It holds no raw principal id or key.

Idempotency without stored procedures (the vNext emulator has none, G12): the lookup document is
created FIRST with create-only semantics. A 409 means the scope exists: the digest is compared
(reuse -> ``idempotency_key_reused``) and the ORIGINAL intent is read and returned. If the
original intent document is missing (a crash between the two creates), it is recreated under
the lookup's intent id, so a retry repairs the pair instead of creating a second intent.

Replace is ``IfNotModified`` on ``_etag``: 412 or 404 -> ``stale_version`` ``intent_modified``.
Queries are parameterized; field names are fixed. Outages -> ``dependency_transient``
(``intent_store_unavailable``); 429 -> ``rate_limited``; a document that fails validation ->
``dependency_transient`` with ``upstream_invalid``. Messages never echo SDK text or documents.

Execution-control container: partition key ``/customer_id``, one document per customer
(``id = execution_control``), written with ``upsert_item`` (last write wins). Every read
failure other than "absent" raises ``dependency_transient`` so callers fail CLOSED.
"""

from __future__ import annotations

import builtins
from collections.abc import Mapping, Sequence
from datetime import datetime
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
from pydantic import ValidationError

from neurosphere_core.actions.control import ExecutionControlState, control_unavailable
from neurosphere_core.actions.models import (
    CreateOutcome,
    StoredIntent,
    format_timestamp,
    idempotency_lookup_id,
)
from neurosphere_core.actions.store import (
    DEFAULT_PAGE_SIZE,
    check_limit,
    decode_cursor,
    encode_cursor,
    idempotency_reused,
    sort_key,
    stale_intent,
    store_unavailable,
)
from neurosphere_core.audit.canonical import digests_equal
from neurosphere_core.errors import (
    DependencyTransientError,
    NeuroSphereError,
    RateLimitedError,
)
from neurosphere_core.paging import Page

__all__ = [
    "CONTROL_PARTITION_KEY_PATH",
    "DEFAULT_CONTROL_CONTAINER",
    "DEFAULT_INTENT_CONTAINER",
    "IDEMPOTENCY_PARTITION",
    "INTENT_PARTITION_KEY_PATHS",
    "CosmosExecutionControl",
    "CosmosIntentStore",
    "create_execution_control_container",
    "create_intent_container",
]

DEFAULT_INTENT_CONTAINER: Final = "action_intents"
DEFAULT_CONTROL_CONTAINER: Final = "action_execution_control"
INTENT_PARTITION_KEY_PATHS: Final = ("/customer_id", "/domain_id")
CONTROL_PARTITION_KEY_PATH: Final = "/customer_id"
IDEMPOTENCY_PARTITION: Final = "__idempotency__"
INTENT_DOC_TYPE: Final = "action_intent"
IDEMPOTENCY_DOC_TYPE: Final = "idempotency"
CONTROL_DOC_ID: Final = "execution_control"
_QUERY_FIELDS: Final = frozenset({"id", "doc_type", "state", "sort_key", "due_key"})


async def create_intent_container(
    database: DatabaseProxy, container_id: str = DEFAULT_INTENT_CONTAINER
) -> ContainerProxy:
    """Create (or open) the intent container with the hierarchical key. New containers only."""
    return await database.create_container_if_not_exists(
        id=container_id,
        partition_key=PartitionKey(path=list(INTENT_PARTITION_KEY_PATHS), kind="MultiHash"),
    )


async def create_execution_control_container(
    database: DatabaseProxy, container_id: str = DEFAULT_CONTROL_CONTAINER
) -> ContainerProxy:
    return await database.create_container_if_not_exists(
        id=container_id, partition_key=PartitionKey(path=CONTROL_PARTITION_KEY_PATH)
    )


def _raise_mapped(exc: Exception) -> NoReturn:
    if isinstance(exc, NeuroSphereError):
        raise exc
    if isinstance(exc, CosmosHttpResponseError) and exc.status_code == 429:
        raise RateLimitedError(1, "intent store throttled the request") from exc
    raise store_unavailable() from exc


def _invalid() -> DependencyTransientError:
    return DependencyTransientError(
        "stored intent failed validation", reason="intent_record_invalid", upstream_invalid=True
    )


def _strip(document: Mapping[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in document.items() if not k.startswith("_") and k not in _QUERY_FIELDS}


def _from_row(row: Mapping[str, Any]) -> StoredIntent:
    try:
        return StoredIntent.from_document(_strip(row), etag=str(row.get("_etag", "")) or None)
    except ValidationError as exc:
        raise _invalid() from exc


class CosmosIntentStore:
    """:class:`neurosphere_core.actions.store.IntentStore` on one Cosmos container."""

    def __init__(self, container: ContainerProxy) -> None:
        self._container = container

    @classmethod
    def from_client(
        cls,
        client: CosmosClient,
        *,
        database: str,
        container: str = DEFAULT_INTENT_CONTAINER,
    ) -> CosmosIntentStore:
        return cls(client.get_database_client(database).get_container_client(container))

    # -- documents ------------------------------------------------------------------------------

    @staticmethod
    def _intent_body(stored: StoredIntent) -> dict[str, Any]:
        body = stored.to_document()
        body["id"] = stored.intent_id
        body["doc_type"] = INTENT_DOC_TYPE
        body["state"] = stored.state
        body["sort_key"] = sort_key(stored)
        if stored.due_at is not None:
            body["due_key"] = format_timestamp(stored.due_at)
        return body

    async def _read_intent(
        self, customer_id: str, domain_id: str, intent_id: str
    ) -> StoredIntent | None:
        try:
            row = await self._container.read_item(
                item=intent_id, partition_key=[customer_id, domain_id]
            )
        except CosmosResourceNotFoundError:
            return None
        except Exception as exc:
            _raise_mapped(exc)
        if row.get("doc_type") != INTENT_DOC_TYPE:
            return None
        return _from_row(row)

    async def _read_lookup(self, customer_id: str, lookup_id: str) -> dict[str, Any] | None:
        try:
            return dict(
                await self._container.read_item(
                    item=lookup_id, partition_key=[customer_id, IDEMPOTENCY_PARTITION]
                )
            )
        except CosmosResourceNotFoundError:
            return None
        except Exception as exc:
            _raise_mapped(exc)

    # -- port -----------------------------------------------------------------------------------

    async def create(self, stored: StoredIntent) -> CreateOutcome:
        lookup_id = idempotency_lookup_id(stored.principal_id, stored.intent.idempotency_key)
        lookup = {
            "id": lookup_id,
            "doc_type": IDEMPOTENCY_DOC_TYPE,
            "customer_id": stored.customer_id,
            "domain_id": IDEMPOTENCY_PARTITION,
            "payload_digest": stored.payload_digest,
            "intent_domain_id": stored.domain_id,
            "intent_id": stored.intent_id,
        }
        try:
            await self._container.create_item(body=lookup)
        except CosmosResourceExistsError:
            return await self._replay(stored, lookup_id)
        except Exception as exc:
            _raise_mapped(exc)
        return CreateOutcome(stored=await self._create_intent(stored), created=True)

    async def _create_intent(self, stored: StoredIntent) -> StoredIntent:
        try:
            row = await self._container.create_item(body=self._intent_body(stored))
        except CosmosResourceExistsError:
            found = await self._read_intent(stored.customer_id, stored.domain_id, stored.intent_id)
            if found is None:
                raise store_unavailable() from None
            return found
        except Exception as exc:
            _raise_mapped(exc)
        return _from_row(row)

    async def _replay(self, stored: StoredIntent, lookup_id: str) -> CreateOutcome:
        lookup = await self._read_lookup(stored.customer_id, lookup_id)
        if lookup is None:  # deleted between the 409 and the read; treat as transient
            raise store_unavailable()
        digest = lookup.get("payload_digest")
        if not isinstance(digest, str) or not digests_equal(digest, stored.payload_digest):
            raise idempotency_reused()
        domain_id = lookup.get("intent_domain_id")
        intent_id = lookup.get("intent_id")
        if not isinstance(domain_id, str) or not isinstance(intent_id, str):
            raise _invalid()
        original = await self._read_intent(stored.customer_id, domain_id, intent_id)
        if original is not None:
            return CreateOutcome(stored=original, created=False)
        # Crash repair: the lookup exists but its intent was never written.
        repaired = stored.to_document()
        repaired["intent"]["intent_id"] = intent_id
        try:
            rebuilt = StoredIntent.from_document(repaired, etag=None)
        except ValidationError as exc:
            raise _invalid() from exc
        return CreateOutcome(stored=await self._create_intent(rebuilt), created=True)

    async def get(self, customer_id: str, domain_id: str, intent_id: str) -> StoredIntent | None:
        return await self._read_intent(customer_id, domain_id, intent_id)

    async def find_by_idempotency_key(
        self, principal_id: str, idempotency_key: str, *, customer_id: str
    ) -> StoredIntent | None:
        lookup = await self._read_lookup(
            customer_id, idempotency_lookup_id(principal_id, idempotency_key)
        )
        if lookup is None:
            return None
        domain_id = lookup.get("intent_domain_id")
        intent_id = lookup.get("intent_id")
        if not isinstance(domain_id, str) or not isinstance(intent_id, str):
            raise _invalid()
        return await self._read_intent(customer_id, domain_id, intent_id)

    async def replace(self, stored: StoredIntent, *, if_match: str) -> StoredIntent:
        body = self._intent_body(stored)
        try:
            row = await self._container.replace_item(
                item=body["id"],
                body=body,
                etag=if_match,
                match_condition=MatchConditions.IfNotModified,
            )
        except (CosmosAccessConditionFailedError, CosmosResourceNotFoundError) as exc:
            raise stale_intent() from exc
        except Exception as exc:
            _raise_mapped(exc)
        return _from_row(row)

    async def _query(
        self,
        sql: str,
        parameters: builtins.list[dict[str, Any]],
        *,
        partition_key: builtins.list[str] | None,
    ) -> builtins.list[StoredIntent]:
        try:
            if partition_key is None:
                rows = [
                    row async for row in self._container.query_items(sql, parameters=parameters)
                ]
            else:
                rows = [
                    row
                    async for row in self._container.query_items(
                        sql, parameters=parameters, partition_key=partition_key
                    )
                ]
        except Exception as exc:
            _raise_mapped(exc)
        return [_from_row(row) for row in rows]

    async def list(
        self,
        customer_id: str,
        domain_id: str,
        *,
        state: str | None = None,
        cursor: str | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> Page[StoredIntent]:
        check_limit(limit)
        clauses = ["c.doc_type = @doc_type"]
        params: builtins.list[dict[str, Any]] = [
            {"name": "@doc_type", "value": INTENT_DOC_TYPE},
            {"name": "@limit", "value": limit + 1},
        ]
        if state is not None:
            clauses.append("c.state = @state")
            params.append({"name": "@state", "value": state})
        if cursor is not None:
            clauses.append("c.sort_key < @after")
            params.append({"name": "@after", "value": decode_cursor(cursor)})
        # Only fixed clause text and parameter placeholders are interpolated.
        sql = (
            "SELECT TOP @limit * FROM c WHERE "  # noqa: S608
            + " AND ".join(clauses)
            + " ORDER BY c.sort_key DESC"
        )
        rows = await self._query(sql, params, partition_key=[customer_id, domain_id])
        page = rows[:limit]
        next_cursor = encode_cursor(sort_key(page[-1])) if len(rows) > limit else None
        return Page[StoredIntent](items=tuple(page), next_cursor=next_cursor)

    async def list_in_states(
        self,
        states: Sequence[str],
        *,
        due_before: datetime | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> builtins.list[StoredIntent]:
        check_limit(limit)
        clauses = ["c.doc_type = @doc_type", "ARRAY_CONTAINS(@states, c.state)"]
        params: builtins.list[dict[str, Any]] = [
            {"name": "@doc_type", "value": INTENT_DOC_TYPE},
            {"name": "@states", "value": builtins.list(states)},
            {"name": "@limit", "value": limit},
        ]
        if due_before is not None:
            clauses.append("IS_DEFINED(c.due_key) AND c.due_key <= @due")
            params.append({"name": "@due", "value": format_timestamp(due_before)})
        sql = (
            "SELECT TOP @limit * FROM c WHERE "  # noqa: S608
            + " AND ".join(clauses)
            + " ORDER BY c.sort_key ASC"
        )
        return await self._query(sql, params, partition_key=None)


class CosmosExecutionControl:
    """:class:`neurosphere_core.actions.control.ExecutionControl` on Cosmos (fail closed)."""

    def __init__(self, container: ContainerProxy) -> None:
        self._container = container

    @classmethod
    def from_client(
        cls,
        client: CosmosClient,
        *,
        database: str,
        container: str = DEFAULT_CONTROL_CONTAINER,
    ) -> CosmosExecutionControl:
        return cls(client.get_database_client(database).get_container_client(container))

    async def get(self, customer_id: str) -> ExecutionControlState:
        try:
            row = await self._container.read_item(item=CONTROL_DOC_ID, partition_key=customer_id)
        except CosmosResourceNotFoundError:
            return ExecutionControlState(customer_id=customer_id)
        except Exception as exc:
            raise control_unavailable() from exc
        try:
            state = ExecutionControlState.model_validate(
                {k: v for k, v in row.items() if not k.startswith("_") and k != "id"}
            )
        except ValidationError as exc:
            raise control_unavailable() from exc
        if state.customer_id != customer_id:
            raise control_unavailable()
        return state

    async def set(
        self,
        customer_id: str,
        *,
        disabled: bool,
        reason: str | None,
        changed_by: str,
        now: datetime,
    ) -> ExecutionControlState:
        state = ExecutionControlState(
            customer_id=customer_id,
            disabled=disabled,
            reason=reason,
            changed_by=changed_by,
            changed_at=now,
        )
        try:
            await self._container.upsert_item(
                body={"id": CONTROL_DOC_ID, **state.model_dump(mode="json")}
            )
        except Exception as exc:
            raise control_unavailable() from exc
        return state
