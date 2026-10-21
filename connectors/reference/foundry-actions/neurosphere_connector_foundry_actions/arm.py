"""Thin ARM REST client for the three documented operations the swap needs.

The credential is an injected ``azure.core`` async ``TokenCredential``; a token is requested per
call, used for one header and dropped. No token, request body or response body is placed in an
exception message or log: errors map by status code only.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx
from azure.core.credentials_async import AsyncTokenCredential
from neurosphere_core.errors import (
    DependencyTransientError,
    ForbiddenError,
    InvalidSchemaError,
    NeuroSphereError,
    RateLimitedError,
    StaleVersionError,
    UnauthorizedError,
)

from neurosphere_connector_foundry_actions.endpoints import AccountRef

__all__ = ["ArmClient", "map_status"]

DEFAULT_MAX_PAGES = 20
_DEFAULT_RETRY_AFTER = 5


def map_status(status: int, retry_after: int | None = None) -> NeuroSphereError:
    """Map a non-2xx ARM status to the taxonomy by status code only."""
    if status == 401:
        return UnauthorizedError()
    if status == 403:
        return ForbiddenError()
    if status == 404:
        return InvalidSchemaError("deployment or resource not found", reason="target_not_found")
    if status in (409, 412):
        return StaleVersionError("ARM reported a conflict", reason="target_version_changed")
    if status == 429:
        return RateLimitedError(retry_after_seconds=retry_after or _DEFAULT_RETRY_AFTER)
    if status >= 500:
        return DependencyTransientError()
    return InvalidSchemaError("ARM rejected the request", reason="arm_rejected")


class ArmClient:
    """Deployments Get/Put, Models List and Permissions List for one account."""

    def __init__(
        self,
        account: AccountRef,
        credential: AsyncTokenCredential,
        *,
        client: httpx.AsyncClient | None = None,
        max_pages: int = DEFAULT_MAX_PAGES,
    ) -> None:
        self.account = account
        self._credential = credential
        self._client = client or httpx.AsyncClient(timeout=30.0)
        self._owns_client = client is None
        self._max_pages = max_pages

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _send(
        self, method: str, url: str, body: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        token = await self._credential.get_token(self.account.token_scope)
        headers = {"Authorization": f"Bearer {token.token}", "Accept": "application/json"}
        try:
            response = await self._client.request(method, url, headers=headers, json=body)
        except httpx.HTTPError:
            raise DependencyTransientError(reason="arm_unreachable") from None
        if response.status_code >= 300:
            retry = response.headers.get("retry-after", "")
            raise map_status(response.status_code, int(retry) if retry.isdigit() else None)
        try:
            data = response.json()
        except ValueError:
            raise DependencyTransientError(upstream_invalid=True) from None
        if not isinstance(data, dict):
            raise DependencyTransientError(upstream_invalid=True)
        return {str(k): v for k, v in data.items()}  # pyright: ignore[reportUnknownVariableType]

    async def get_deployment(self, name: str) -> dict[str, Any]:
        return await self._send("GET", self.account.deployment_url(name))

    async def put_deployment(self, name: str, body: Mapping[str, Any]) -> dict[str, Any]:
        return await self._send("PUT", self.account.deployment_url(name), body)

    async def _list(self, url: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        next_url: str | None = url
        for _ in range(self._max_pages):
            if next_url is None:
                return items
            if not next_url.startswith(f"https://{self.account.host}/"):
                raise DependencyTransientError(upstream_invalid=True, reason="bad_next_link")
            page = await self._send("GET", next_url)
            value = page.get("value", [])
            if not isinstance(value, list):
                raise DependencyTransientError(upstream_invalid=True)
            items.extend(
                {str(k): v for k, v in row.items()}  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType]
                for row in value  # pyright: ignore[reportUnknownVariableType]
                if isinstance(row, dict)
            )
            link = page.get("nextLink")
            next_url = link if isinstance(link, str) and link else None
        if next_url is not None:
            # Incomplete list: refuse to decide on partial data.
            raise DependencyTransientError(upstream_invalid=True, reason="page_budget_exceeded")
        return items

    async def list_models(self) -> list[dict[str, Any]]:
        return await self._list(self.account.models_url())

    async def list_permissions(self) -> list[dict[str, Any]]:
        return await self._list(self.account.permissions_url())
