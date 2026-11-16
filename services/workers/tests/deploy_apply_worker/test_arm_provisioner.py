"""``HttpArmProvisioner`` (PRP-55 item 3, criterion 4) over a fake ARM (``httpx.MockTransport``).

Allowlisted services only, the created-by tag, ``created=False`` for an existing resource, a
bounded long-running-operation poll, ``resource_group_missing`` and the deployment cloud's
management host. No network.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from neurosphere_contracts.deployment.v1.deploy_action_plan import ResourceSpec
from neurosphere_core.cloud import CloudName, profile_for
from neurosphere_core.deploy.arm import CREATED_BY_TAG, DEPLOYMENT_TAG, arm_resource_name
from neurosphere_core.errors import (
    CapabilityUnavailableError,
    DependencyTransientError,
    ForbiddenError,
    InvalidSchemaError,
)
from neurosphere_workers.actions.deploy_arm import RESOURCE_GROUP_MISSING, HttpArmProvisioner
from neurosphere_workers.actions.deploy_http import BearerDeployHttp, deploy_scopes

from .fake_arm import RG, SUB, FakeArm, FakeCredential, no_sleep

DEPLOYMENT = "demo-eastus2"


def _spec(service: str = "storage", **extra: Any) -> ResourceSpec:
    base: dict[str, Any] = {
        "service": service,
        "kind": "arm_resource",
        "disposition": "create",
        "name": arm_resource_name(service, DEPLOYMENT),
        "region": "eastus2",
        "sku": None,
        "resource_id": None,
        "subscription_id": SUB,
        "resource_group": RG,
        "consent_reference": None,
    }
    base.update(extra)
    return ResourceSpec.model_validate(base)


def _provisioner(
    arm: FakeArm, *, max_polls: int = 5, cloud: CloudName = CloudName.COMMERCIAL
) -> tuple[HttpArmProvisioner, FakeCredential]:
    credential = FakeCredential()
    profile = profile_for(cloud)
    http = BearerDeployHttp(arm.client(), lambda: credential, deploy_scopes(profile))  # type: ignore[arg-type, return-value]
    return HttpArmProvisioner(http, profile, sleep=no_sleep, max_polls=max_polls), credential


@pytest.mark.parametrize("service", ["storage", "event_hubs", "monitoring"])
async def test_allowlisted_service_is_created_tagged_and_read_back(service: str) -> None:
    arm = FakeArm()
    provisioner, credential = _provisioner(arm)
    spec = _spec(service)
    result = await provisioner.ensure_tagged(spec, {DEPLOYMENT_TAG: DEPLOYMENT})
    assert result.created is True
    assert result.resource_id.endswith("/" + spec.name)
    assert result.resource_id.startswith(f"/subscriptions/{SUB}/resourceGroups/{RG}/providers/")
    (payload,) = arm.payloads
    assert payload["tags"][CREATED_BY_TAG] == "neurosphere"
    assert payload["tags"][DEPLOYMENT_TAG] == DEPLOYMENT
    assert payload["location"] == "eastus2"
    assert await provisioner.exists(spec) is True
    assert set(credential.scopes) == {"https://management.azure.com/.default"}
    assert set(arm.hosts) == {"management.azure.com"}


async def test_plain_ensure_still_stamps_the_created_by_tag() -> None:
    arm = FakeArm()
    provisioner, _ = _provisioner(arm)
    assert (await provisioner.ensure(_spec())).created is True
    assert arm.payloads[0]["tags"] == {CREATED_BY_TAG: "neurosphere"}


async def test_an_existing_resource_is_reported_not_created_and_not_written() -> None:
    arm = FakeArm()
    provisioner, _ = _provisioner(arm)
    await provisioner.ensure(_spec())
    arm.payloads.clear()
    again = await provisioner.ensure(_spec())
    assert again.created is False
    assert arm.payloads == []


async def test_missing_resource_group_is_refused_before_any_write() -> None:
    arm = FakeArm(groups=set())
    provisioner, _ = _provisioner(arm)
    with pytest.raises(InvalidSchemaError) as raised:
        await provisioner.ensure(_spec())
    assert raised.value.reason == RESOURCE_GROUP_MISSING
    assert [m for m, _ in arm.calls] == ["GET"]


async def test_the_long_running_operation_poll_is_bounded() -> None:
    arm = FakeArm(lro_polls=10)
    provisioner, _ = _provisioner(arm, max_polls=3)
    with pytest.raises(DependencyTransientError) as raised:
        await provisioner.ensure(_spec())
    assert raised.value.reason == "lro_timeout"
    polls = [p for m, p in arm.calls if m == "GET" and p.startswith("/operations/")]
    assert len(polls) == 3


async def test_the_poll_waits_for_success() -> None:
    arm = FakeArm(lro_polls=2)
    provisioner, _ = _provisioner(arm, max_polls=5)
    assert (await provisioner.ensure(_spec())).created is True
    polls = [p for m, p in arm.calls if m == "GET" and p.startswith("/operations/")]
    assert len(polls) == 3


@pytest.mark.parametrize(
    "service", ["key_vault", "cosmos_db", "ai_search", "container_registry", "api_management"]
)
async def test_any_other_service_is_capability_unavailable_with_zero_calls(service: str) -> None:
    arm = FakeArm()
    provisioner, _ = _provisioner(arm)
    spec = _spec(service, name=f"{service.replace('_', '')}demo")
    assert provisioner.supports(spec) is False
    with pytest.raises(CapabilityUnavailableError) as raised:
        await provisioner.ensure(spec)
    assert raised.value.reason == "capability_unavailable"
    assert arm.calls == []


async def test_government_uses_the_government_management_host_only() -> None:
    arm = FakeArm(cloud=CloudName.GOVERNMENT)
    provisioner, credential = _provisioner(arm, cloud=CloudName.GOVERNMENT)
    assert (await provisioner.ensure(_spec(region="usgovvirginia"))).created is True
    assert set(arm.hosts) == {"management.usgovcloudapi.net"}
    assert set(credential.scopes) == {"https://management.usgovcloudapi.net/.default"}


async def test_an_operation_url_on_another_host_is_refused() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "PUT":
            return httpx.Response(
                201,
                json={},
                headers={"Azure-AsyncOperation": "https://evil.example.com/operations/1"},
            )
        if "/providers/" in request.url.path:
            return httpx.Response(404, json={})
        return httpx.Response(200, json={})

    profile = profile_for(CloudName.COMMERCIAL)
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    http = BearerDeployHttp(client, FakeCredential, deploy_scopes(profile))  # type: ignore[arg-type]
    provisioner = HttpArmProvisioner(http, profile, sleep=no_sleep)
    with pytest.raises(DependencyTransientError) as raised:
        await provisioner.ensure(_spec())
    assert raised.value.reason == "lro_bad_location"


async def test_a_failed_operation_is_lro_failed_and_403_is_forbidden() -> None:
    def failing(request: httpx.Request) -> httpx.Response:
        if request.method == "PUT":
            return httpx.Response(200, json={"properties": {"provisioningState": "Failed"}})
        if "/providers/" in request.url.path:
            return httpx.Response(404, json={})
        return httpx.Response(200, json={})

    profile = profile_for(CloudName.COMMERCIAL)
    http = BearerDeployHttp(
        httpx.AsyncClient(transport=httpx.MockTransport(failing)),
        FakeCredential,  # type: ignore[arg-type]
        deploy_scopes(profile),
    )
    with pytest.raises(DependencyTransientError) as raised:
        await HttpArmProvisioner(http, profile, sleep=no_sleep).ensure(_spec())
    assert raised.value.reason == "lro_failed"

    denied = BearerDeployHttp(
        httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(403))),
        FakeCredential,  # type: ignore[arg-type]
        deploy_scopes(profile),
    )
    with pytest.raises(ForbiddenError):
        await HttpArmProvisioner(denied, profile, sleep=no_sleep).ensure(_spec())


async def test_exists_is_false_for_a_missing_or_failed_resource() -> None:
    arm = FakeArm()
    provisioner, _ = _provisioner(arm)
    assert await provisioner.exists(_spec()) is False
    await provisioner.ensure(_spec())
    key = next(iter(arm.resources))
    arm.resources[key]["properties"] = {"provisioningState": "Failed"}
    assert await provisioner.exists(_spec()) is False
    assert [m for m, _ in arm.calls].count("PUT") == 1  # exists never writes
