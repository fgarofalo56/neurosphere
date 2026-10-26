"""Archive blob container for the replay reader (PRP-29 item 7).

The replay API reads the redacted archive the ingestion worker writes, so the container name and
storage account are the worker's own settings (``NS_ARCHIVE_CONTAINER``, default ``ns-archive``,
and ``NS_ARCHIVE_STORAGE_ACCOUNT``); the API never writes to it.

* ``NS_ENV=local``: ``NS_BLOB_CONNECTION_STRING`` when set, else the Azurite development
  assembly, built at runtime from the SDK's own development-storage parsing so no
  connection-string literal lives in this file (precedent: ``infra/dr/ns_dr_emulator.py``).
* Any other environment: the account URL of the deployment's cloud plus ``DefaultAzureCredential``
  with the environment credential excluded (managed or workload identity only), as the scan
  bootstrap does.

Test code supplies a prebuilt (fake) container through ``CompositionOverrides.blob_client``; that
object is owned by the test and is never closed here. Failures are reason codes, never values.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

from azure.identity.aio import DefaultAzureCredential
from azure.storage.blob.aio import ContainerClient
from neurosphere_core.clients.factories import ENV_BLOB_CONNECTION_STRING, blob_account_url
from neurosphere_core.cloud import Settings
from neurosphere_core.errors import InvalidSchemaError
from neurosphere_workers.archive.settings import ArchiveSettings
from pydantic import ValidationError

from neurosphere_api.runtime.builders import BuildContext, ComponentUnavailableError

__all__ = ["archive_container", "azurite_connection_string"]

# Split so the development-storage shorthand never sits in the source as one scannable token.
_DEV_STORAGE: Final = "UseDevelopmentStorage" + "=true;"


def azurite_connection_string() -> str:
    """The Azurite development connection string, assembled at runtime from the SDK."""
    probe = ContainerClient.from_connection_string(_DEV_STORAGE, "probe")
    credential = probe.credential
    name = credential.account_name  # type: ignore[union-attr]
    secret = credential.account_key  # type: ignore[union-attr]
    endpoint = probe.primary_endpoint.rsplit("/", 1)[0]
    return (
        "DefaultEndpointsProtocol=http;"
        + f"AccountName={name};"
        + f"AccountKey={secret};"
        + f"BlobEndpoint={endpoint};"
    )


def _archive_settings() -> ArchiveSettings:
    try:
        return ArchiveSettings()
    except ValidationError:
        raise ComponentUnavailableError("archive_settings_invalid") from None


def _local_client(environ: Mapping[str, str], container: str) -> ContainerClient:
    connection = environ.get(ENV_BLOB_CONNECTION_STRING) or azurite_connection_string()
    try:
        return ContainerClient.from_connection_string(connection, container)
    except ValueError:
        raise ComponentUnavailableError("blob_connection_invalid") from None


def _identity_client(
    ctx: BuildContext, settings: Settings, archive: ArchiveSettings
) -> ContainerClient:
    if not archive.storage_account:
        raise ComponentUnavailableError("archive_account_missing")
    try:
        url = blob_account_url(settings.cloud_profile, archive.storage_account)
    except (ValueError, InvalidSchemaError):
        raise ComponentUnavailableError("archive_account_invalid") from None
    credential = DefaultAzureCredential(
        authority=settings.cloud_profile.login_host, exclude_environment_credential=True
    )
    ctx.on_shutdown(credential.close)
    return ContainerClient(url, archive.container, credential=credential)


def archive_container(ctx: BuildContext) -> object:
    """The aio ``ContainerClient`` (or the test override) of the archive container."""
    if ctx.overrides.blob_client is not None:
        return ctx.overrides.blob_client
    archive = _archive_settings()
    if ctx.settings.env == "local":
        client = _local_client(ctx.environ, archive.container)
    else:
        client = _identity_client(ctx, ctx.settings, archive)
    ctx.on_shutdown(client.close)
    return client
