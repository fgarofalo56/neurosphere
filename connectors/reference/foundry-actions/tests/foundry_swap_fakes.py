"""Shared fakes for the swap connector tests: a scripted ARM over ``httpx.MockTransport``."""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from datetime import date
from types import TracebackType
from typing import Any

import httpx
from azure.core.credentials import AccessToken
from neurosphere_connector.write import WriteRequest
from neurosphere_connector_foundry_actions import AccountRef
from neurosphere_contracts.actions.v1.action_intent import PatchOperation, ProposedDiff
from neurosphere_contracts.actions.v1.target_ref import TargetRef
from neurosphere_core.cloud.profile import CloudName

SUB = "00000000-1111-2222-3333-444444444444"
ACCOUNT = AccountRef(
    cloud=CloudName.COMMERCIAL,
    subscription_id=SUB,
    resource_group="rg-ai",
    account="acct1",
    location="eastus2",
)
TODAY = date(2026, 10, 20)
TOKEN = "tok-secret-value"  # noqa: S105  # test fixture, not a credential


class FakeCredential:
    """Async TokenCredential stand-in; records the scopes it was asked for."""

    def __init__(self) -> None:
        self.scopes: list[tuple[str, ...]] = []

    async def get_token(self, *scopes: str, **_: Any) -> AccessToken:
        self.scopes.append(scopes)
        return AccessToken(TOKEN, 0)

    async def close(self) -> None:
        return None

    async def __aenter__(self) -> FakeCredential:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None = None,
        exc_value: BaseException | None = None,
        traceback: TracebackType | None = None,
    ) -> None:
        return None


def model_entry(
    name: str,
    version: str,
    *,
    skus: tuple[str, ...] = ("Standard",),
    caps: dict[str, str] | None = None,
    lifecycle: str = "GenerallyAvailable",
    deprecation: str | None = None,
    fmt: str = "OpenAI",
) -> dict[str, Any]:
    model: dict[str, Any] = {
        "format": fmt,
        "name": name,
        "version": version,
        "capabilities": caps if caps is not None else {"chatCompletion": "true"},
        "lifecycleStatus": lifecycle,
        "skus": [{"name": s, "capacity": {"default": 1}} for s in skus],
    }
    if deprecation:
        model["deprecation"] = {"inference": deprecation}
    return {"kind": "OpenAI", "skuName": "S0", "model": model}


def deployment(model: str = "gpt-4o", version: str = "2024-08-06", etag: str = "etag-1") -> dict:
    return {
        "id": "/subscriptions/x/deployments/dep1",
        "name": "dep1",
        "type": "Microsoft.CognitiveServices/accounts/deployments",
        "etag": etag,
        "sku": {"name": "Standard", "capacity": 3},
        "tags": {"team": "ai"},
        "properties": {
            "model": {"format": "OpenAI", "name": model, "version": version},
            "provisioningState": "Succeeded",
            "versionUpgradeOption": "NoAutoUpgrade",
            "raiPolicyName": "Microsoft.Default",
            "capabilities": {"chatCompletion": "true"},
        },
        "systemData": {"createdBy": "x"},
    }


DEFAULT_MODELS = [
    model_entry("gpt-4o", "2024-08-06"),
    model_entry("gpt-4.1", "2025-04-14", caps={"chatCompletion": "true", "agents": "true"}),
]
WRITE_PERMS = {"value": [{"actions": ["Microsoft.CognitiveServices/*"], "notActions": []}]}
READ_PERMS = {"value": [{"actions": ["Microsoft.CognitiveServices/*/read"], "notActions": []}]}


class FakeArm:
    """Scripted ARM. ``post_put_states`` are the provisioningStates returned by GETs after a PUT."""

    def __init__(
        self,
        state: dict[str, Any] | None = None,
        *,
        models: list[dict[str, Any]] | None = None,
        permissions: dict[str, Any] | None = None,
        put_state: str = "Accepted",
        post_put_states: list[str] | None = None,
    ) -> None:
        self.state = state or deployment()
        self.models = models if models is not None else DEFAULT_MODELS
        self.permissions = permissions if permissions is not None else WRITE_PERMS
        self.put_state = put_state
        self.post_put_states = list(post_put_states if post_put_states is not None else [])
        self.requests: list[httpx.Request] = []
        self.put_bodies: list[dict[str, Any]] = []
        self.on_get: Callable[[FakeArm], None] | None = None
        self._etag_n = 1
        self._putting = False

    @property
    def puts(self) -> list[httpx.Request]:
        return [r for r in self.requests if r.method == "PUT"]

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self._handle))

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path.endswith("/providers/Microsoft.Authorization/permissions"):
            return httpx.Response(200, json=self.permissions)
        if path.endswith("/models"):
            return httpx.Response(200, json={"value": self.models})
        if path.endswith("/deployments/dep1"):
            if request.method == "PUT":
                return self._put(request)
            if self.on_get:
                self.on_get(self)
            if self._putting and self.post_put_states:
                self.state["properties"]["provisioningState"] = self.post_put_states.pop(0)
            return httpx.Response(200, json=self.state)
        return httpx.Response(404, json={"error": {"code": "NotFound"}})

    def _put(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.put_bodies.append(copy.deepcopy(body))
        self._etag_n += 1
        self.state["etag"] = f"etag-{self._etag_n}"
        self.state["properties"]["model"] = body["properties"]["model"]
        self.state["properties"]["provisioningState"] = self.put_state
        self._putting = True
        return httpx.Response(200, json=self.state)


def request_for(
    *ops: tuple[str, str, str], etag: str = "etag-1", cloud: str = "commercial"
) -> WriteRequest:
    return WriteRequest(
        target=TargetRef(
            canonical_id=f"{cloud}:cust1:foundry:model_deployment:dep1",
            entity_type="model_deployment",
        ),
        target_version=etag,
        proposed_diff=ProposedDiff(
            format="json_patch",
            operations=[PatchOperation(op=op, path=path, value=value) for op, path, value in ops],  # type: ignore[arg-type]
        ),
    )


def swap_request(name: str = "gpt-4.1", version: str = "2025-04-14", etag: str = "etag-1"):
    return request_for(
        ("test", "/properties/model/name", "gpt-4o"),
        ("replace", "/properties/model/name", name),
        ("replace", "/properties/model/version", version),
        etag=etag,
    )


class Sleeper:
    """Injected sleep + clock: sleeping advances the clock, so polling never really waits."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds

    def clock(self) -> float:
        return self.now
