"""A fake ARM management plane for the deploy apply tests (PRP-55): an ``httpx.MockTransport``
handler that keeps resource groups and resources in memory and answers GET/PUT like ARM,
including a 201 + ``Azure-AsyncOperation`` long-running create. No network, nothing paid."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

import httpx
from azure.core.credentials import AccessToken
from neurosphere_core.cloud import CloudName, profile_for

SUB = "aaaaaaaa-0000-4000-8000-000000000001"
RG = "rg-neurosphere"


class FakeCredential:
    """Records the scopes asked for; the token is a fixed non-secret marker."""

    def __init__(self) -> None:
        self.scopes: list[str] = []

    async def get_token(self, *scopes: str, **_: Any) -> AccessToken:
        self.scopes.extend(scopes)
        return AccessToken("fake-token-not-a-secret", 4102444800)

    async def close(self) -> None:
        return None

    async def __aenter__(self) -> FakeCredential:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None


@dataclass
class FakeArm:
    cloud: CloudName = CloudName.COMMERCIAL
    groups: set[str] = field(default_factory=lambda: {f"/subscriptions/{SUB}/resourcegroups/{RG}"})
    resources: dict[str, dict[str, Any]] = field(default_factory=dict)
    calls: list[tuple[str, str]] = field(default_factory=list)
    hosts: list[str] = field(default_factory=list)
    payloads: list[dict[str, Any]] = field(default_factory=list)
    #: Number of "InProgress" answers an async operation gives before "Succeeded".
    lro_polls: int = 1
    #: When set, a created resource vanishes right after creation (a pretend apply).
    drop_after_create: bool = False
    _operations: dict[str, int] = field(default_factory=dict)

    @property
    def host(self) -> str:
        return profile_for(self.cloud).management_host

    def handler(self, request: httpx.Request) -> httpx.Response:
        parts = urlsplit(str(request.url))
        self.hosts.append(parts.hostname or "")
        path = parts.path
        self.calls.append((request.method, path))
        key = path.lower()
        if path.startswith("/operations/"):
            remaining = self._operations.get(path, 0)
            if remaining > 0:
                self._operations[path] = remaining - 1
                return httpx.Response(200, json={"status": "InProgress"})
            return httpx.Response(200, json={"status": "Succeeded"})
        if "/providers/" not in key:  # a resource group
            if request.method == "GET":
                return httpx.Response(200 if key in self.groups else 404, json={})
            return httpx.Response(405)
        if request.method == "GET":
            found = self.resources.get(key)
            if found is None:
                return httpx.Response(404, json={"error": {"code": "ResourceNotFound"}})
            return httpx.Response(200, json=found)
        if request.method == "PUT":
            body = json.loads(request.content or b"{}")
            self.payloads.append(body)
            stored = {**body, "id": path, "properties": {"provisioningState": "Succeeded"}}
            if not self.drop_after_create:
                self.resources[key] = stored
            operation = f"/operations/{len(self._operations) + 1}"
            self._operations[operation] = self.lro_polls
            return httpx.Response(
                201,
                json={**body, "properties": {"provisioningState": "Creating"}},
                headers={
                    "Azure-AsyncOperation": f"https://{self.host}{operation}?api-version=x",
                    "Retry-After": "1",
                },
            )
        return httpx.Response(405)

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))

    def put_bodies(self) -> list[str]:
        return [p for m, p in self.calls if m == "PUT"]


async def no_sleep(_: float) -> None:
    return None
