"""Bearer-token HTTP transport for the deploy apply (PRP-55 item 3).

:class:`BearerDeployHttp` implements the core ``FabricHttp`` seam over ``httpx`` for both hosts a
deploy apply talks to: the deployment cloud's ARM management host (scope
``<CloudProfile.management_url>.default``) and, when Fabric is available, the Fabric REST host
(``FabricEndpoints.token_scope``). Each host is mapped to exactly one token scope; a URL whose
host is not in that map, or that is not ``https``, is refused before any token is requested, so
a token for one cloud can never be sent to another cloud's host.

The credential is resolved lazily (a callable) so composing the worker never creates one unless a
request is made. No URL, token or body is logged (ARM URLs carry the subscription id and the
repo is public).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Final
from urllib.parse import urlsplit

import httpx
from azure.core.credentials_async import AsyncTokenCredential
from neurosphere_core.cloud import CloudProfile
from neurosphere_core.deploy.fabric import FabricEndpoints, FabricResponse
from neurosphere_core.errors import DependencyTransientError, InvalidSchemaError

__all__ = ["DEFAULT_TIMEOUT", "BearerDeployHttp", "arm_token_scope", "deploy_scopes"]

DEFAULT_TIMEOUT: Final = httpx.Timeout(30.0)


def arm_token_scope(profile: CloudProfile) -> str:
    """ARM token audience of the deployment's cloud (never another cloud's)."""
    return f"{profile.management_url}.default"


def deploy_scopes(profile: CloudProfile, fabric: FabricEndpoints | None = None) -> dict[str, str]:
    """Host -> token scope for one deployment cloud. Fabric hosts only when ``fabric`` is given
    (and its cloud equals the profile's: never bridged)."""
    scopes = {profile.management_host.lower(): arm_token_scope(profile)}
    if fabric is not None:
        if fabric.cloud is not profile.cloud:
            raise InvalidSchemaError(
                "the Fabric endpoints belong to another cloud", reason="cloud_mismatch"
            )
        host = urlsplit(fabric.fabric_api_base).hostname or ""
        scopes[host.lower()] = fabric.token_scope
    return scopes


class BearerDeployHttp:
    """``FabricHttp`` over ``httpx`` with a per-host bearer token (ARM and Fabric)."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        credential: Callable[[], AsyncTokenCredential],
        scopes: Mapping[str, str],
    ) -> None:
        if not scopes:
            raise ValueError("at least one host scope is required")
        self._client = client
        self._credential = credential
        self._scopes = {host.lower(): scope for host, scope in scopes.items()}

    @property
    def hosts(self) -> frozenset[str]:
        return frozenset(self._scopes)

    def _scope_for(self, url: str) -> str:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        scope = self._scopes.get(host)
        if parts.scheme != "https" or scope is None:
            raise InvalidSchemaError(
                "the request host is not a deploy host of this cloud", reason="host_not_allowed"
            )
        return scope

    async def request(
        self, method: str, url: str, json: Mapping[str, Any] | None = None
    ) -> FabricResponse:
        scope = self._scope_for(url)
        token = await self._credential().get_token(scope)
        headers = {"Authorization": f"Bearer {token.token}", "Accept": "application/json"}
        try:
            response = await self._client.request(
                method, url, headers=headers, json=dict(json) if json is not None else None
            )
        except httpx.HTTPError:
            raise DependencyTransientError(
                "the deploy host is unreachable", reason="deploy_host_unreachable"
            ) from None
        return FabricResponse(
            status_code=response.status_code,
            body=_body(response),
            headers={k.lower(): v for k, v in response.headers.items()},
        )


def _body(response: httpx.Response) -> Mapping[str, Any] | None:
    if not response.content:
        return None
    try:
        data = response.json()
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    return {str(k): v for k, v in data.items()}  # pyright: ignore[reportUnknownVariableType]
