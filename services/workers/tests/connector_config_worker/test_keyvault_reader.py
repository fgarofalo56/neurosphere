"""PRP-42 item 2: the REST Key Vault reader (httpx.MockTransport, no network)."""

from __future__ import annotations

import logging

import httpx
import pytest
from neurosphere_contracts.admin.v1.credential_reference import CredentialReference
from neurosphere_core.cloud import CloudName
from neurosphere_workers.connector_config import (
    ConnectorCredentialUnavailableError,
    KeyVaultSecretReader,
)

from .support import SECRET_VALUE, VAULT_URI


def _ref(uri: str = VAULT_URI) -> CredentialReference:
    return CredentialReference(kind="key_vault_secret", secret_uri=uri)


async def _token() -> str:
    return "token-for-test"


def _reader(
    handler: httpx.MockTransport, cloud: CloudName = CloudName.COMMERCIAL
) -> KeyVaultSecretReader:
    return KeyVaultSecretReader(cloud=cloud, token_provider=_token, transport=handler)


async def test_reads_the_secret_with_bearer_token_and_api_version() -> None:
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"value": SECRET_VALUE})

    secret = await _reader(httpx.MockTransport(handle)).read(_ref())
    assert secret.get_secret_value() == SECRET_VALUE
    assert SECRET_VALUE not in repr(secret)
    request = seen[0]
    assert request.url.host == "ns-kv.vault.azure.net"
    assert request.url.path == "/secrets/producer-key"
    assert request.url.params["api-version"] == "7.4"
    assert request.headers["authorization"] == "Bearer token-for-test"


@pytest.mark.parametrize("status", [401, 403, 404, 500])
async def test_http_failures_map_to_one_reason_without_uri(
    status: int, caplog: pytest.LogCaptureFixture
) -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(status, json={"error": "x"}))
    with (
        caplog.at_level(logging.DEBUG),
        pytest.raises(ConnectorCredentialUnavailableError) as caught,
    ):
        await _reader(transport).read(_ref())
    assert caught.value.reason == "connector_credential_unavailable"
    assert VAULT_URI not in str(caught.value) and "ns-kv" not in str(caught.value)
    assert "ns-kv" not in caplog.text


async def test_timeout_and_transport_errors_map_to_the_same_reason() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("slow", request=request)

    with pytest.raises(ConnectorCredentialUnavailableError):
        await _reader(httpx.MockTransport(boom)).read(_ref())


async def test_token_failure_maps_to_the_same_reason() -> None:
    async def bad_token() -> str:
        raise RuntimeError("no identity")

    reader = KeyVaultSecretReader(
        cloud=CloudName.COMMERCIAL,
        token_provider=bad_token,
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"value": "v"})),
    )
    with pytest.raises(ConnectorCredentialUnavailableError):
        await reader.read(_ref())


async def test_host_of_another_cloud_is_refused_before_any_request() -> None:
    calls: list[int] = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(200, json={"value": "v"})

    reader = _reader(httpx.MockTransport(handle), CloudName.GOVERNMENT)
    with pytest.raises(ConnectorCredentialUnavailableError):
        await reader.read(_ref())  # commercial vault on a Government deployment
    with pytest.raises(ConnectorCredentialUnavailableError):
        await _reader(httpx.MockTransport(handle)).read(
            CredentialReference(
                kind="managed_identity",
                managed_identity_client_id="6c1d2e3f-4a5b-4c6d-8e7f-90a1b2c3d4e5",
            )
        )
    assert calls == []


async def test_empty_or_malformed_value_is_unavailable() -> None:
    for payload in ({"value": ""}, {"nope": 1}, {"value": 3}):
        transport = httpx.MockTransport(lambda r, p=payload: httpx.Response(200, json=p))
        with pytest.raises(ConnectorCredentialUnavailableError):
            await _reader(transport).read(_ref())
