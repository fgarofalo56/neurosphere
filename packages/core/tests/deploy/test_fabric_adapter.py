# ruff: noqa: S105, S106
"""Fabric adapter: matrix gate, endpoint isolation, idempotency, LRO, throttling, ownership."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

import pytest
from neurosphere_core.capabilities.loader import CapabilityMatrix
from neurosphere_core.capabilities.validate import default_matrix
from neurosphere_core.cloud import CloudName
from neurosphere_core.deploy import fabric as fabric_pkg
from neurosphere_core.deploy.fabric import (
    FabricEndpoints,
    FabricProvisioner,
    FabricResponse,
    RecordingFabricHttp,
    fabric_endpoints_for,
)
from neurosphere_core.errors import (
    CapabilityUnavailableError,
    DependencyTransientError,
    ForbiddenError,
    InvalidSchemaError,
)
from pydantic import ValidationError

WS = "11111111-1111-1111-1111-111111111111"
CAP = "22222222-2222-2222-2222-222222222222"
SUB = "33333333-3333-3333-3333-333333333333"
GOV_SCOPE = "https://configured.example.us/.default"


async def _no_sleep(_: float) -> None:
    SLEPT.append(_)


SLEPT: list[float] = []


@pytest.fixture(autouse=True)
def _reset_sleep() -> None:
    SLEPT.clear()


def _matrix_commercial_available() -> CapabilityMatrix:
    rows = tuple(
        r.model_copy(update={"availability": "available", "ga_status": "ga"})
        if (r.service, r.feature, r.cloud) == ("fabric", "base", "commercial")
        else r
        for r in default_matrix().rows
    )
    return CapabilityMatrix(rows=rows)


def _gov() -> FabricEndpoints:
    return fabric_endpoints_for(CloudName.GOVERNMENT, token_scope=GOV_SCOPE)


def _prov(http: RecordingFabricHttp, gov: bool = True, matrix: CapabilityMatrix | None = None):
    ep = _gov() if gov else fabric_endpoints_for(CloudName.COMMERCIAL)
    return FabricProvisioner(http, ep, matrix=matrix, sleep=_no_sleep, max_polls=3)


def _ok(body=None, status=200, **headers):
    return FabricResponse(status, body, headers)


# 1 -------------------------------------------------------------------------
async def test_unavailable_commercial_shipped_matrix_no_calls() -> None:
    http = RecordingFabricHttp()
    with pytest.raises(CapabilityUnavailableError) as ei:
        await _prov(http, gov=False).ensure_workspace(display_name="w", region="swedensouth")
    assert "fabric.base.commercial.global.any" in (ei.value.detail or "")
    assert http.calls == []


async def test_unavailable_gov_region_shipped_matrix_no_calls() -> None:
    http = RecordingFabricHttp()
    p = _prov(http)
    with pytest.raises(CapabilityUnavailableError) as ei:
        await p.ensure_workspace(display_name="w", region="usgovarizona")
    assert ei.value.reason == "not_verified"
    assert http.calls == []
    with pytest.raises(CapabilityUnavailableError):
        await p.ensure_capacity(
            subscription_id=SUB,
            resource_group="rg",
            name="cap1",
            region="usgovarizona",
            sku="F2",
            admin_members=("a@b.us",),
        )
    with pytest.raises(CapabilityUnavailableError):
        await p.assign_workspace_to_capacity(
            workspace_id=WS, capacity_id=CAP, region="usgovarizona"
        )
    with pytest.raises(CapabilityUnavailableError):
        await p.delete_workspace(
            workspace_id=WS, region="usgovarizona", created_by_neurosphere=True
        )
    assert http.calls == []


async def test_hand_built_unavailable_matrix_carries_reason() -> None:
    rows = tuple(
        r.model_copy(update={"availability": "unavailable"})
        if (r.service, r.feature, r.region) == ("fabric", "base", "usgovvirginia")
        else r
        for r in default_matrix().rows
    )
    http = RecordingFabricHttp()
    with pytest.raises(CapabilityUnavailableError) as ei:
        await _prov(http, matrix=CapabilityMatrix(rows=rows)).ensure_workspace(
            display_name="w", region="usgovvirginia"
        )
    assert ei.value.reason == "not_available_in_region"
    assert http.calls == []


async def test_wrong_cloud_region_is_invalid_not_a_call() -> None:
    http = RecordingFabricHttp()
    with pytest.raises(InvalidSchemaError):
        await _prov(http).ensure_workspace(display_name="w", region="eastus")
    assert http.calls == []


# 2 -------------------------------------------------------------------------
def test_no_arm_workspace_path_in_module() -> None:
    forbidden = "Microsoft.Fabric/" + "workspaces"
    for path in Path(fabric_pkg.__file__).parent.glob("*.py"):
        assert forbidden.lower() not in path.read_text(encoding="utf-8").lower()


async def test_workspace_create_uses_fabric_host() -> None:
    http = RecordingFabricHttp([_ok({"value": []}), _ok({"id": WS}, 201)])
    ref = await _prov(http).ensure_workspace(display_name="ns", region="usgovvirginia")
    assert ref.created and ref.id == WS
    assert [c.method for c in http.calls] == ["GET", "POST"]
    assert http.calls[1].url == "https://highapi.fabric.microsoft.us/v1/workspaces"
    assert http.calls[1].json == {"displayName": "ns"}


# 3 -------------------------------------------------------------------------
async def test_government_hosts_only() -> None:
    http = RecordingFabricHttp(
        [
            _ok({"value": []}),
            _ok({"id": WS}, 201),
            _ok(status=200),
            _ok(status=404),  # capacity GET
            _ok({}, 201),  # capacity PUT
            _ok(status=200),  # delete
        ]
    )
    p = _prov(http)
    await p.ensure_workspace(display_name="ns", region="usgovtexas")
    await p.assign_workspace_to_capacity(workspace_id=WS, capacity_id=CAP, region="usgovtexas")
    cap = await p.ensure_capacity(
        subscription_id=SUB,
        resource_group="rg",
        name="cap1",
        region="usgovtexas",
        sku="F2",
        admin_members=("a@b.us",),
    )
    assert cap.created
    await p.delete_workspace(workspace_id=WS, region="usgovtexas", created_by_neurosphere=True)
    assert len(http.calls) == 6
    for call in http.calls:
        host = urlsplit(call.url).hostname or ""
        assert host.endswith((".us", "usgovcloudapi.net")), call.url
        assert "microsoft.com" not in host and "azure.com" not in host


def test_government_endpoints_reject_commercial_hosts() -> None:
    with pytest.raises(ValidationError):
        FabricEndpoints(
            cloud=CloudName.GOVERNMENT,
            fabric_api_base="https://api.fabric.microsoft.com",
            token_scope=GOV_SCOPE,
            management_url="https://management.usgovcloudapi.net/",
        )
    with pytest.raises(ValidationError):
        FabricEndpoints(
            cloud=CloudName.GOVERNMENT,
            fabric_api_base="https://highapi.fabric.microsoft.us",
            token_scope="https://api.fabric.microsoft.com/.default",
            management_url="https://management.usgovcloudapi.net/",
        )
    with pytest.raises(ValidationError):
        FabricEndpoints(
            cloud=CloudName.GOVERNMENT,
            fabric_api_base="https://highapi.fabric.microsoft.us",
            token_scope=GOV_SCOPE,
            management_url="https://management.azure.com/",
        )


def test_government_scope_must_be_configured() -> None:
    with pytest.raises(InvalidSchemaError):
        fabric_endpoints_for(CloudName.GOVERNMENT)
    with pytest.raises(InvalidSchemaError):
        fabric_endpoints_for(
            CloudName.GOVERNMENT, token_scope="https://api.fabric.microsoft.com/.default"
        )


def test_commercial_endpoints() -> None:
    ep = fabric_endpoints_for(CloudName.COMMERCIAL)
    assert ep.fabric_api_base == "https://api.fabric.microsoft.com"
    assert ep.token_scope == "https://api.fabric.microsoft.com/.default"
    with pytest.raises(ValidationError):
        FabricEndpoints(
            cloud=CloudName.COMMERCIAL,
            fabric_api_base="https://highapi.fabric.microsoft.us",
            token_scope=ep.token_scope,
            management_url=ep.management_url,
        )


async def test_commercial_flow_with_available_matrix() -> None:
    http = RecordingFabricHttp([_ok({"value": []}), _ok({"id": WS}, 201)])
    p = _prov(http, gov=False, matrix=_matrix_commercial_available())
    await p.ensure_workspace(display_name="ns", region="eastus")
    assert http.calls[1].url == "https://api.fabric.microsoft.com/v1/workspaces"


# 4 -------------------------------------------------------------------------
async def test_ensure_workspace_idempotent() -> None:
    http = RecordingFabricHttp(
        [_ok({"value": [{"id": WS, "displayName": "ns", "capacityId": CAP}]})]
    )
    ref = await _prov(http).ensure_workspace(display_name="ns", region="usgovvirginia")
    assert not ref.created and ref.id == WS and ref.capacity_id == CAP
    assert [c.method for c in http.calls] == ["GET"]


async def test_lro_polling_with_injected_sleep() -> None:
    loc = "https://highapi.fabric.microsoft.us/v1/operations/op1"
    http = RecordingFabricHttp(
        [
            _ok({"value": []}),
            FabricResponse(202, None, {"Location": loc, "Retry-After": "5"}),
            _ok({"status": "Running"}, 200),
            _ok({"status": "Succeeded"}, 200),
            _ok({"value": [{"id": WS, "displayName": "ns"}]}),
        ]
    )
    ref = await _prov(http).ensure_workspace(display_name="ns", region="usgovvirginia")
    assert ref.created and ref.id == WS
    assert SLEPT == [5, 5]
    assert [c.url for c in http.calls[2:4]] == [loc, loc]


async def test_lro_poll_bound() -> None:
    loc = "https://highapi.fabric.microsoft.us/v1/operations/op1"
    running = _ok({"status": "Running"}, 200)
    http = RecordingFabricHttp(
        [
            _ok({"value": []}),
            FabricResponse(202, None, {"location": loc}),
            running,
            running,
            running,
        ]
    )
    with pytest.raises(DependencyTransientError) as ei:
        await _prov(http).ensure_workspace(display_name="ns", region="usgovvirginia")
    assert ei.value.reason == "lro_timeout"
    assert len(SLEPT) == 3


async def test_lro_location_off_host_rejected() -> None:
    http = RecordingFabricHttp(
        [
            _ok({"value": []}),
            FabricResponse(202, None, {"Location": "https://api.fabric.microsoft.com/v1/o"}),
        ]
    )
    with pytest.raises(DependencyTransientError):
        await _prov(http).ensure_workspace(display_name="ns", region="usgovvirginia")
    assert len(http.calls) == 2


async def test_throttle_429_is_transient() -> None:
    http = RecordingFabricHttp([FabricResponse(429, None, {"Retry-After": "7"})])
    with pytest.raises(DependencyTransientError) as ei:
        await _prov(http).ensure_workspace(display_name="ns", region="usgovvirginia")
    assert ei.value.retry_after_seconds == 7


async def test_ensure_capacity_existing_does_not_put() -> None:
    http = RecordingFabricHttp([_ok({"name": "cap1"})])
    cap = await _prov(http).ensure_capacity(
        subscription_id=SUB,
        resource_group="rg",
        name="cap1",
        region="usgovvirginia",
        sku="F2",
        admin_members=("a@b.us",),
    )
    assert not cap.created
    assert [c.method for c in http.calls] == ["GET"]
    assert urlsplit(http.calls[0].url).hostname == "management.usgovcloudapi.net"


# 5 -------------------------------------------------------------------------
async def test_delete_refuses_when_not_owned() -> None:
    http = RecordingFabricHttp()
    with pytest.raises(ForbiddenError):
        await _prov(http).delete_workspace(
            workspace_id=WS, region="usgovvirginia", created_by_neurosphere=False
        )
    assert http.calls == []


async def test_delete_owned_calls_delete() -> None:
    http = RecordingFabricHttp([_ok(status=200)])
    await _prov(http).delete_workspace(
        workspace_id=WS, region="usgovvirginia", created_by_neurosphere=True
    )
    assert http.calls[0].method == "DELETE"
    assert http.calls[0].url.endswith(f"/v1/workspaces/{WS}")


async def test_bad_workspace_id_rejected() -> None:
    http = RecordingFabricHttp()
    with pytest.raises(InvalidSchemaError):
        await _prov(http).delete_workspace(
            workspace_id="../x", region="usgovvirginia", created_by_neurosphere=True
        )
    assert http.calls == []
