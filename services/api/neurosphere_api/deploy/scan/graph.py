"""Azure Resource Graph reader: a Protocol plus an httpx implementation.

Read-only by construction. The only non-GET request is the Resource Graph query POST; the query
text is the fixed module constant :data:`SCAN_QUERY`. Hosts come from the injected
``CloudProfile``; no endpoint literal lives here.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Final, Protocol

import httpx
from azure.core.credentials_async import AsyncTokenCredential
from neurosphere_core.cloud import CloudProfile
from neurosphere_core.errors import DependencyTransientError, ForbiddenError

ARG_PATH: Final = "providers/Microsoft.ResourceGraph/resources"
ARG_API_VERSION: Final = "2024-04-01"
SUBSCRIPTIONS_PATH: Final = "subscriptions"
SUBSCRIPTIONS_API_VERSION: Final = "2022-12-01"
_ARG_BATCH: Final = 1000
_MAX_LIST_PAGES: Final = 50

#: Resource type (lower case) to scan category. Single source for the query and the mapping.
TYPE_CATEGORY: Final[dict[str, str]] = {
    "microsoft.apimanagement/service": "apim",
    "microsoft.cognitiveservices/accounts": "model_endpoint",
    "microsoft.keyvault/vaults": "key_vault",
    "microsoft.operationalinsights/workspaces": "monitoring",
    "microsoft.insights/components": "monitoring",
    "microsoft.eventhub/namespaces": "event_hubs",
    "microsoft.storage/storageaccounts": "storage",
    "microsoft.fabric/capacities": "analytics_workspace",
    "microsoft.synapse/workspaces": "analytics_workspace",
    "microsoft.databricks/workspaces": "analytics_workspace",
}

_TYPES = ", ".join(f"'{t}'" for t in TYPE_CATEGORY)
SCAN_QUERY: Final = (
    "Resources "
    f"| where type in~ ({_TYPES}) "
    "| where type !~ 'microsoft.cognitiveservices/accounts' "
    "or kind in~ ('OpenAI', 'AIServices') "
    "| project id, name, type, location, subscriptionId, tags, sku = tostring(sku.name)"
)


class ResourceGraphReader(Protocol):
    async def list_readable_subscriptions(self) -> frozenset[str]:
        """Subscription ids (lower case) the caller's identity can read."""
        ...

    async def query(self, subscriptions: Sequence[str], query: str) -> list[dict[str, Any]]:
        """Run ``query`` over ``subscriptions`` and return all rows (paged to completion)."""
        ...


class HttpxResourceGraphReader:
    def __init__(
        self,
        credential: AsyncTokenCredential,
        profile: CloudProfile,
        *,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 30.0,
        page_size: int = 1000,
        max_pages: int = 50,
    ) -> None:
        self._credential = credential
        self._base = profile.management_url
        self._client = client
        self._timeout = timeout_seconds
        self._page_size = page_size
        self._max_pages = max_pages

    async def _headers(self) -> dict[str, str]:
        try:
            token = await self._credential.get_token(f"{self._base}.default")
        except Exception as exc:
            raise DependencyTransientError(
                "management token unavailable", reason="arm_token_unavailable"
            ) from exc
        return {"Authorization": f"Bearer {token.token}"}

    async def _send(
        self, method: str, url: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        headers = await self._headers()
        try:
            if self._client is not None:
                response = await self._send_with(self._client, method, url, headers, payload)
            else:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    response = await self._send_with(client, method, url, headers, payload)
        except httpx.HTTPError as exc:
            raise DependencyTransientError(
                "resource graph unreachable", reason="arg_unreachable"
            ) from exc
        return self._body(response)

    @staticmethod
    async def _send_with(
        client: httpx.AsyncClient,
        method: str,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any] | None,
    ) -> httpx.Response:
        if method == "GET":
            return await client.get(url, headers=headers)
        return await client.post(url, headers=headers, json=payload)

    @staticmethod
    def _body(response: httpx.Response) -> dict[str, Any]:
        status = response.status_code
        if status == 429 or status >= 500:
            retry_after: int | None = None
            raw = response.headers.get("retry-after", "")
            if raw.isdigit():
                retry_after = int(raw)
            raise DependencyTransientError(
                "resource graph throttled or unavailable",
                reason="arg_throttled" if status == 429 else "arg_unavailable",
                retry_after_seconds=retry_after,
            )
        if status in (401, 403):
            raise ForbiddenError("management access denied", reason="arm_forbidden")
        if status >= 400:
            raise DependencyTransientError("resource graph rejected request", reason="arg_error")
        try:
            body = response.json()
        except ValueError as exc:
            raise DependencyTransientError(
                "resource graph returned invalid JSON", reason="arg_error"
            ) from exc
        if not isinstance(body, dict):
            raise DependencyTransientError(
                "resource graph returned invalid body", reason="arg_error"
            )
        return body

    async def list_readable_subscriptions(self) -> frozenset[str]:
        url: str | None = (
            f"{self._base}{SUBSCRIPTIONS_PATH}?api-version={SUBSCRIPTIONS_API_VERSION}"
        )
        found: set[str] = set()
        pages = 0
        while url is not None:
            pages += 1
            if pages > _MAX_LIST_PAGES:
                raise DependencyTransientError("too many subscription pages", reason="arg_error")
            body = await self._send("GET", url)
            for item in body.get("value", []):
                sub = item.get("subscriptionId") if isinstance(item, dict) else None
                if isinstance(sub, str):
                    found.add(sub.lower())
            next_link = body.get("nextLink")
            # Only follow a continuation that stays on the profile's management host.
            url = (
                next_link
                if isinstance(next_link, str) and next_link.startswith(self._base)
                else None
            )
        return frozenset(found)

    async def query(self, subscriptions: Sequence[str], query: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        url = f"{self._base}{ARG_PATH}?api-version={ARG_API_VERSION}"
        for start in range(0, len(subscriptions), _ARG_BATCH):
            batch = list(subscriptions[start : start + _ARG_BATCH])
            skip: str | None = None
            for _ in range(self._max_pages):
                options: dict[str, Any] = {"$top": self._page_size, "resultFormat": "objectArray"}
                if skip:
                    options["$skipToken"] = skip
                body = await self._send(
                    "POST",
                    url,
                    {"subscriptions": batch, "query": query, "options": options},
                )
                data = body.get("data", [])
                if not isinstance(data, list):
                    raise DependencyTransientError(
                        "resource graph returned unexpected data", reason="arg_error"
                    )
                rows.extend(r for r in data if isinstance(r, dict))
                token = body.get("$skipToken")
                skip = token if isinstance(token, str) and token else None
                if skip is None:
                    break
            else:
                raise DependencyTransientError(
                    "resource graph paging did not finish", reason="arg_error"
                )
        return rows
