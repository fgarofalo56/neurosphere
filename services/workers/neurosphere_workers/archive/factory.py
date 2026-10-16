"""Optional wiring helper: build a ``BlobArchiveSink`` over a real ``ContainerClient``.

Follows ``neurosphere_core.clients.factories``: a connection string only when NS_ENV=local,
managed identity everywhere else. Not used by tests (they inject a fake container).
"""

from __future__ import annotations

import os

from azure.core.credentials_async import AsyncTokenCredential
from azure.identity.aio import DefaultAzureCredential
from azure.storage.blob.aio import ContainerClient
from neurosphere_core.clients.factories import ENV_BLOB_CONNECTION_STRING, blob_account_url
from neurosphere_core.clients.lifetime import ClientLifetime
from neurosphere_core.cloud import CloudName, Settings
from neurosphere_core.errors import InvalidSchemaError, ValidationIssue

from neurosphere_workers.archive.settings import ArchiveSettings, resolve_pseudonym_key
from neurosphere_workers.archive.sink import BlobArchiveSink


def _config_error(pointer: str, detail: str) -> InvalidSchemaError:
    return InvalidSchemaError(detail, errors=[ValidationIssue(pointer, detail)], reason="config")


def create_archive_sink(
    settings: Settings,
    archive: ArchiveSettings,
    *,
    lifetime: ClientLifetime,
    credential: AsyncTokenCredential | None = None,
) -> BlobArchiveSink:
    """One sink for this deployment's cloud and its single archive storage account."""
    if settings.env == "local":
        conn = os.environ.get(ENV_BLOB_CONNECTION_STRING)
        if not conn:
            raise _config_error("/connection_string", f"{ENV_BLOB_CONNECTION_STRING} is required")
        client = ContainerClient.from_connection_string(conn, archive.container)
    else:
        if not archive.storage_account:
            raise _config_error("/storage_account", "NS_ARCHIVE_STORAGE_ACCOUNT is required")
        if credential is None:
            credential = lifetime.register(
                DefaultAzureCredential(authority=settings.cloud_profile.login_host)
            )
        url = blob_account_url(settings.cloud_profile, archive.storage_account)
        client = ContainerClient(url, archive.container, credential=credential)
    lifetime.register(client)
    cloud = (settings.cloud or CloudName.COMMERCIAL).value
    return BlobArchiveSink(
        client, cloud=cloud, pseudonym_key=resolve_pseudonym_key(archive, env=settings.env)
    )
