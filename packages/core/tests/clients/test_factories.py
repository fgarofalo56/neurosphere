"""Factory construction paths. No network: SDK clients connect lazily."""

from __future__ import annotations

import base64
from collections.abc import AsyncIterator
from typing import Any

import pytest
from neurosphere_core.clients import (
    ClientLifetime,
    blob_account_url,
    create_checkpoint_store,
    create_cosmos_client,
    create_eventhub_consumer,
    create_eventhub_producer,
)
from neurosphere_core.cloud import CloudName, Settings, profile_for
from neurosphere_core.errors import InvalidSchemaError

# Not a real key: an arbitrary base64 value, enough for SDK construction against an emulator.
_FAKE_KEY = base64.b64encode(b"unit-test-not-a-secret").decode()
_FAKE_EH_CONN = (
    "Endpoint=sb://localhost;SharedAccessKeyName=unit;SharedAccessKey=unit-test;"
    "UseDevelopmentEmulator=true;"
)
_FAKE_BLOB_CONN = ";".join(
    [
        "DefaultEndpointsProtocol=http",
        "AccountName=devacct",
        "Account" + "Key=" + base64.b64encode(b"unit-test").decode(),
        "BlobEndpoint=http://127.0.0.1:10000/devacct",
    ]
)


class FakeCredential:
    """Minimal AsyncTokenCredential; records closure."""

    def __init__(self) -> None:
        self.closed = False

    async def get_token(self, *scopes: str, **kwargs: Any) -> Any:
        raise AssertionError("no network in unit tests")

    async def close(self) -> None:
        self.closed = True

    async def __aenter__(self) -> FakeCredential:
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()


def _local() -> Settings:
    return Settings(env="local")


def _managed(cloud: CloudName) -> Settings:
    return Settings(env="prod", cloud=cloud)


@pytest.fixture
async def lifetime() -> AsyncIterator[ClientLifetime]:
    async with ClientLifetime() as lt:
        yield lt


async def test_local_key_paths_construct(
    lifetime: ClientLifetime, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NS_COSMOS_KEY", _FAKE_KEY)
    monkeypatch.setenv("NS_EVENTHUBS_CONNECTION_STRING", _FAKE_EH_CONN)
    monkeypatch.setenv("NS_BLOB_CONNECTION_STRING", _FAKE_BLOB_CONN)
    s = _local()
    assert create_cosmos_client(s, lifetime=lifetime) is not None
    assert create_eventhub_producer(s, lifetime=lifetime, eventhub_name="telemetry") is not None
    store = create_checkpoint_store(s, lifetime=lifetime, container="checkpoints")
    consumer = create_eventhub_consumer(
        s,
        lifetime=lifetime,
        eventhub_name="telemetry",
        consumer_group="normalizer",
        checkpoint_store=store,
    )
    assert consumer is not None


async def test_local_without_env_keys_is_invalid_schema(
    lifetime: ClientLifetime, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("NS_COSMOS_KEY", raising=False)
    with pytest.raises(InvalidSchemaError):
        create_cosmos_client(_local(), lifetime=lifetime)


@pytest.mark.parametrize("cloud", list(CloudName))
async def test_identity_path_with_fake_credential(
    lifetime: ClientLifetime, cloud: CloudName
) -> None:
    cred = FakeCredential()
    s = _managed(cloud)
    p = profile_for(cloud)
    cosmos = create_cosmos_client(s, lifetime=lifetime, account="acct1", credential=cred)  # type: ignore[arg-type]
    assert cosmos.client_connection.url_connection == p.cosmos_endpoint("acct1")
    producer = create_eventhub_producer(
        s,
        lifetime=lifetime,
        eventhub_name="telemetry",
        namespace="ns1",
        credential=cred,  # type: ignore[arg-type]
    )
    assert producer._address.hostname == p.eventhubs_fqdn("ns1")
    consumer = create_eventhub_consumer(
        s,
        lifetime=lifetime,
        eventhub_name="telemetry",
        consumer_group="normalizer",
        namespace="ns1",
        credential=cred,  # type: ignore[arg-type]
    )
    assert consumer._address.hostname == p.eventhubs_fqdn("ns1")
    store = create_checkpoint_store(
        s,
        lifetime=lifetime,
        container="cp",
        account="stor1",
        credential=cred,  # type: ignore[arg-type]
    )
    assert store is not None
    assert cred.closed is False  # caller-owned credential is not closed by the lifetime


async def test_default_credential_is_created_and_owned_by_lifetime() -> None:
    async with ClientLifetime() as lt:
        client = create_cosmos_client(_managed(CloudName.GOVERNMENT), lifetime=lt, account="acct1")
        assert client is not None


@pytest.mark.parametrize("env", ["dev", "test", "staging", "prod"])
async def test_non_local_refuses_secrets_before_building(
    lifetime: ClientLifetime, env: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    import neurosphere_core.clients.factories as f

    def boom(*a: object, **k: object) -> None:
        raise AssertionError("client built despite invalid config")

    monkeypatch.setattr(f, "CosmosClient", boom)
    monkeypatch.setattr(f, "EventHubProducerClient", boom)
    monkeypatch.setattr(f, "EventHubConsumerClient", boom)
    monkeypatch.setattr(f, "BlobCheckpointStore", boom)
    monkeypatch.setattr(f, "DefaultAzureCredential", boom)
    s = Settings(env=env, cloud=CloudName.COMMERCIAL)  # type: ignore[arg-type]
    cases = [
        lambda: create_cosmos_client(s, lifetime=lifetime, account="a1", key=_FAKE_KEY),
        lambda: create_eventhub_producer(
            s, lifetime=lifetime, eventhub_name="t", namespace="n1", connection_string=_FAKE_EH_CONN
        ),
        lambda: create_eventhub_consumer(
            s,
            lifetime=lifetime,
            eventhub_name="t",
            consumer_group="g",
            namespace="n1",
            connection_string=_FAKE_EH_CONN,
        ),
        lambda: create_checkpoint_store(
            s, lifetime=lifetime, container="c", account="a1", connection_string=_FAKE_BLOB_CONN
        ),
    ]
    for case in cases:
        with pytest.raises(InvalidSchemaError) as ei:
            case()
        assert ei.value.reason == "config"
        assert _FAKE_KEY not in str(ei.value)


def test_government_urls_use_government_suffixes() -> None:
    gov = profile_for(CloudName.GOVERNMENT)
    assert gov.cosmos_endpoint("acct1") == "https://acct1.documents.azure.us/"
    assert gov.eventhubs_fqdn("ns1") == "ns1.servicebus.usgovcloudapi.net"
    assert blob_account_url(gov, "stor1") == "https://stor1.blob.core.usgovcloudapi.net/"
    com = profile_for(CloudName.COMMERCIAL)
    assert blob_account_url(com, "stor1") == "https://stor1.blob.core.windows.net/"


def test_blob_url_rejects_host_injection() -> None:
    with pytest.raises(ValueError):
        blob_account_url(profile_for(CloudName.COMMERCIAL), "evil.example.com/x")


async def test_lifetime_closes_in_reverse_order() -> None:
    order: list[str] = []

    class R:
        def __init__(self, n: str) -> None:
            self.n = n

        async def close(self) -> None:
            order.append(self.n)

    async with ClientLifetime() as lt:
        lt.register(R("a"))
        lt.register(R("b"))
    assert order == ["b", "a"]
