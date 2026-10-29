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

import asyncio
import os
import time
from collections.abc import AsyncGenerator
from typing import Final
from urllib.parse import urlsplit

import httpx
from azure.core.credentials_async import AsyncTokenCredential
from azure.cosmos.aio import CosmosClient
from azure.eventhub.aio import EventHubConsumerClient, EventHubProducerClient
from azure.eventhub.extensions.checkpointstoreblobaio import BlobCheckpointStore
from azure.identity.aio import DefaultAzureCredential

from neurosphere_core.clients.lifetime import ClientLifetime
from neurosphere_core.cloud import CloudName, CloudProfile, Settings
from neurosphere_core.errors import CapabilityUnavailableError, InvalidSchemaError, ValidationIssue

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


# --- Cloud-pinned REST clients (ARM, Log Analytics) -----------------------------------------

_LOG_ANALYTICS_HOST: Final = {
    CloudName.COMMERCIAL: "api.loganalytics.io",
    CloudName.GOVERNMENT: "api.loganalytics.us",
}
_REFRESH_SKEW_SECONDS: Final = 300  # refresh when within 5 minutes of expiry


def log_analytics_query_host(profile: CloudProfile) -> str:
    """Documented Log Analytics query host for the profile's cloud."""
    return _LOG_ANALYTICS_HOST[profile.cloud]


def _allowed_hosts(profile: CloudProfile) -> tuple[frozenset[str], tuple[str, ...]]:
    exact = frozenset(
        {profile.login_host, profile.management_host, log_analytics_query_host(profile)}
    )
    suffixes = (
        profile.cosmos_suffix,
        profile.eventhubs_suffix,
        profile.search_suffix,
        profile.apim_gateway_suffix,
        _BLOB_SUFFIX[profile.cloud],
    )
    return exact, suffixes


def assert_host_in_cloud(profile: CloudProfile, url: str) -> None:
    """Refuse (``capability_unavailable``) any URL whose host is not in the profile's cloud."""
    host = (urlsplit(url).hostname or "").lower()
    exact, suffixes = _allowed_hosts(profile)
    if host in exact or (host and host.endswith(suffixes)):
        return
    raise CapabilityUnavailableError(
        "endpoint_cloud_mismatch",
        f"{host or 'url'} is not an approved {profile.cloud.value}-cloud endpoint host",
    )


class _BearerAuth(httpx.Auth):
    """Per-client bearer injection; the token is never logged and never leaves the cloud."""

    def __init__(self, profile: CloudProfile, credential: AsyncTokenCredential, scope: str) -> None:
        self._profile = profile
        self._credential = credential
        self._scope = scope
        self._token: str | None = None
        self._expires_on = 0.0
        self._lock = asyncio.Lock()

    async def _bearer(self) -> str:
        async with self._lock:
            if self._token is None or self._expires_on - time.time() < _REFRESH_SKEW_SECONDS:
                fresh = await self._credential.get_token(self._scope)
                self._token, self._expires_on = fresh.token, float(fresh.expires_on)
            return self._token

    async def async_auth_flow(
        self, request: httpx.Request
    ) -> AsyncGenerator[httpx.Request, httpx.Response]:
        assert_host_in_cloud(self._profile, str(request.url))  # before any token is attached
        request.headers["Authorization"] = f"Bearer {await self._bearer()}"
        yield request


class _CloudClient(httpx.AsyncClient):
    """``httpx.AsyncClient`` that also closes a credential it created itself."""

    _owned: AsyncTokenCredential | None = None

    async def aclose(self) -> None:
        await super().aclose()
        if self._owned is not None:
            await self._owned.close()
            self._owned = None


def _rest_client(
    profile: CloudProfile,
    base_url: str,
    scope: str,
    credential: AsyncTokenCredential | None,
    transport: httpx.AsyncBaseTransport | None,
) -> httpx.AsyncClient:
    assert_host_in_cloud(profile, base_url)
    owned = None
    if credential is None:
        owned = credential = DefaultAzureCredential(authority=profile.login_host)
    client = _CloudClient(
        base_url=base_url,
        auth=_BearerAuth(profile, credential, scope),
        transport=transport,
        timeout=30.0,
    )
    client._owned = owned
    return client


def arm_client(
    profile: CloudProfile,
    credential: AsyncTokenCredential | None = None,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> httpx.AsyncClient:
    """Bearer-authenticated ARM client bound to the profile's management endpoint."""
    base = profile.management_url
    return _rest_client(profile, base, f"{base}.default", credential, transport)


def log_analytics_client(
    profile: CloudProfile,
    credential: AsyncTokenCredential | None = None,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> httpx.AsyncClient:
    """Bearer-authenticated Log Analytics query client for the profile's cloud."""
    base = f"https://{log_analytics_query_host(profile)}/"
    return _rest_client(profile, base, f"{base}.default", credential, transport)
