"""The ARM surface the APIM write connector needs, and its REST implementation.

``ApimArm`` is the narrow protocol the planner and applier use (GET, PUT with ``If-Match``,
DELETE with ``If-Match``) on paths RELATIVE to one API Management service. ``HttpApimArm`` wraps
the bearer-authenticated ``httpx.AsyncClient`` from ``neurosphere_core.clients.arm_client``
(PRP-33's ARM client), so token handling and cloud-host checks stay in one place.

Hard rules enforced here, not by convention:

- Only ``GET``, ``PUT`` and ``DELETE`` exist. There is no ``POST``, so ``listSecrets``,
  ``listValue`` and ``listKeys`` cannot be called; a path naming one is refused before any I/O.
- Paths are validated against the resource kinds the connector writes (``classify_path``), so a
  name can never address another provider or climb out of the service.
- Subscription keys (``primaryKey``/``secondaryKey``) and named-value ``value`` fields are
  removed from every response and refused in every request body.
- Errors map by status code only; no request or response body (which may hold policy XML with
  named-value references) is placed in an exception or a log line.
- ``412`` maps to ``stale_version`` (reason ``etag_mismatch``). ``429`` honours ``Retry-After``
  for a bounded number of retries and then maps to ``dependency_transient`` carrying the wait.

``ApimPermissionsReader`` (PRP-34 item 2) is the one read outside the resource tree: a ``GET`` of
``Microsoft.Authorization/permissions`` at the service scope, used by the manage-mode preflight.
Only ``actions`` and ``notActions`` are kept from it.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Final, Protocol, cast, runtime_checkable
from urllib.parse import urlsplit

import httpx
from neurosphere_core.clients import assert_host_in_cloud
from neurosphere_core.cloud import CloudProfile
from neurosphere_core.errors import (
    DependencyTransientError,
    ForbiddenError,
    InvalidSchemaError,
    NeuroSphereError,
    StaleVersionError,
    UnauthorizedError,
)
from neurosphere_core.gateway.mode import PERMISSIONS_API_VERSION
from neurosphere_core.gateway.models import normalize_arm_id

from neurosphere_connector_apim_gateway.models import ResourceType, classify_path

__all__ = [
    "APIM_API_VERSION",
    "PERMISSIONS_PATH",
    "ApimArm",
    "ApimPermissionsReader",
    "ArmResource",
    "HttpApimArm",
    "check_path",
    "map_status",
    "permission_entries",
    "strip_secrets",
]

#: Relative to the service id: the caller's effective role permissions at the gateway scope.
PERMISSIONS_PATH: Final = "providers/Microsoft.Authorization/permissions"
MAX_PERMISSION_PAGES: Final = 10

# v2 tiers and the AI gateway policies need api-version 2024-05-01 or later (Learn, v2 tiers
# overview); PRP-33's inventory reads pin the same version.
APIM_API_VERSION: Final = "2024-05-01"
MAX_RETRIES: Final = 3
MAX_RETRY_AFTER_SECONDS: Final = 60.0
_DEFAULT_RETRY_AFTER: Final = 5.0
_FORBIDDEN_ACTION = re.compile(r"(^|/)(listsecrets|listvalue|listkeys|regenerate[a-z]*)$")
_SECRET_FIELDS: Final = frozenset({"primaryKey", "secondaryKey"})
_RAWXML_TYPES: Final = frozenset(
    {ResourceType.POLICY_FRAGMENT, ResourceType.API_POLICY, ResourceType.PRODUCT_POLICY}
)

Sleep = Callable[[float], Awaitable[None]]


@dataclass(frozen=True)
class ArmResource:
    """A resource as read from ARM: secret-bearing fields already removed."""

    path: str
    properties: dict[str, Any] = field(default_factory=dict[str, Any])
    etag: str | None = None


@runtime_checkable
class ApimArm(Protocol):
    """Relative-path access to ONE API Management service. ``""`` addresses the service."""

    async def get(self, path: str) -> ArmResource | None:
        """The resource, or None when ARM answers 404."""
        ...

    async def put(self, path: str, properties: Mapping[str, Any], *, if_match: str | None) -> None:
        """Create (``if_match`` None) or update (``if_match`` = ETag of the preceding read)."""
        ...

    async def delete(self, path: str, *, if_match: str) -> bool:
        """Delete with ``If-Match``; False when the resource was already gone."""
        ...


@runtime_checkable
class ApimPermissionsReader(Protocol):
    async def permissions(self) -> list[dict[str, Any]]:
        """``{"actions": [...], "notActions": [...]}`` per permission entry at the service."""
        ...


def permission_entries(body: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The ``actions``/``notActions`` of every entry in one permissions page (nothing else)."""
    value = body.get("value")
    if not isinstance(value, list):
        raise DependencyTransientError(
            "ARM returned an unexpected body", reason="arm_invalid_body", upstream_invalid=True
        )
    entries: list[dict[str, Any]] = []
    for item in cast(list[object], value):
        if not isinstance(item, Mapping):
            continue
        entry = cast(Mapping[str, Any], item)
        entries.append(
            {
                key: [a for a in cast(list[object], entry.get(key) or []) if isinstance(a, str)]
                for key in ("actions", "notActions")
            }
        )
    return entries


def check_path(path: str, *, allow_service: bool = False) -> ResourceType | None:
    """Refuse secret-listing actions and any path that is not a resource we write."""
    if _FORBIDDEN_ACTION.search(path.lower()):
        raise InvalidSchemaError("secret-listing actions are never called", reason="forbidden_path")
    if path == "" and allow_service:
        return None
    rtype = classify_path(path)
    if rtype is None:
        raise InvalidSchemaError(
            "not an APIM resource path this connector writes", reason="bad_path"
        )
    return rtype


def strip_secrets(rtype: ResourceType | None, properties: Mapping[str, Any]) -> dict[str, Any]:
    """Drop subscription keys and named-value values; nothing secret leaves this function."""
    out = {k: v for k, v in properties.items() if k not in _SECRET_FIELDS}
    if rtype is ResourceType.NAMED_VALUE:
        out.pop("value", None)
    return out


def _secret_in_body(rtype: ResourceType | None, properties: Mapping[str, Any]) -> bool:
    if any(k in properties for k in _SECRET_FIELDS):
        return True
    return rtype is ResourceType.NAMED_VALUE and "value" in properties


def map_status(status: int, *, retry_after: float | None = None) -> NeuroSphereError:
    """Non-2xx ARM status to the PRP-17 D3 taxonomy, by status code only."""
    if status == 401:
        return UnauthorizedError()
    if status == 403:
        return ForbiddenError()
    if status == 404:
        return InvalidSchemaError("APIM resource not found", reason="target_not_found")
    if status == 412:
        return StaleVersionError("the resource changed since it was read", reason="etag_mismatch")
    if status == 409:
        return StaleVersionError("ARM reported a conflict", reason="arm_conflict")
    if status == 429:
        wait = retry_after if retry_after is not None else _DEFAULT_RETRY_AFTER
        return DependencyTransientError(
            "ARM throttled the request",
            reason="arm_rate_limited",
            retry_after_seconds=max(1, int(wait)),
        )
    if status >= 500:
        return DependencyTransientError("ARM is unavailable", reason="arm_unavailable")
    return InvalidSchemaError("ARM rejected the request", reason="arm_rejected")


def _retry_after(response: httpx.Response) -> float | None:
    raw = response.headers.get("Retry-After", "").strip()
    try:
        seconds = float(raw)
    except ValueError:
        return None
    return min(max(seconds, 0.0), MAX_RETRY_AFTER_SECONDS)


class HttpApimArm:
    """``ApimArm`` over ARM REST, using a client from ``neurosphere_core.clients.arm_client``."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        service_arm_id: str,
        *,
        profile: CloudProfile | None = None,
        api_version: str = APIM_API_VERSION,
        sleep: Sleep = asyncio.sleep,
        max_retries: int = MAX_RETRIES,
    ) -> None:
        self._client = client
        self._service = normalize_arm_id(service_arm_id)
        self._profile = profile
        self._api_version = api_version
        self._sleep = sleep
        self._max_retries = max_retries
        if profile is not None:
            assert_host_in_cloud(profile, str(client.base_url))

    def _url(self, path: str, rtype: ResourceType | None, *, read: bool) -> str:
        url = f"{self._service}/{path}" if path else self._service
        url = f"{url}?api-version={self._api_version}"
        if read and rtype in _RAWXML_TYPES:
            url += "&format=rawxml"
        return url

    async def _send(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        body: Mapping[str, Any] | None = None,
    ) -> httpx.Response:
        if self._profile is not None:
            assert_host_in_cloud(self._profile, str(self._client.base_url))
        attempt = 0
        while True:
            try:
                response = await self._client.request(
                    method, url, headers=dict(headers or {}), json=body
                )
            except (httpx.TransportError, httpx.TimeoutException):
                raise DependencyTransientError(
                    "ARM is unreachable", reason="arm_unreachable"
                ) from None
            if response.status_code != 429:
                return response
            wait = _retry_after(response)
            if attempt >= self._max_retries:
                raise map_status(429, retry_after=wait)
            attempt += 1
            await self._sleep(wait if wait is not None else _DEFAULT_RETRY_AFTER)

    @staticmethod
    def _etag(response: httpx.Response, body: Mapping[str, Any]) -> str | None:
        header = response.headers.get("ETag")
        if header:
            return header
        etag = body.get("etag")
        return str(etag) if isinstance(etag, str) and etag else None

    async def get(self, path: str) -> ArmResource | None:
        rtype = check_path(path, allow_service=True)
        response = await self._send("GET", self._url(path, rtype, read=True))
        if response.status_code == 404:
            return None
        if response.status_code >= 300:
            raise map_status(response.status_code)
        try:
            body = response.json()
        except ValueError:
            raise DependencyTransientError(
                "ARM returned a non-JSON body", reason="arm_invalid_body", upstream_invalid=True
            ) from None
        if not isinstance(body, dict):
            raise DependencyTransientError(
                "ARM returned an unexpected body", reason="arm_invalid_body", upstream_invalid=True
            )
        doc: dict[str, Any] = {str(k): v for k, v in body.items()}  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]
        props = doc.get("properties")
        properties: dict[str, Any] = (
            {str(k): v for k, v in props.items()}  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]
            if isinstance(props, dict)
            else {}
        )
        return ArmResource(
            path=path,
            properties=strip_secrets(rtype, properties),
            etag=self._etag(response, doc),
        )

    async def put(self, path: str, properties: Mapping[str, Any], *, if_match: str | None) -> None:
        rtype = check_path(path)
        if _secret_in_body(rtype, properties):
            raise InvalidSchemaError("secret material is never written", reason="secret_in_payload")
        headers = {"If-Match": if_match} if if_match else {}
        response = await self._send(
            "PUT",
            self._url(path, rtype, read=False),
            headers=headers,
            body={"properties": dict(properties)},
        )
        if response.status_code >= 300:
            raise map_status(response.status_code)

    async def delete(self, path: str, *, if_match: str) -> bool:
        rtype = check_path(path)
        response = await self._send(
            "DELETE", self._url(path, rtype, read=False), headers={"If-Match": if_match}
        )
        if response.status_code == 404:
            return False
        if response.status_code >= 300:
            raise map_status(response.status_code)
        return True

    async def permissions(self) -> list[dict[str, Any]]:
        """GET ``Microsoft.Authorization/permissions`` at the service (pages on the same host)."""
        url = f"{self._service}/{PERMISSIONS_PATH}?api-version={PERMISSIONS_API_VERSION}"
        base = urlsplit(str(self._client.base_url))
        entries: list[dict[str, Any]] = []
        for _ in range(MAX_PERMISSION_PAGES):
            response = await self._send("GET", url)
            if response.status_code >= 300:
                raise map_status(response.status_code)
            try:
                body = response.json()
            except ValueError:
                raise DependencyTransientError(
                    "ARM returned a non-JSON body", reason="arm_invalid_body", upstream_invalid=True
                ) from None
            if not isinstance(body, dict):
                raise DependencyTransientError(
                    "ARM returned an unexpected body",
                    reason="arm_invalid_body",
                    upstream_invalid=True,
                )
            page = cast(dict[str, Any], body)
            entries.extend(permission_entries(page))
            next_link = page.get("nextLink")
            if not isinstance(next_link, str) or not next_link:
                return entries
            target = urlsplit(next_link)
            if target.scheme != "https" or target.netloc.lower() != base.netloc.lower():
                raise DependencyTransientError(
                    "ARM paging left the management host", reason="arm_invalid_body"
                )
            url = next_link
        raise DependencyTransientError("too many permission pages", reason="arm_paging_limit")
