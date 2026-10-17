"""Read side of the Foundry project: a small protocol plus a documented-REST adapter.

The adapter calls only two operations of the Microsoft Foundry project data-plane REST API
(reference: https://learn.microsoft.com/rest/api/microsoft-foundry/aiproject, observed 2026-10-17,
API version ``v1``, OAuth scope ``https://ai.azure.com/.default``):

- ``GET {endpoint}/agents?api-version=v1`` ("Agents - list agents"; query ``kind``, ``limit``
  1-100, ``order``, ``after``, ``before``).
- ``GET {endpoint}/deployments?api-version=v1`` ("Deployments - list"; returns
  ``PagedDeployment`` with ``value`` and ``nextLink``; ``Deployment`` fields ``name``, ``type``,
  ``modelName``, ``modelVersion``, ``modelPublisher``, ``sku``, ``capabilities``,
  ``connectionName``).

Why REST and not the ``azure-ai-projects`` SDK: the SDK's transitive chain pulls an
emscripten-only package whose licence cannot be established by the repo licence gate, and the
gate never defaults to permissive. These two list operations are documented REST, so the
reader uses ``httpx`` directly.

The agents list response is documented only as "an object", with no schema on the reference
page. The reader therefore reads ``data`` (list), ``has_more`` and ``last_id`` defensively (the
same envelope the page documents for other list responses) and never trusts them blindly:
a missing ``has_more`` falls back to "a full page means there may be more", and a cursor that
does not advance stops the loop with a partial result. ``Foundry-Features`` (the preview
opt-in header) is never sent; neither list operation needs it.

Pagination is bounded by an explicit page budget per list. When the budget is exhausted while
more pages remain, the reader stops and reports the source in ``budget_exceeded`` so the
connector can mark coverage partial. Credentials are injected as an async token provider; no
token, response body or URL query is ever placed in an exception message or log.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from typing import Any, Protocol
from urllib.parse import urljoin, urlsplit

import httpx
from neurosphere_core.cloud.profile import CloudName
from neurosphere_core.errors import (
    DependencyTransientError,
    ForbiddenError,
    NeuroSphereError,
    RateLimitedError,
    UnauthorizedError,
)

from neurosphere_connector_foundry.endpoints import FOUNDRY_ENDPOINTS

__all__ = [
    "API_VERSION",
    "FoundryProjectReader",
    "RestProjectReader",
    "TokenProvider",
    "default_token_provider",
    "map_http_status",
]

API_VERSION = "v1"
_AGENTS_MAX_LIMIT = 100  # documented range for `limit` is 1-100
_PAGE_SIZE = 50
DEFAULT_MAX_PAGES = 10
DEFAULT_MAX_RETRIES = 2
RETRY_AFTER_CAP_SECONDS = 30
_DEFAULT_RETRY_AFTER = 5

TokenProvider = Callable[[], Awaitable[str]]


class FoundryProjectReader(Protocol):
    """What the connector needs; tests inject a fake, production uses ``RestProjectReader``.

    A reader may also expose ``budget_exceeded: frozenset[str]`` (names ``"agents"`` and/or
    ``"deployments"``) naming lists cut short by the page budget; the connector reads it
    optionally.
    """

    def list_agents(self, *, page_size: int) -> AsyncIterator[Mapping[str, Any]]: ...

    def list_deployments(self) -> AsyncIterator[Mapping[str, Any]]: ...

    async def close(self) -> None: ...


def map_http_status(status: int, retry_after_seconds: int | None = None) -> NeuroSphereError:
    """Map a non-2xx status to the taxonomy by status code only (no body text copied)."""
    if status == 429:
        return RateLimitedError(retry_after_seconds=retry_after_seconds or _DEFAULT_RETRY_AFTER)
    if status == 401:
        return UnauthorizedError()
    if status == 403:
        return ForbiddenError()
    if status >= 500:
        return DependencyTransientError()
    return DependencyTransientError(upstream_invalid=True)


def default_token_provider(cloud: CloudName) -> TokenProvider:
    """Production default: ``DefaultAzureCredential`` (managed identity) with the cloud's scope.

    Imported lazily. The synchronous credential runs in a worker thread, so no async HTTP
    transport dependency is needed. Government uses the documented ``https://ai.azure.us``
    scope and authority host.
    """
    scope = FOUNDRY_ENDPOINTS[cloud].token_scope

    async def provide() -> str:
        from azure.identity import AzureAuthorityHosts, DefaultAzureCredential

        authority = AzureAuthorityHosts.AZURE_GOVERNMENT if cloud is CloudName.GOVERNMENT else None
        credential = DefaultAzureCredential(**({"authority": authority} if authority else {}))
        try:
            token = await asyncio.to_thread(credential.get_token, scope)
        finally:
            credential.close()
        return token.token

    return provide


def _retry_after(response: httpx.Response) -> int:
    raw = response.headers.get("retry-after", "")
    try:
        seconds = int(raw)
    except ValueError:
        seconds = _DEFAULT_RETRY_AFTER
    return max(0, min(seconds, RETRY_AFTER_CAP_SECONDS))


def _agent_row(item: Mapping[str, Any]) -> dict[str, Any]:
    return {"id": item.get("id"), "name": item.get("name"), "versions": item.get("versions")}


def _deployment_row(item: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "name": item.get("name"),
        "type": item.get("type"),
        "model_name": item.get("modelName"),
        "model_version": item.get("modelVersion"),
        "model_publisher": item.get("modelPublisher"),
        "sku": item.get("sku"),
        "capabilities": item.get("capabilities"),
        "connection_name": item.get("connectionName"),
    }


def _items(payload: Any, key: str) -> list[Mapping[str, Any]]:
    """Return the list under ``key``; a missing or non-list value is an invalid response."""
    if not isinstance(payload, Mapping):
        raise DependencyTransientError(upstream_invalid=True)
    raw: Any = payload.get(key)  # pyright: ignore[reportUnknownMemberType]
    if not isinstance(raw, list):
        raise DependencyTransientError(upstream_invalid=True)
    return [x for x in raw if isinstance(x, Mapping)]  # pyright: ignore[reportUnknownVariableType]


class RestProjectReader:
    """Reader over the documented Foundry project REST API with an injected token provider."""

    def __init__(
        self,
        *,
        endpoint: str,
        token_provider: TokenProvider,
        cloud: CloudName,
        client: httpx.AsyncClient | None = None,
        max_pages: int = DEFAULT_MAX_PAGES,
        max_retries: int = DEFAULT_MAX_RETRIES,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        timeout_seconds: float = 30.0,
    ) -> None:
        if max_pages < 1:
            raise ValueError("max_pages must be at least 1")
        if max_retries < 0:
            raise ValueError("max_retries must not be negative")
        parts = urlsplit(endpoint)
        suffix = FOUNDRY_ENDPOINTS[cloud].project_host_suffix
        # The bearer token is only ever sent to the cloud's documented Foundry host.
        if parts.scheme != "https" or not (parts.hostname or "").endswith(suffix):
            raise ValueError("endpoint must be an https Foundry project endpoint for this cloud")
        self._endpoint = endpoint.rstrip("/")
        self._origin = (parts.scheme, parts.netloc)
        self._token_provider = token_provider
        self._max_pages = max_pages
        self._max_retries = max_retries
        self._sleep = sleep
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)
        self._budget_exceeded: set[str] = set()

    @property
    def budget_exceeded(self) -> frozenset[str]:
        return frozenset(self._budget_exceeded)

    async def _get(self, url: str, params: Mapping[str, str] | None) -> Any:
        """One GET with bounded 429 backoff; returns parsed JSON or raises the taxonomy error."""
        attempt = 0
        while True:
            try:
                token = await self._token_provider()
            except Exception:
                raise UnauthorizedError() from None
            try:
                response = await self._client.get(
                    url,
                    params=params,
                    headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                )
            except httpx.HTTPError:
                raise DependencyTransientError() from None
            if response.status_code == 429:
                delay = _retry_after(response)
                if attempt >= self._max_retries:
                    raise RateLimitedError(retry_after_seconds=max(delay, 1))
                attempt += 1
                await self._sleep(delay)
                continue
            if not 200 <= response.status_code < 300:
                raise map_http_status(response.status_code)
            try:
                return response.json()
            except ValueError:
                raise DependencyTransientError(upstream_invalid=True) from None

    async def list_agents(self, *, page_size: int = _PAGE_SIZE) -> AsyncIterator[Mapping[str, Any]]:
        self._budget_exceeded.discard("agents")
        limit = max(1, min(page_size, _AGENTS_MAX_LIMIT))
        after: str | None = None
        for page in range(self._max_pages):
            params: dict[str, str] = {
                "api-version": API_VERSION,
                "limit": str(limit),
                "order": "asc",
            }
            if after is not None:
                params["after"] = after
            payload = await self._get(f"{self._endpoint}/agents", params)
            data = _items(payload, "data")
            for item in data:
                yield _agent_row(item)
            has_more: Any = payload.get("has_more")  # pyright: ignore[reportUnknownMemberType]
            more = has_more if isinstance(has_more, bool) else len(data) >= limit
            if not more or not data:
                return
            last_id: Any = payload.get("last_id")  # pyright: ignore[reportUnknownMemberType]
            cursor = last_id if isinstance(last_id, str) and last_id else data[-1].get("id")
            if not isinstance(cursor, str) or not cursor or cursor == after:
                # No usable, advancing cursor: stop rather than loop; result is partial.
                self._budget_exceeded.add("agents")
                return
            after = cursor
            if page == self._max_pages - 1:
                self._budget_exceeded.add("agents")

    async def list_deployments(self) -> AsyncIterator[Mapping[str, Any]]:
        self._budget_exceeded.discard("deployments")
        url = f"{self._endpoint}/deployments"
        params: dict[str, str] | None = {"api-version": API_VERSION}
        seen: set[str] = set()
        for page in range(self._max_pages):
            seen.add(url)
            payload = await self._get(url, params)
            for item in _items(payload, "value"):
                yield _deployment_row(item)
            next_link: Any = payload.get("nextLink")  # pyright: ignore[reportUnknownMemberType]
            if not isinstance(next_link, str) or not next_link:
                return
            url = urljoin(self._endpoint + "/", next_link)
            parts = urlsplit(url)
            if (parts.scheme, parts.netloc) != self._origin or url in seen:
                # Never follow a link off the Foundry host with the bearer token, or in a cycle.
                self._budget_exceeded.add("deployments")
                return
            params = None  # nextLink is a complete URL
            if page == self._max_pages - 1:
                self._budget_exceeded.add("deployments")

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()
