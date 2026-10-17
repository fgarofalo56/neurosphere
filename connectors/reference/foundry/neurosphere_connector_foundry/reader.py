"""Read side of the Foundry project: a small protocol plus the documented-SDK adapter.

The adapter uses only operations documented in the ``azure-ai-projects`` Python reference
(observed 2026-10-17): ``AIProjectClient(endpoint, credential, *, allow_preview=False)``,
``agents.list(*, kind, limit, order, before)`` and
``deployments.list(*, model_publisher, model_name, deployment_type)``. The async client lives in
``azure.ai.projects.aio``. https://learn.microsoft.com/python/api/azure-ai-projects/

``allow_preview`` defaults to False and is only set when the caller passes it explicitly; it is
never enabled implicitly. For Government the documented ``credential_scopes`` is passed
(https://learn.microsoft.com/azure/foundry/agents/concepts/azure-government).

The SDK import is lazy so that importing this package, and every test, needs no network and no
live client. Credentials are injected by the caller (an async token credential); this module
never creates one.
"""

from __future__ import annotations

import importlib
from collections.abc import AsyncIterator, Mapping
from typing import Any, Protocol

from neurosphere_core.cloud.profile import CloudName
from neurosphere_core.errors import (
    DependencyTransientError,
    ForbiddenError,
    NeuroSphereError,
    RateLimitedError,
    UnauthorizedError,
)

from neurosphere_connector_foundry.endpoints import FOUNDRY_ENDPOINTS

__all__ = ["FoundryProjectReader", "SdkProjectReader", "map_sdk_error"]

_PAGE_SIZE = 50  # request page size; the connector's item budget bounds total reads


class FoundryProjectReader(Protocol):
    """What the connector needs; tests inject a fake, production uses ``SdkProjectReader``."""

    def list_agents(self, *, page_size: int) -> AsyncIterator[Mapping[str, Any]]: ...

    def list_deployments(self) -> AsyncIterator[Mapping[str, Any]]: ...

    async def close(self) -> None: ...


def _plain(item: Any, fields: tuple[str, ...]) -> dict[str, Any]:
    return {name: getattr(item, name, None) for name in fields}


def map_sdk_error(exc: Exception) -> NeuroSphereError:
    """Map an SDK/HTTP failure to the taxonomy by status code only (no response text copied)."""
    if isinstance(exc, NeuroSphereError):
        return exc
    status = getattr(exc, "status_code", None)
    if status == 429:
        return RateLimitedError(retry_after_seconds=30)
    if status == 401:
        return UnauthorizedError()
    if status == 403:
        return ForbiddenError()
    return DependencyTransientError()


_AGENT_FIELDS = ("id", "name", "versions")
_DEPLOYMENT_FIELDS = (
    "name",
    "type",
    "model_name",
    "model_version",
    "model_publisher",
    "sku",
    "capabilities",
    "connection_name",
)


class SdkProjectReader:
    """Reader over ``azure.ai.projects.aio.AIProjectClient`` (lazy import, injected credential)."""

    def __init__(
        self,
        *,
        endpoint: str,
        credential: Any,
        cloud: CloudName,
        allow_preview: bool = False,
    ) -> None:
        module = importlib.import_module("azure.ai.projects.aio")
        kwargs: dict[str, Any] = {"allow_preview": allow_preview}
        if cloud is CloudName.GOVERNMENT:
            kwargs["credential_scopes"] = [FOUNDRY_ENDPOINTS[cloud].token_scope]
        self._client: Any = module.AIProjectClient(endpoint, credential, **kwargs)

    async def list_agents(self, *, page_size: int = _PAGE_SIZE) -> AsyncIterator[Mapping[str, Any]]:
        try:
            async for item in self._client.agents.list(limit=page_size):
                yield _plain(item, _AGENT_FIELDS)
        except Exception as exc:
            raise map_sdk_error(exc) from None

    async def list_deployments(self) -> AsyncIterator[Mapping[str, Any]]:
        try:
            async for item in self._client.deployments.list():
                yield _plain(item, _DEPLOYMENT_FIELDS)
        except Exception as exc:
            raise map_sdk_error(exc) from None

    async def close(self) -> None:
        await self._client.close()
