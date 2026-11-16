"""ARM provisioner for the deploy apply (PRP-55 item 3).

:class:`HttpArmProvisioner` creates only the allowlisted services of
``neurosphere_core.deploy.arm`` (decision 2) in the deployment cloud's management host
(``CloudProfile.management_url``; never another cloud's), into a resource group that must
already exist (decision 3: ``resource_group_missing``, no resource group is ever created).

``ensure_tagged``: GET the resource group (404 = ``resource_group_missing``), GET the resource
(present = ``created=False``: an existing resource is never claimed), else PUT the minimal body
with the ``neurosphere:created-by`` tag and poll the long-running operation
(``Azure-AsyncOperation`` / ``Location`` / ``provisioningState``) a bounded number of times
(``lro_timeout``). A poll URL must stay on the management host. ``exists`` is a read-only GET
used by ``verify``. No URL, subscription id or body is logged.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from typing import Final
from urllib.parse import urlsplit

from neurosphere_contracts.deployment.v1.deploy_action_plan import ResourceSpec
from neurosphere_core.cloud import CloudProfile
from neurosphere_core.deploy.arm import (
    CREATED_BY_TAG,
    RESOURCE_GROUP_API_VERSION,
    ArmServiceType,
    arm_service,
    resource_group_id,
)
from neurosphere_core.deploy.fabric import FabricHttp, FabricResponse
from neurosphere_core.deploy.register.models import CREATED_BY_NEUROSPHERE
from neurosphere_core.errors import (
    CapabilityUnavailableError,
    DependencyTransientError,
    ForbiddenError,
    InvalidSchemaError,
    UnauthorizedError,
)

from neurosphere_workers.actions.deploy import ProvisionedResource

__all__ = [
    "DEFAULT_MAX_POLLS",
    "RESOURCE_GROUP_MISSING",
    "HttpArmProvisioner",
]

DEFAULT_MAX_POLLS: Final = 30
DEFAULT_RETRY_AFTER_SECONDS: Final = 5
RESOURCE_GROUP_MISSING: Final = "resource_group_missing"
_RUNNING: Final = frozenset(
    {"notstarted", "running", "inprogress", "accepted", "creating", "updating", "provisioning"}
)
_FAILED: Final = frozenset({"failed", "canceled", "cancelled"})

Sleep = Callable[[float], Awaitable[None]]


class HttpArmProvisioner:
    """``ArmProvisioner`` over a bearer ``FabricHttp`` transport, allowlisted services only."""

    def __init__(
        self,
        http: FabricHttp,
        profile: CloudProfile,
        *,
        sleep: Sleep = asyncio.sleep,
        max_polls: int = DEFAULT_MAX_POLLS,
    ) -> None:
        if max_polls < 1:
            raise ValueError("max_polls must be positive")
        self._http = http
        self._profile = profile
        self._base = profile.management_url.rstrip("/")
        self._host = profile.management_host.lower()
        self._sleep = sleep
        self._max_polls = max_polls

    # -- allowlist ------------------------------------------------------------------------------

    def supports(self, spec: ResourceSpec) -> bool:
        return spec.kind == "arm_resource" and arm_service(spec.service) is not None

    def _entry(self, spec: ResourceSpec) -> ArmServiceType:
        entry = arm_service(spec.service) if spec.kind == "arm_resource" else None
        if entry is None:
            raise CapabilityUnavailableError(
                "capability_unavailable",
                f"the ARM provisioner does not create the {spec.service} service",
            )
        return entry

    def _resource_id(self, spec: ResourceSpec, entry: ArmServiceType) -> str:
        return entry.resource_id(spec.subscription_id or "", spec.resource_group or "", spec.name)

    def _url(self, path: str, api_version: str) -> str:
        return f"{self._base}{path}?api-version={api_version}"

    # -- ArmProvisioner ---------------------------------------------------------------------------

    async def ensure(self, spec: ResourceSpec) -> ProvisionedResource:
        return await self.ensure_tagged(spec, {CREATED_BY_TAG: CREATED_BY_NEUROSPHERE})

    async def ensure_tagged(
        self, spec: ResourceSpec, tags: Mapping[str, str]
    ) -> ProvisionedResource:
        """Create ``spec`` if absent; ``created=False`` when it already exists."""
        entry = self._entry(spec)
        if spec.disposition != "create":
            raise InvalidSchemaError(
                "only a create item is provisioned", reason="invalid_resource_spec"
            )
        resource_id = self._resource_id(spec, entry)
        group = resource_group_id(spec.subscription_id or "", spec.resource_group or "")
        found = await self._http.request("GET", self._url(group, RESOURCE_GROUP_API_VERSION), None)
        if found.status_code == 404:
            raise InvalidSchemaError(
                "the target resource group does not exist", reason=RESOURCE_GROUP_MISSING
            )
        _check(found, {200})
        url = self._url(resource_id, entry.api_version)
        existing = await self._http.request("GET", url, None)
        if existing.status_code != 404:
            _check(existing, {200})
            return ProvisionedResource(resource_id=resource_id, created=False)
        body = entry.create_body(spec.region, {**tags, CREATED_BY_TAG: CREATED_BY_NEUROSPHERE})
        created = await self._http.request("PUT", url, body)
        _check(created, {200, 201, 202})
        await self._settle(created, url)
        return ProvisionedResource(resource_id=resource_id, created=True)

    async def exists(self, spec: ResourceSpec) -> bool:
        """Read-only: the resource is there and not in a failed state."""
        entry = self._entry(spec)
        url = self._url(self._resource_id(spec, entry), entry.api_version)
        response = await self._http.request("GET", url, None)
        if response.status_code == 404:
            return False
        _check(response, {200})
        return _state(response) not in _FAILED

    # -- long-running operations --------------------------------------------------------------

    def _poll_url(self, raw: str) -> str:
        parts = urlsplit(raw)
        if parts.scheme != "https" or (parts.hostname or "").lower() != self._host:
            raise DependencyTransientError(
                "the operation URL is outside the management host",
                reason="lro_bad_location",
                upstream_invalid=True,
            )
        return raw

    async def _settle(self, response: FabricResponse, resource_url: str) -> None:
        operation = response.header("azure-asyncoperation")
        location = response.header("location")
        if operation:
            poll, kind = self._poll_url(operation), "operation"
        elif response.status_code == 202 and location:
            poll, kind = self._poll_url(location), "location"
        elif _state(response) in _RUNNING:
            poll, kind = resource_url, "resource"
        elif _state(response) in _FAILED:
            raise _lro_failed()
        else:
            return
        delay = _retry_after(response) or DEFAULT_RETRY_AFTER_SECONDS
        for _ in range(self._max_polls):
            await self._sleep(delay)
            current = await self._http.request("GET", poll, None)
            _check(current, {200, 201, 202})
            state = _state(current)
            if state in _FAILED:
                raise _lro_failed()
            if kind == "operation":
                if state == "succeeded":
                    return
            elif kind == "location":
                if current.status_code != 202:
                    return
            elif state not in _RUNNING:
                return
            delay = _retry_after(current) or delay
        raise DependencyTransientError(
            f"the ARM operation did not finish after {self._max_polls} polls",
            reason="lro_timeout",
            retry_after_seconds=delay,
        )


def _lro_failed() -> DependencyTransientError:
    return DependencyTransientError(
        "the ARM operation failed", reason="lro_failed", upstream_invalid=True
    )


def _check(response: FabricResponse, ok: set[int]) -> None:
    code = response.status_code
    if code in ok:
        return
    retry = _retry_after(response)
    if code == 429:
        raise DependencyTransientError(
            "ARM throttled the request", reason="throttled", retry_after_seconds=retry
        )
    if code >= 500:
        raise DependencyTransientError(
            f"ARM error {code}", reason="upstream_error", retry_after_seconds=retry
        )
    if code == 401:
        raise UnauthorizedError("ARM rejected the token")
    if code == 403:
        raise ForbiddenError("ARM denied the operation")
    raise DependencyTransientError(
        f"unexpected ARM status {code}", reason="unexpected_status", upstream_invalid=True
    )


def _retry_after(response: FabricResponse) -> int | None:
    raw = response.header("retry-after")
    if raw is not None and raw.isdigit():
        return int(raw)
    return None


def _state(response: FabricResponse) -> str:
    body = response.body or {}
    props = body.get("properties")
    nested = props.get("provisioningState") if isinstance(props, Mapping) else None
    raw = body.get("status") or nested or ""
    return str(raw).lower()
