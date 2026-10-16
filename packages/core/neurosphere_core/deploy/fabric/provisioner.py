"""Fabric capacity and workspace lifecycle, gated by the capability matrix.

* Capacity is an ARM resource (management host from the cloud profile).
* Workspace create/assign/delete go ONLY through Fabric REST; a workspace is not an ARM resource.
* Every public method evaluates the capability matrix first; when Fabric is not ``supported``
  for the cloud/region it raises ``CapabilityUnavailableError`` and performs zero HTTP calls.
* Long-running operations (202 + ``Location``) are polled a bounded number of times with an
  injectable sleep. Poll URLs must stay on this endpoint set's hosts.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable, Mapping
from typing import Any
from urllib.parse import quote, urlsplit

from pydantic import BaseModel, ConfigDict, ValidationError

from neurosphere_core.capabilities.loader import CapabilityMatrix
from neurosphere_core.capabilities.validate import DeploymentProfile, validate_profile
from neurosphere_core.deploy.fabric.endpoints import FabricEndpoints
from neurosphere_core.deploy.fabric.transport import FabricHttp, FabricResponse
from neurosphere_core.errors import (
    CapabilityUnavailableError,
    DependencyTransientError,
    ForbiddenError,
    InvalidSchemaError,
    UnauthorizedError,
)

ARM_API_VERSION = "2023-11-01"
DEFAULT_MAX_POLLS = 10
DEFAULT_RETRY_AFTER_SECONDS = 2

_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_CAPACITY_RE = re.compile(r"^[a-z][a-z0-9]{2,62}$")
_RG_RE = re.compile(r"^[\w.()-]{1,90}$")
_RUNNING = {"notstarted", "running", "inprogress", "accepted", "creating", "updating"}
_FAILED = {"failed", "canceled", "cancelled"}

Sleep = Callable[[float], Awaitable[None]]


class CapacityRef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    arm_id: str
    created: bool


class WorkspaceRef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    display_name: str
    capacity_id: str | None = None
    created: bool


class FabricProvisioner:
    def __init__(
        self,
        http: FabricHttp,
        endpoints: FabricEndpoints,
        *,
        matrix: CapabilityMatrix | None = None,
        sleep: Sleep = asyncio.sleep,
        max_polls: int = DEFAULT_MAX_POLLS,
    ) -> None:
        self._http = http
        self._ep = endpoints
        self._matrix = matrix
        self._sleep = sleep
        self._max_polls = max_polls

    # ------------------------------------------------------------------ gate
    def _require_fabric(self, region: str) -> None:
        """Raise ``CapabilityUnavailableError`` unless the matrix supports Fabric here."""
        try:
            profile = DeploymentProfile(
                cloud=self._ep.cloud.value,  # type: ignore[arg-type]
                regions=(region,),
                hosting="aks",
                analytics="fabric",
            )
        except ValidationError as exc:
            raise InvalidSchemaError(
                f"region {region!r} is not valid for {self._ep.cloud.value}",
                reason="invalid_region",
            ) from exc
        result = validate_profile(profile, matrix=self._matrix)
        for item in result.results:
            if item.kind == "analytics" and item.status != "supported":
                raise CapabilityUnavailableError(
                    item.reason_code or "not_verified", detail=item.reason
                )

    # ------------------------------------------------------------- plumbing
    def _fabric_url(self, path: str) -> str:
        return f"{self._ep.fabric_api_base.rstrip('/')}/v1/{path.lstrip('/')}"

    def _check_status(self, resp: FabricResponse, ok: set[int]) -> None:
        code = resp.status_code
        if code in ok:
            return
        retry = _retry_after(resp)
        if code == 429:
            raise DependencyTransientError(
                "Fabric/ARM throttled the request", reason="throttled", retry_after_seconds=retry
            )
        if code >= 500:
            raise DependencyTransientError(
                f"upstream error {code}", reason="upstream_error", retry_after_seconds=retry
            )
        if code == 401:
            raise UnauthorizedError("Fabric/ARM rejected the token")
        if code == 403:
            raise ForbiddenError("Fabric/ARM denied the operation")
        raise DependencyTransientError(
            f"unexpected upstream status {code}", reason="unexpected_status", upstream_invalid=True
        )

    async def _send(
        self, method: str, url: str, ok: set[int], body: Mapping[str, Any] | None = None
    ) -> FabricResponse:
        resp = await self._http.request(method, url, body)
        self._check_status(resp, ok | {202} if method != "GET" else ok)
        if resp.status_code == 202:
            return await self._poll(resp)
        return resp

    async def _poll(self, accepted: FabricResponse) -> FabricResponse:
        location = accepted.header("location") or accepted.header("azure-asyncoperation")
        if not location:
            raise DependencyTransientError(
                "202 without Location", reason="lro_no_location", upstream_invalid=True
            )
        host = (urlsplit(location).hostname or "").lower()
        if urlsplit(location).scheme != "https" or host not in self._ep.allowed_hosts:
            raise DependencyTransientError(
                "LRO Location is outside the endpoint set",
                reason="lro_bad_location",
                upstream_invalid=True,
            )
        delay = _retry_after(accepted) or DEFAULT_RETRY_AFTER_SECONDS
        for _ in range(self._max_polls):
            await self._sleep(delay)
            resp = await self._http.request("GET", location, None)
            self._check_status(resp, {200, 201, 202})
            state = _state(resp)
            if state in _FAILED:
                raise DependencyTransientError(
                    "long-running operation failed", reason="lro_failed", upstream_invalid=True
                )
            if resp.status_code != 202 and state not in _RUNNING:
                return resp
            delay = _retry_after(resp) or delay
        raise DependencyTransientError(
            f"long-running operation not finished after {self._max_polls} polls",
            reason="lro_timeout",
            retry_after_seconds=delay,
        )

    # ------------------------------------------------------------- capacity
    async def ensure_capacity(
        self,
        *,
        subscription_id: str,
        resource_group: str,
        name: str,
        region: str,
        sku: str,
        admin_members: tuple[str, ...],
    ) -> CapacityRef:
        """Create the ARM capacity if absent (GET first, then PUT)."""
        self._require_fabric(region)
        if not _UUID_RE.match(subscription_id):
            raise InvalidSchemaError("invalid subscription id", reason="invalid_subscription")
        if not _RG_RE.match(resource_group) or not _CAPACITY_RE.match(name):
            raise InvalidSchemaError(
                "invalid resource group or capacity name", reason="invalid_name"
            )
        arm_id = (
            f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}"
            f"/providers/Microsoft.Fabric/capacities/{name}"
        )
        url = f"{self._ep.management_url.rstrip('/')}{arm_id}?api-version={ARM_API_VERSION}"
        existing = await self._http.request("GET", url, None)
        if existing.status_code != 404:
            self._check_status(existing, {200})
            return CapacityRef(name=name, arm_id=arm_id, created=False)
        body = {
            "location": region,
            "sku": {"name": sku, "tier": "Fabric"},
            "properties": {"administration": {"members": list(admin_members)}},
        }
        await self._send("PUT", url, {200, 201}, body)
        return CapacityRef(name=name, arm_id=arm_id, created=True)

    # ------------------------------------------------------------ workspace
    async def _find_workspace(self, display_name: str) -> Mapping[str, Any] | None:
        url: str | None = self._fabric_url("workspaces")
        for _ in range(self._max_polls):
            resp = await self._send("GET", url, {200})
            body = resp.body or {}
            for item in body.get("value", []):
                if item.get("displayName") == display_name:
                    return item
            url = body.get("continuationUri")
            if not url or (urlsplit(url).hostname or "").lower() not in self._ep.allowed_hosts:
                return None
        return None

    async def ensure_workspace(
        self, *, display_name: str, region: str, capacity_id: str | None = None
    ) -> WorkspaceRef:
        """Return the workspace named ``display_name``, creating it only if none exists."""
        self._require_fabric(region)
        if not display_name.strip() or len(display_name) > 256:
            raise InvalidSchemaError("invalid workspace display name", reason="invalid_name")
        found = await self._find_workspace(display_name)
        if found is not None:
            return WorkspaceRef(
                id=_checked_id(found.get("id")),
                display_name=display_name,
                capacity_id=found.get("capacityId"),
                created=False,
            )
        payload: dict[str, Any] = {"displayName": display_name}
        if capacity_id:
            payload["capacityId"] = _checked_id(capacity_id)
        resp = await self._send("POST", self._fabric_url("workspaces"), {201}, payload)
        ws_id = (resp.body or {}).get("id")
        if ws_id is None:  # LRO result carries no body: look it up by name
            again = await self._find_workspace(display_name)
            ws_id = again.get("id") if again else None
        return WorkspaceRef(
            id=_checked_id(ws_id), display_name=display_name, capacity_id=capacity_id, created=True
        )

    async def assign_workspace_to_capacity(
        self, *, workspace_id: str, capacity_id: str, region: str
    ) -> None:
        self._require_fabric(region)
        url = self._fabric_url(
            f"workspaces/{quote(_checked_id(workspace_id), safe='')}/assignToCapacity"
        )
        await self._send("POST", url, {200}, {"capacityId": _checked_id(capacity_id)})

    async def delete_workspace(
        self, *, workspace_id: str, region: str, created_by_neurosphere: bool
    ) -> None:
        """Delete a workspace; refuses anything the ownership register did not record."""
        self._require_fabric(region)
        if not created_by_neurosphere:
            raise ForbiddenError(
                "refusing to delete a workspace NeuroSphere did not create",
                reason="not_owned",
            )
        url = self._fabric_url(f"workspaces/{quote(_checked_id(workspace_id), safe='')}")
        resp = await self._http.request("DELETE", url, None)
        if resp.status_code == 404:
            return
        self._check_status(resp, {200, 202})


def _checked_id(value: object) -> str:
    if not isinstance(value, str) or not _UUID_RE.match(value):
        raise InvalidSchemaError("expected a GUID identifier", reason="invalid_id")
    return value


def _retry_after(resp: FabricResponse) -> int | None:
    raw = resp.header("retry-after")
    if raw is not None and raw.isdigit():
        return int(raw)
    return None


def _state(resp: FabricResponse) -> str:
    body = resp.body or {}
    raw = body.get("status") or (body.get("properties") or {}).get("provisioningState") or ""
    return str(raw).lower()
