"""Token provider type and the production default (managed identity / DefaultAzureCredential).

Tests inject a fake ``TokenProvider``; ``azure-identity`` is imported lazily so importing the
connector never touches it. No token or secret is stored on the connector.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from neurosphere_core.cloud.profile import CloudName

__all__ = ["ManagedIdentityTokenProvider", "TokenProvider"]

TokenProvider = Callable[[str], Awaitable[str]]
"""Async callable: OAuth scope in, bearer access token out."""


class ManagedIdentityTokenProvider:  # pragma: no cover - needs a real Azure identity
    """``DefaultAzureCredential`` for the selected cloud's authority host."""

    def __init__(self, cloud: CloudName) -> None:
        from azure.identity import AzureAuthorityHosts
        from azure.identity.aio import DefaultAzureCredential

        authority = (
            AzureAuthorityHosts.AZURE_GOVERNMENT
            if cloud is CloudName.GOVERNMENT
            else AzureAuthorityHosts.AZURE_PUBLIC_CLOUD
        )
        self._credential: Any = DefaultAzureCredential(authority=authority)

    async def __call__(self, scope: str) -> str:
        token = await self._credential.get_token(scope)
        return str(token.token)

    async def aclose(self) -> None:
        await self._credential.close()
