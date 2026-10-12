"""Cosmos DB NoSQL implementation of the audit storage port.

Container layout: partition key path ``/chain_id``. Per chain partition there is one record
document per sequence (``id = rec-<seq>``, ``doc_type = audit_record``) and one tail pointer
(``id = tail``, ``doc_type = audit_tail``).

SDK surface used, by design: ``create_item`` (records and the first tail), ``read_item``,
``query_items`` (parameterized, single partition) and ``replace_item`` with an ``IfNotModified``
ETag condition for the TAIL ONLY. ``upsert_item``, ``patch_item`` and ``delete_item`` are never
called (asserted by ``packages/core/tests/audit/test_immutability.py``).

Immutability here is by API surface. The Cosmos emulator enforces no auth and cannot prove
service-side immutability; that is an open emulator delta (PRP-06 C10, gate G12).

The container is built from a client the caller injects (``neurosphere_core.clients``
factories own client construction and lifetime).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

from azure.core import MatchConditions
from azure.cosmos.aio import ContainerProxy, CosmosClient
from azure.cosmos.exceptions import (
    CosmosAccessConditionFailedError,
    CosmosResourceExistsError,
    CosmosResourceNotFoundError,
)

from neurosphere_core.audit.chain import TailPointer
from neurosphere_core.audit.store import (
    RECORD_DOC_TYPE,
    TAIL_DOC_TYPE,
    TAIL_ID,
    SequenceTakenError,
    StoredTail,
    TailConflictError,
    record_document_id,
)
from neurosphere_core.clients import translating

PARTITION_KEY_PATH: Final = "/chain_id"
_STORAGE_FIELDS: Final = frozenset({"id", "doc_type"})
_RANGE_QUERY: Final = (
    "SELECT * FROM c WHERE c.doc_type = @doc_type AND c.sequence >= @start AND c.sequence < @stop"
)


def _strip(document: Mapping[str, Any]) -> dict[str, Any]:
    """Drop Cosmos system properties (``_rid``, ``_etag``...) and storage-only fields."""
    return {k: v for k, v in document.items() if not k.startswith("_") and k not in _STORAGE_FIELDS}


class CosmosAuditStore:
    def __init__(self, container: ContainerProxy) -> None:
        self._container = container

    @classmethod
    def from_client(
        cls, client: CosmosClient, *, database: str, container: str
    ) -> CosmosAuditStore:
        return cls(client.get_database_client(database).get_container_client(container))

    async def read_tail(self, chain_id: str) -> StoredTail | None:
        with translating():
            try:
                doc = await self._container.read_item(item=TAIL_ID, partition_key=chain_id)
            except CosmosResourceNotFoundError:
                return None
        tail = TailPointer(
            chain_id=doc["chain_id"], sequence=doc["sequence"], record_hash=doc["record_hash"]
        )
        return StoredTail(tail, str(doc["_etag"]))

    async def create_record(
        self, chain_id: str, sequence: int, document: Mapping[str, Any]
    ) -> None:
        if document.get("chain_id") != chain_id or document.get("sequence") != sequence:
            raise ValueError("document chain_id/sequence do not match the target slot")
        body = {**document, "id": record_document_id(sequence), "doc_type": RECORD_DOC_TYPE}
        with translating():
            try:
                await self._container.create_item(body=body)
            except CosmosResourceExistsError as exc:
                raise SequenceTakenError(body["id"]) from exc

    async def read_record(self, chain_id: str, sequence: int) -> dict[str, Any] | None:
        with translating():
            try:
                doc = await self._container.read_item(
                    item=record_document_id(sequence), partition_key=chain_id
                )
            except CosmosResourceNotFoundError:
                return None
        return _strip(doc)

    async def write_tail(self, tail: TailPointer, *, if_match: str | None) -> None:
        body = {**tail.model_dump(), "id": TAIL_ID, "doc_type": TAIL_DOC_TYPE}
        with translating():
            try:
                if if_match is None:
                    await self._container.create_item(body=body)
                else:
                    await self._container.replace_item(
                        item=TAIL_ID,
                        body=body,
                        etag=if_match,
                        match_condition=MatchConditions.IfNotModified,
                    )
            except (CosmosResourceExistsError, CosmosAccessConditionFailedError) as exc:
                raise TailConflictError(tail.chain_id) from exc

    async def query_range(self, chain_id: str, start: int, stop: int) -> list[dict[str, Any]]:
        # No ORDER BY: the vNext emulator lacks range indexes (G12 delta); sort client-side.
        found: list[dict[str, Any]] = []
        with translating():
            pager = self._container.query_items(
                query=_RANGE_QUERY,
                parameters=[
                    {"name": "@doc_type", "value": RECORD_DOC_TYPE},
                    {"name": "@start", "value": start},
                    {"name": "@stop", "value": stop},
                ],
                partition_key=chain_id,
            )
            async for doc in pager:
                found.append(_strip(doc))
        found.sort(key=lambda d: d.get("sequence", -1))
        return found
