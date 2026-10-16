"""Blob-backed quarantine store (PRP-07 C3): ``records/{doc_id}.json`` plus replay markers.

The container client is INJECTED (a ``BlobContainer``), so the sink, the replay CLI and the tests
never build SDK clients themselves. ``create_quarantine_container`` is the one optional builder,
and follows ``neurosphere_core.clients.factories``: a connection string only when NS_ENV=local,
managed identity everywhere else.

Layout::

    records/{doc_id}.json    one QuarantineRecord, first write wins
    replayed/{doc_id}.json   written by the replay CLI after a successful replay

Blob metadata (``reason``, ``customer_id``, ``quarantined_date``) exists only so listings can
filter without downloading every record. It is never trusted over the record itself.
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime
from typing import Any, Protocol

from azure.core.credentials_async import AsyncTokenCredential
from azure.core.exceptions import (
    AzureError,
    HttpResponseError,
    ResourceExistsError,
    ServiceRequestError,
    ServiceResponseError,
)
from azure.identity.aio import DefaultAzureCredential
from azure.storage.blob.aio import ContainerClient
from neurosphere_core.clients import ClientLifetime
from neurosphere_core.clients.factories import ENV_BLOB_CONNECTION_STRING, blob_account_url
from neurosphere_core.cloud import Settings
from neurosphere_core.errors import (
    DependencyTransientError,
    InvalidSchemaError,
    ValidationIssue,
)
from neurosphere_core.payload import find_body_fields
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from neurosphere_workers.ingestion.models import QuarantineRecord
from neurosphere_workers.ingestion.reasons import QuarantineReason

RECORDS_PREFIX = "records/"
REPLAYED_PREFIX = "replayed/"
_TRANSIENT_STATUS = frozenset({408, 429})


class QuarantineSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NS_QUARANTINE_", frozen=True, extra="forbid")

    container: str = Field(default="ns-quarantine", min_length=3)
    storage_account: str | None = None  # non-local only (managed identity)


class BlobDownload(Protocol):
    async def readall(self) -> bytes: ...


class BlobListItem(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def metadata(self) -> Mapping[str, str] | None: ...


class BlobContainer(Protocol):
    """The slice of ``azure.storage.blob.aio.ContainerClient`` this package uses."""

    async def upload_blob(
        self,
        name: str,
        data: bytes,
        *,
        overwrite: bool = False,
        metadata: Mapping[str, str] | None = None,
    ) -> Any:
        """Raises ``azure.core.exceptions.ResourceExistsError`` when it exists and not overwrite."""
        ...

    async def download_blob(self, blob: str) -> BlobDownload:
        """Raises ``azure.core.exceptions.ResourceNotFoundError`` when missing."""
        ...

    def list_blobs(
        self, name_starts_with: str | None = None, include: list[str] | None = None
    ) -> AsyncIterator[BlobListItem]: ...


def record_blob_name(doc_id: str) -> str:
    return f"{RECORDS_PREFIX}{doc_id}.json"


def replayed_blob_name(doc_id: str) -> str:
    return f"{REPLAYED_PREFIX}{doc_id}.json"


def _is_transient(exc: AzureError) -> bool:
    if isinstance(exc, (ServiceRequestError, ServiceResponseError)):
        return True
    status = exc.status_code if isinstance(exc, HttpResponseError) else None
    return status is not None and (status >= 500 or status in _TRANSIENT_STATUS)


async def _upload_first_wins(
    container: BlobContainer, name: str, data: bytes, metadata: Mapping[str, str]
) -> bool:
    """True when newly written, False when it already existed. Transient SDK errors are mapped."""
    try:
        await container.upload_blob(name, data, overwrite=False, metadata=dict(metadata))
    except ResourceExistsError:
        return False
    except AzureError as exc:
        if _is_transient(exc):
            raise DependencyTransientError(
                "blob store unavailable", reason="quarantine_blob"
            ) from None
        raise
    return True


def _metadata_value(value: str | None) -> str | None:
    """Blob metadata must be printable ASCII; anything else is simply not filterable."""
    if value and value.isascii() and value.isprintable():
        return value
    return None


def record_metadata(record: QuarantineRecord) -> dict[str, str]:
    meta = {
        "reason": record.reason.value,
        "quarantined_date": record.quarantined_at.astimezone(UTC).date().isoformat(),
    }
    customer = _metadata_value(record.customer_id)
    if customer:
        meta["customer_id"] = customer
    return meta


class BlobQuarantineSink:
    """``QuarantineSink`` over a blob container. Idempotent: the first write for a doc_id wins."""

    def __init__(self, container: BlobContainer) -> None:
        self._container = container

    async def write(self, record: QuarantineRecord) -> None:
        # Defense in depth: QuarantineRecord already refuses bodies, but a record built with
        # model_construct would skip that validator. A body never reaches the container.
        if record.payload is not None and find_body_fields(record.payload):
            raise InvalidSchemaError(
                "quarantine payload contains body fields",
                errors=[ValidationIssue("/payload", "body field present")],
                reason="body_field_present",
            )
        data = record.model_dump_json().encode()
        await _upload_first_wins(
            self._container, record_blob_name(record.doc_id), data, record_metadata(record)
        )


class BlobQuarantineReader:
    """Read side used by the replay CLI: list, load, and replay markers."""

    def __init__(self, container: BlobContainer) -> None:
        self._container = container

    async def list_doc_ids(
        self,
        *,
        reason: QuarantineReason | None = None,
        customer_id: str | None = None,
        date: str | None = None,
    ) -> list[str]:
        ids: list[str] = []
        async for item in self._container.list_blobs(RECORDS_PREFIX, include=["metadata"]):
            meta = item.metadata or {}
            if reason is not None and meta.get("reason") != reason.value:
                continue
            if customer_id is not None and meta.get("customer_id") != customer_id:
                continue
            if date is not None and meta.get("quarantined_date") != date:
                continue
            name = item.name
            if name.startswith(RECORDS_PREFIX) and name.endswith(".json"):
                ids.append(name[len(RECORDS_PREFIX) : -len(".json")])
        return sorted(ids)

    async def get(self, doc_id: str) -> QuarantineRecord | None:
        name = record_blob_name(doc_id)
        if not await self._exists(name):
            return None
        stream = await self._container.download_blob(name)
        return QuarantineRecord.model_validate_json(await stream.readall())

    async def is_replayed(self, doc_id: str) -> bool:
        return await self._exists(replayed_blob_name(doc_id))

    async def mark_replayed(self, doc_id: str, *, at: datetime) -> bool:
        body = json.dumps({"doc_id": doc_id, "replayed_at": at.astimezone(UTC).isoformat()})
        return await _upload_first_wins(
            self._container, replayed_blob_name(doc_id), body.encode(), {"doc_id": doc_id}
        )

    async def _exists(self, name: str) -> bool:
        async for item in self._container.list_blobs(name):
            if item.name == name:
                return True
        return False


def create_quarantine_container(
    settings: Settings,
    *,
    lifetime: ClientLifetime,
    quarantine: QuarantineSettings | None = None,
    credential: AsyncTokenCredential | None = None,
    connection_string: str | None = None,
) -> ContainerClient:
    """Build the real container client (wiring only). Keys are refused outside NS_ENV=local."""
    conf = quarantine or QuarantineSettings()
    if settings.env == "local":
        conn = connection_string or os.environ.get(ENV_BLOB_CONNECTION_STRING)
        if not conn:
            raise InvalidSchemaError(
                f"{ENV_BLOB_CONNECTION_STRING} is required",
                errors=[ValidationIssue("/connection_string", "required")],
                reason="config",
            )
        client = ContainerClient.from_connection_string(conn, conf.container)
    else:
        if connection_string is not None:
            raise InvalidSchemaError(
                "connection_string is only allowed when NS_ENV=local; use managed identity",
                errors=[ValidationIssue("/connection_string", "local only")],
                reason="config",
            )
        if not conf.storage_account:
            raise InvalidSchemaError(
                "storage account is required",
                errors=[ValidationIssue("/storage_account", "required")],
                reason="config",
            )
        cred = credential or lifetime.register(
            DefaultAzureCredential(authority=settings.cloud_profile.login_host)
        )
        client = ContainerClient(
            blob_account_url(settings.cloud_profile, conf.storage_account),
            conf.container,
            credential=cred,
        )
    return lifetime.register(client)
