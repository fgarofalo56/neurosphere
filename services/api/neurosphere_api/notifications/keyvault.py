"""Key Vault secret reader for the notification test send (PRP-107 item 7).

The API cannot import ``neurosphere_workers``, so this imitates the workers' reader
(``connector_config/keyvault.py``): ``GET https://<vault>/secrets/<name>[/<version>]`` over
``httpx`` with a workload-identity bearer token for the deployment cloud's vault scope. The vault
host is checked as a DNS-label match for the cloud before any token is requested. Every failure
raises :class:`NotificationCredentialUnavailableError`, whose message is a fixed reason code: never
the URI, the vault, the secret name or the value.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any, Final

import httpx
from neurosphere_contracts.admin.v1.credential_reference import CredentialReference
from neurosphere_core.admin.connectors import parse_key_vault_secret
from neurosphere_core.cloud import CloudName, profile_for
from neurosphere_core.errors import NeuroSphereError
from pydantic import SecretStr

__all__ = [
    "API_VERSION",
    "REASON",
    "KeyVaultSecretReader",
    "NotificationCredentialUnavailableError",
    "TokenProvider",
    "default_vault_token_provider",
]

API_VERSION: Final = "7.4"
REASON: Final = "credential_unavailable"
_SCOPES: Final = {
    CloudName.COMMERCIAL: "https://vault.azure.net/.default",
    CloudName.GOVERNMENT: "https://vault.usgovcloudapi.net/.default",
}

TokenProvider = Callable[[], Awaitable[str]]


class _DropVaultRequests(logging.Filter):
    """httpx logs every request URL at INFO; a Key Vault URL never leaves the process."""

    def filter(self, record: logging.LogRecord) -> bool:
        return "/secrets/" not in record.getMessage()


logging.getLogger("httpx").addFilter(_DropVaultRequests())


class NotificationCredentialUnavailableError(Exception):
    """The secret could not be read. ``reason`` is a machine code; nothing else."""

    reason: str = REASON

    def __init__(self) -> None:
        super().__init__(REASON)


def default_vault_token_provider(cloud: CloudName) -> TokenProvider:
    """``DefaultAzureCredential`` (workload identity) with the cloud's Key Vault scope."""
    scope = _SCOPES[cloud]
    authority = profile_for(cloud).login_host

    async def provide() -> str:
        from azure.identity import DefaultAzureCredential

        options: dict[str, Any] = {"authority": authority}
        credential = DefaultAzureCredential(**options)
        try:
            token = await asyncio.to_thread(credential.get_token, scope)
        finally:
            credential.close()
        return token.token

    return provide


class KeyVaultSecretReader:
    """Reads one secret per call; holds no secret and logs nothing."""

    def __init__(
        self,
        *,
        cloud: CloudName,
        token_provider: TokenProvider | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        self._cloud = cloud
        self._token = token_provider or default_vault_token_provider(cloud)
        self._transport = transport
        self._timeout = timeout_seconds

    async def read(self, reference: CredentialReference) -> SecretStr:
        try:
            return await asyncio.wait_for(self._read(reference), self._timeout + 5.0)
        except NotificationCredentialUnavailableError:
            raise
        except Exception:
            # Includes timeouts, transport errors and token failures: one code, no detail.
            raise NotificationCredentialUnavailableError from None

    async def _read(self, reference: CredentialReference) -> SecretStr:
        if reference.kind != "key_vault_secret" or reference.secret_uri is None:
            raise NotificationCredentialUnavailableError
        try:
            parsed = parse_key_vault_secret(reference.secret_uri, self._cloud.value)
        except NeuroSphereError:
            raise NotificationCredentialUnavailableError from None
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
            raise NotificationCredentialUnavailableError
        try:
            value = response.json().get("value")
        except ValueError:
            raise NotificationCredentialUnavailableError from None
        if not isinstance(value, str) or not value:
            raise NotificationCredentialUnavailableError
        return SecretStr(value)
