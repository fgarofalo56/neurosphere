"""Key Vault secret reader over REST with the workload identity (PRP-42, clarification 2).

``GET https://<vault>/secrets/<name>[/<version>]?api-version=7.4`` with a bearer token for the
vault scope, through ``httpx``: no ``azure-keyvault-secrets`` dependency (a Tier-1 change this PRP
does not own). The vault host is checked as a DNS-label match for the deployment cloud before any
token is requested. Every failure (a refused host, 401/403/404, a timeout, a malformed answer)
raises :class:`ConnectorCredentialUnavailableError`: its message is the reason code only, never the
URI, the vault, the secret name or the value.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any, Final, Protocol

import httpx
from neurosphere_contracts.admin.v1.credential_reference import CredentialReference
from neurosphere_core.admin.connectors import parse_key_vault_secret
from neurosphere_core.cloud import CloudName, profile_for
from neurosphere_core.errors import NeuroSphereError
from pydantic import SecretStr

__all__ = [
    "API_VERSION",
    "REASON",
    "ConnectorCredentialUnavailableError",
    "KeyVaultSecretReader",
    "SecretReader",
    "TokenProvider",
    "default_vault_token_provider",
]

API_VERSION: Final = "7.4"
REASON: Final = "connector_credential_unavailable"
_SCOPES: Final = {
    CloudName.COMMERCIAL: "https://vault.azure.net/.default",
    CloudName.GOVERNMENT: "https://vault.usgovcloudapi.net/.default",
}

TokenProvider = Callable[[], Awaitable[str]]


class _DropVaultRequests(logging.Filter):
    """httpx logs every request URL at INFO; a Key Vault URL (vault, secret name) never leaves."""

    def filter(self, record: logging.LogRecord) -> bool:
        return "/secrets/" not in record.getMessage()


logging.getLogger("httpx").addFilter(_DropVaultRequests())


class ConnectorCredentialUnavailableError(Exception):
    """The producer secret could not be read. ``reason`` is a machine code; nothing else."""

    reason: str = REASON

    def __init__(self) -> None:
        super().__init__(REASON)


class SecretReader(Protocol):
    async def read(self, reference: CredentialReference) -> SecretStr: ...


def default_vault_token_provider(
    cloud: CloudName, *, client_id: str | None = None
) -> TokenProvider:
    """``DefaultAzureCredential`` (workload identity) with the cloud's Key Vault scope."""
    scope = _SCOPES[cloud]
    authority = _authority(cloud)

    async def provide() -> str:
        from azure.identity import DefaultAzureCredential

        options: dict[str, Any] = {"authority": authority}
        if client_id is not None:
            options["managed_identity_client_id"] = client_id
        credential = DefaultAzureCredential(**options)
        try:
            token = await asyncio.to_thread(credential.get_token, scope)
        finally:
            credential.close()
        return token.token

    return provide


def _authority(cloud: CloudName) -> str:
    return profile_for(cloud).login_host


class KeyVaultSecretReader:
    """Reads one secret per call; holds no secret and logs nothing."""

    def __init__(
        self,
        *,
        cloud: CloudName,
        token_provider: TokenProvider,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        self._cloud = cloud
        self._token = token_provider
        self._transport = transport
        self._timeout = timeout_seconds

    async def read(self, reference: CredentialReference) -> SecretStr:
        try:
            return await asyncio.wait_for(self._read(reference), self._timeout + 5.0)
        except ConnectorCredentialUnavailableError:
            raise
        except Exception:
            # Includes timeouts, transport errors and token failures: one code, no detail.
            raise ConnectorCredentialUnavailableError from None

    async def _read(self, reference: CredentialReference) -> SecretStr:
        if reference.kind != "key_vault_secret" or reference.secret_uri is None:
            raise ConnectorCredentialUnavailableError
        try:
            parsed = parse_key_vault_secret(reference.secret_uri, self._cloud.value)
        except NeuroSphereError:
            raise ConnectorCredentialUnavailableError from None
        path = f"/secrets/{parsed.name}" + (f"/{parsed.version}" if parsed.version else "")
        token = await self._token()
        async with httpx.AsyncClient(
            transport=self._transport, timeout=httpx.Timeout(self._timeout), follow_redirects=False
        ) as client:
            response = await client.get(
                f"https://{parsed.host}{path}",
                params={"api-version": API_VERSION},
                headers={"Authorization": f"Bearer {token}"},
            )
        if response.status_code != 200:
            raise ConnectorCredentialUnavailableError
        try:
            value = response.json().get("value")
        except ValueError:
            raise ConnectorCredentialUnavailableError from None
        if not isinstance(value, str) or not value:
            raise ConnectorCredentialUnavailableError
        return SecretStr(value)
