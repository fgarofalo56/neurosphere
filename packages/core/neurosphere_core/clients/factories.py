"""The only place SDK clients are constructed (services must call these, never the SDKs).

Two paths, one switch (PRP-05 C6): ``NS_ENV=local`` may use emulator keys; every other env
requires a managed-identity credential and refuses keys/connection strings with
``invalid_schema`` before any client object exists. Hosts come only from ``CloudProfile``
(except Blob, see ``_BLOB_SUFFIX``).

Emulator secrets are read from environment variable NAMES (never hard-coded):
``NS_COSMOS_ENDPOINT`` (default ``http://localhost:8081``), ``NS_COSMOS_KEY``,
``NS_EVENTHUBS_CONNECTION_STRING``, ``NS_BLOB_CONNECTION_STRING``.
"""

from __future__ import annotations

import os
from typing import Final

from azure.core.credentials_async import AsyncTokenCredential
from azure.cosmos.aio import CosmosClient
from azure.eventhub.aio import EventHubConsumerClient, EventHubProducerClient
from azure.eventhub.extensions.checkpointstoreblobaio import BlobCheckpointStore
from azure.identity.aio import DefaultAzureCredential

from neurosphere_core.clients.lifetime import ClientLifetime
from neurosphere_core.cloud import CloudName, CloudProfile, Settings
from neurosphere_core.errors import InvalidSchemaError, ValidationIssue

ENV_COSMOS_ENDPOINT: Final = "NS_COSMOS_ENDPOINT"
ENV_COSMOS_KEY: Final = "NS_COSMOS_KEY"
ENV_EVENTHUBS_CONNECTION_STRING: Final = "NS_EVENTHUBS_CONNECTION_STRING"
ENV_BLOB_CONNECTION_STRING: Final = "NS_BLOB_CONNECTION_STRING"
_DEFAULT_LOCAL_COSMOS: Final = "http://localhost:8081"

# CloudProfile (PRP-05 item 1, not editable here) has no blob suffix; kept here as a
# per-cloud fact table until the profile gains one. Never built from user input.
_BLOB_SUFFIX: Final = {
    CloudName.COMMERCIAL: ".blob.core.windows.net",
    CloudName.GOVERNMENT: ".blob.core.usgovcloudapi.net",
}


def blob_account_url(profile: CloudProfile, account: str) -> str:
    profile.eventhubs_fqdn(account)  # reuse the profile's account-name validation
    return f"https://{account}{_BLOB_SUFFIX[profile.cloud]}/"


def _config_error(pointer: str, detail: str) -> InvalidSchemaError:
    return InvalidSchemaError(detail, errors=[ValidationIssue(pointer, detail)], reason="config")


def _refuse_secrets_outside_local(settings: Settings, **secrets: str | None) -> None:
    if settings.env == "local":
        return
    for name, value in secrets.items():
        if value is not None:
            raise _config_error(
                f"/{name}", f"{name} is only allowed when NS_ENV=local; use managed identity"
            )


def _identity(
    settings: Settings, credential: AsyncTokenCredential | None, lifetime: ClientLifetime
) -> AsyncTokenCredential:
    if credential is not None:
        return credential  # caller-owned
    created = DefaultAzureCredential(authority=settings.cloud_profile.login_host)
    return lifetime.register(created)


def _required(value: str | None, field: str, what: str) -> str:
    if not value:
        raise _config_error(f"/{field}", f"{what} is required")
    return value


def create_cosmos_client(
    settings: Settings,
    *,
    lifetime: ClientLifetime,
    account: str | None = None,
    credential: AsyncTokenCredential | None = None,
    key: str | None = None,
) -> CosmosClient:
    _refuse_secrets_outside_local(settings, key=key)
    if settings.env == "local":
        endpoint = os.environ.get(ENV_COSMOS_ENDPOINT, _DEFAULT_LOCAL_COSMOS)
        secret = _required(key or os.environ.get(ENV_COSMOS_KEY), "key", ENV_COSMOS_KEY)
        client = CosmosClient(endpoint, secret, enable_endpoint_discovery=False)
    else:
        url = settings.cloud_profile.cosmos_endpoint(_required(account, "account", "account"))
        client = CosmosClient(url, _identity(settings, credential, lifetime))
    return lifetime.register(client)


def create_eventhub_producer(
    settings: Settings,
    *,
    lifetime: ClientLifetime,
    eventhub_name: str,
    namespace: str | None = None,
    credential: AsyncTokenCredential | None = None,
    connection_string: str | None = None,
) -> EventHubProducerClient:
    _refuse_secrets_outside_local(settings, connection_string=connection_string)
    if settings.env == "local":
        conn = _required(
            connection_string or os.environ.get(ENV_EVENTHUBS_CONNECTION_STRING),
            "connection_string",
            ENV_EVENTHUBS_CONNECTION_STRING,
        )
        producer = EventHubProducerClient.from_connection_string(conn, eventhub_name=eventhub_name)
    else:
        fqdn = settings.cloud_profile.eventhubs_fqdn(_required(namespace, "namespace", "namespace"))
        producer = EventHubProducerClient(
            fqdn, eventhub_name, _identity(settings, credential, lifetime)
        )
    return lifetime.register(producer)


def create_eventhub_consumer(
    settings: Settings,
    *,
    lifetime: ClientLifetime,
    eventhub_name: str,
    consumer_group: str,
    namespace: str | None = None,
    credential: AsyncTokenCredential | None = None,
    connection_string: str | None = None,
    checkpoint_store: BlobCheckpointStore | None = None,
) -> EventHubConsumerClient:
    _refuse_secrets_outside_local(settings, connection_string=connection_string)
    if settings.env == "local":
        conn = _required(
            connection_string or os.environ.get(ENV_EVENTHUBS_CONNECTION_STRING),
            "connection_string",
            ENV_EVENTHUBS_CONNECTION_STRING,
        )
        consumer = EventHubConsumerClient.from_connection_string(
            conn,
            consumer_group=consumer_group,
            eventhub_name=eventhub_name,
            checkpoint_store=checkpoint_store,
        )
    else:
        fqdn = settings.cloud_profile.eventhubs_fqdn(_required(namespace, "namespace", "namespace"))
        consumer = EventHubConsumerClient(
            fqdn,
            eventhub_name,
            consumer_group,
            _identity(settings, credential, lifetime),
            checkpoint_store=checkpoint_store,
        )
    return lifetime.register(consumer)


def create_checkpoint_store(
    settings: Settings,
    *,
    lifetime: ClientLifetime,
    container: str,
    account: str | None = None,
    credential: AsyncTokenCredential | None = None,
    connection_string: str | None = None,
) -> BlobCheckpointStore:
    _refuse_secrets_outside_local(settings, connection_string=connection_string)
    if settings.env == "local":
        conn = _required(
            connection_string or os.environ.get(ENV_BLOB_CONNECTION_STRING),
            "connection_string",
            ENV_BLOB_CONNECTION_STRING,
        )
        store = BlobCheckpointStore.from_connection_string(conn, container)
    else:
        url = blob_account_url(
            settings.cloud_profile, _required(account, "account", "storage account")
        )
        store = BlobCheckpointStore(
            url, container, credential=_identity(settings, credential, lifetime)
        )
    return lifetime.register(store)
