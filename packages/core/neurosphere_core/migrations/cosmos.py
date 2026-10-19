"""Cosmos (``azure.cosmos.aio``) implementations of the migration stores.

Concurrency uses ``replace_item`` with ``etag`` + ``MatchConditions.IfNotModified``. Mapping:
412 (and 409 on ledger create, 404 on replace) -> ``StaleVersionError``; everything else goes
through ``neurosphere_core.clients.errors.translate_sdk_error`` (429 -> ``RateLimitedError``,
408/5xx -> ``DependencyTransientError``). Both containers must use partition key ``/id``.
Build the client with ``neurosphere_core.clients.create_cosmos_client``; no credentials are
handled here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from azure.core import MatchConditions
from azure.cosmos.exceptions import (
    CosmosAccessConditionFailedError,
    CosmosResourceExistsError,
    CosmosResourceNotFoundError,
)
from azure.cosmos.exceptions import CosmosHttpResponseError as _CosmosError

from neurosphere_core.clients.errors import translate_sdk_error
from neurosphere_core.errors import StaleVersionError
from neurosphere_core.migrations.models import MigrationLedger
from neurosphere_core.migrations.protocols import StoredDocument

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from azure.cosmos.aio import ContainerProxy

__all__ = ["CosmosDocumentStore", "CosmosLedgerStore"]

_SYSTEM_PROPERTIES = ("_rid", "_self", "_etag", "_attachments", "_ts")


def _clean(item: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in item.items() if k not in _SYSTEM_PROPERTIES}


def _translate(exc: _CosmosError) -> Exception:
    # One taxonomy mapping for every Cosmos caller: reuse the shared client translation.
    return translate_sdk_error(exc) or exc


class CosmosDocumentStore:
    """``DocumentStore`` over one container (partition key ``/id``)."""

    def __init__(self, container: ContainerProxy) -> None:
        self._container = container

    async def iter_documents(self) -> AsyncIterator[StoredDocument]:
        try:
            rows = [row async for row in self._container.query_items("SELECT * FROM c")]
        except _CosmosError as exc:
            raise _translate(exc) from exc
        for row in rows:
            yield StoredDocument(_clean(row), str(row["_etag"]))

    async def replace_document(self, document: dict[str, Any], *, etag: str) -> StoredDocument:
        body = _clean(document)
        try:
            saved = await self._container.replace_item(
                body["id"], body, etag=etag, match_condition=MatchConditions.IfNotModified
            )
        except (CosmosAccessConditionFailedError, CosmosResourceNotFoundError) as exc:
            raise StaleVersionError("document changed since it was read") from exc
        except _CosmosError as exc:
            raise _translate(exc) from exc
        return StoredDocument(_clean(dict(saved)), str(saved["_etag"]))


class CosmosLedgerStore:
    """``LedgerStore`` over one container (partition key ``/id``)."""

    def __init__(self, container: ContainerProxy) -> None:
        self._container = container

    async def read(self, ledger_id: str) -> MigrationLedger | None:
        try:
            item = await self._container.read_item(ledger_id, partition_key=ledger_id)
        except CosmosResourceNotFoundError:
            return None
        except _CosmosError as exc:
            raise _translate(exc) from exc
        return MigrationLedger.model_validate({**_clean(item), "etag": str(item["_etag"])})

    async def write(self, ledger: MigrationLedger, *, expected_etag: str | None) -> MigrationLedger:
        body = ledger.model_dump(mode="json", exclude={"etag"})
        try:
            if expected_etag is None:
                saved = await self._container.create_item(body)
            else:
                saved = await self._container.replace_item(
                    body["id"],
                    body,
                    etag=expected_etag,
                    match_condition=MatchConditions.IfNotModified,
                )
        except (
            CosmosAccessConditionFailedError,
            CosmosResourceExistsError,
            CosmosResourceNotFoundError,
        ) as exc:
            raise StaleVersionError("ledger changed since it was read") from exc
        except _CosmosError as exc:
            raise _translate(exc) from exc
        return ledger.model_copy(update={"etag": str(saved["_etag"])})
