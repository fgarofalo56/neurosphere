"""Cosmos DB NoSQL register store. Partition key ``/deployment_id``.

Documents: ``doc_type=register_row`` (id derived from the lower-cased ARM id, since ARM ids
contain ``/``) and ``doc_type=register_consent``. Row writes use create/replace with an ETag
condition so the no-downgrade check cannot race. ``delete_item`` is never called. The client is
built by ``neurosphere_core.clients`` and injected.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any, Final

from azure.core import MatchConditions
from azure.cosmos.aio import ContainerProxy, CosmosClient
from azure.cosmos.exceptions import (
    CosmosAccessConditionFailedError,
    CosmosResourceExistsError,
    CosmosResourceNotFoundError,
)

from neurosphere_core.clients import translating
from neurosphere_core.deploy.register.models import ConsentRecord, ResourceRow, normalize_id
from neurosphere_core.deploy.register.store import check_no_downgrade
from neurosphere_core.errors import StaleVersionError

PARTITION_KEY_PATH: Final = "/deployment_id"
ROW_DOC_TYPE: Final = "register_row"
CONSENT_DOC_TYPE: Final = "register_consent"
_STORAGE_FIELDS: Final = frozenset({"id", "doc_type"})
_LIST: Final = "SELECT * FROM c WHERE c.doc_type = @doc_type"


def row_document_id(resource_id: str) -> str:
    return "row-" + hashlib.sha256(normalize_id(resource_id).encode()).hexdigest()[:40]


def consent_document_id(consent_id: str) -> str:
    return "consent-" + consent_id


def _strip(document: Mapping[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in document.items() if not k.startswith("_") and k not in _STORAGE_FIELDS}


class CosmosRegisterStore:
    def __init__(self, container: ContainerProxy) -> None:
        self._container = container

    @classmethod
    def from_client(
        cls, client: CosmosClient, *, database: str, container: str
    ) -> CosmosRegisterStore:
        return cls(client.get_database_client(database).get_container_client(container))

    async def _read(self, item: str, partition: str) -> dict[str, Any] | None:
        try:
            return dict(await self._container.read_item(item=item, partition_key=partition))
        except CosmosResourceNotFoundError:
            return None

    async def put_row(self, row: ResourceRow) -> None:
        doc_id = row_document_id(row.resource_id)
        body = {**row.model_dump(mode="json"), "id": doc_id, "doc_type": ROW_DOC_TYPE}
        with translating():
            current = await self._read(doc_id, row.deployment_id)
            existing = ResourceRow.model_validate(_strip(current)) if current else None
            check_no_downgrade(existing, row)
            try:
                if current is None:
                    await self._container.create_item(body=body)
                else:
                    await self._container.replace_item(
                        item=doc_id,
                        body=body,
                        etag=str(current["_etag"]),
                        match_condition=MatchConditions.IfNotModified,
                    )
            except (CosmosResourceExistsError, CosmosAccessConditionFailedError) as exc:
                raise StaleVersionError("register row changed concurrently") from exc

    async def get_row(self, deployment_id: str, resource_id: str) -> ResourceRow | None:
        with translating():
            doc = await self._read(row_document_id(resource_id), deployment_id)
        return ResourceRow.model_validate(_strip(doc)) if doc else None

    async def _query(self, deployment_id: str, doc_type: str) -> list[dict[str, Any]]:
        found: list[dict[str, Any]] = []
        with translating():
            pager = self._container.query_items(
                query=_LIST,
                parameters=[{"name": "@doc_type", "value": doc_type}],
                partition_key=deployment_id,
            )
            async for doc in pager:
                found.append(_strip(doc))
        return found

    async def list_rows(self, deployment_id: str) -> list[ResourceRow]:
        docs = await self._query(deployment_id, ROW_DOC_TYPE)
        rows = [ResourceRow.model_validate(d) for d in docs]
        return sorted(rows, key=lambda r: normalize_id(r.resource_id))

    async def put_consent(self, consent: ConsentRecord) -> None:
        body = {
            **consent.model_dump(mode="json"),
            "id": consent_document_id(consent.consent_id),
            "doc_type": CONSENT_DOC_TYPE,
        }
        with translating():
            await self._container.upsert_item(body=body)

    async def list_consents(self, deployment_id: str) -> list[ConsentRecord]:
        docs = await self._query(deployment_id, CONSENT_DOC_TYPE)
        return sorted((ConsentRecord.model_validate(d) for d in docs), key=lambda c: c.consent_id)
