"""``HttpApimArm`` over a scripted ARM (httpx.MockTransport; no network)."""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest
from apim_write_support import ARM_ID  # pyright: ignore[reportMissingImports]
from neurosphere_connector_apim_gateway import ApimArm, HttpApimArm
from neurosphere_core.cloud.profile import CloudName, profile_for
from neurosphere_core.errors import (
    CapabilityUnavailableError,
    DependencyTransientError,
    ForbiddenError,
    InvalidSchemaError,
    StaleVersionError,
)

Handler = Callable[[httpx.Request], httpx.Response]


class Recorder:
    def __init__(self, handler: Handler) -> None:
        self.handler = handler
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.handler(request)


class Sleeper:
    def __init__(self) -> None:
        self.waits: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.waits.append(seconds)


def _arm(
    handler: Handler, *, base: str = "https://management.azure.com", **kw: object
) -> tuple[HttpApimArm, Recorder, Sleeper]:
    rec = Recorder(handler)
    sleeper = Sleeper()
    client = httpx.AsyncClient(base_url=base, transport=httpx.MockTransport(rec))
    arm = HttpApimArm(client, ARM_ID, sleep=sleeper, **kw)  # type: ignore[arg-type]
    return arm, rec, sleeper


def test_satisfies_protocol() -> None:
    arm, _, _ = _arm(lambda r: httpx.Response(200, json={}))
    assert isinstance(arm, ApimArm)


async def test_get_uses_api_version_rawxml_and_etag_header() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"properties": {"format": "rawxml", "value": "<fragment />"}},
            headers={"ETag": '"e1"'},
        )

    arm, rec, _ = _arm(handler)
    res = await arm.get("policyFragments/f1")
    assert res is not None and res.etag == '"e1"'
    url = rec.requests[0].url
    assert url.path == f"{ARM_ID}/policyFragments/f1"
    assert url.params["api-version"] == "2024-05-01"
    assert url.params["format"] == "rawxml"
    await arm.get("backends/b1")
    assert "format" not in rec.requests[1].url.params


async def test_get_404_is_none_and_service_path_is_allowed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == ARM_ID:
            return httpx.Response(200, json={"etag": '"svc"', "properties": {}})
        return httpx.Response(404)

    arm, _, _ = _arm(handler)
    assert await arm.get("apis/missing") is None
    service = await arm.get("")
    assert service is not None and service.etag == '"svc"'


async def test_put_sends_if_match_and_412_is_stale_version() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(412 if request.headers.get("If-Match") == '"old"' else 200, json={})

    arm, rec, _ = _arm(handler)
    await arm.put("backends/b1", {"url": "https://x"}, if_match='"e1"')
    sent = rec.requests[0]
    assert sent.method == "PUT"
    assert sent.headers["If-Match"] == '"e1"'
    assert json.loads(sent.content) == {"properties": {"url": "https://x"}}
    await arm.put("backends/b2", {"url": "https://x"}, if_match=None)
    assert "If-Match" not in rec.requests[1].headers
    with pytest.raises(StaleVersionError) as err:
        await arm.put("backends/b1", {"url": "https://y"}, if_match='"old"')
    assert err.value.reason == "etag_mismatch"


async def test_429_honours_retry_after_then_maps_to_dependency_transient() -> None:
    attempts = {"n": 0}

    def flaky(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] <= 2:
            return httpx.Response(429, headers={"Retry-After": "7"})
        return httpx.Response(200, json={})

    arm, _, sleeper = _arm(flaky)
    await arm.put("apis/a1", {"path": "a"}, if_match=None)
    assert sleeper.waits == [7.0, 7.0]

    arm2, rec2, sleeper2 = _arm(lambda r: httpx.Response(429, headers={"Retry-After": "12"}))
    with pytest.raises(DependencyTransientError) as err:
        await arm2.get("apis/a1")
    assert err.value.reason == "arm_rate_limited"
    assert err.value.retry_after_seconds == 12
    assert len(rec2.requests) == 4 and len(sleeper2.waits) == 3


async def test_secret_listing_paths_are_refused_before_any_request() -> None:
    arm, rec, _ = _arm(lambda r: httpx.Response(200, json={}))
    for path in (
        "subscriptions/s1/listSecrets",
        "namedValues/n1/listValue",
        "subscriptions/s1/regeneratePrimaryKey",
    ):
        with pytest.raises(InvalidSchemaError) as err:
            await arm.get(path)
        assert err.value.reason == "forbidden_path"
    with pytest.raises(InvalidSchemaError):
        await arm.put("../../Microsoft.Storage/x", {}, if_match=None)
    assert rec.requests == []


async def test_keys_and_named_value_values_never_leave_the_arm_layer() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "properties": {
                    "scope": "/products/p",
                    "primaryKey": "pk",
                    "secondaryKey": "sk",
                    "value": "v",
                }
            },
        )

    arm, rec, _ = _arm(handler)
    sub = await arm.get("subscriptions/s1")
    assert (
        sub is not None
        and "primaryKey" not in sub.properties
        and "secondaryKey" not in sub.properties
    )
    nv = await arm.get("namedValues/n1")
    assert nv is not None and "value" not in nv.properties
    for path, body in (
        ("subscriptions/s1", {"primaryKey": "k"}),
        ("namedValues/n1", {"value": "v"}),
    ):
        with pytest.raises(InvalidSchemaError) as err:
            await arm.put(path, body, if_match=None)
        assert err.value.reason == "secret_in_payload"
    assert [r.method for r in rec.requests] == ["GET", "GET"]


async def test_delete_with_if_match_and_404_is_false() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404 if request.url.path.endswith("gone") else 200)

    arm, rec, _ = _arm(handler)
    deleted = await arm.delete("backends/b1", if_match='"e1"')
    assert deleted is True
    assert rec.requests[0].headers["If-Match"] == '"e1"'
    missing = await arm.delete("backends/gone", if_match='"e1"')
    assert missing is False


async def test_status_mapping_carries_no_body() -> None:
    secret_body = {"error": {"message": "<policies>{{foundry-key}}</policies>"}}
    arm, _, _ = _arm(lambda r: httpx.Response(403, json=secret_body))
    with pytest.raises(ForbiddenError) as err:
        await arm.put("apis/a1", {"path": "a"}, if_match=None)
    assert "foundry-key" not in str(err.value) and "<" not in str(err.value)


async def test_profile_refuses_a_client_outside_the_cloud() -> None:
    client = httpx.AsyncClient(base_url="https://management.usgovcloudapi.net")
    with pytest.raises(CapabilityUnavailableError) as err:
        HttpApimArm(client, ARM_ID, profile=profile_for(CloudName.COMMERCIAL))
    assert err.value.reason == "endpoint_cloud_mismatch"
    await client.aclose()


async def test_transport_error_is_dependency_transient() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    arm, _, _ = _arm(boom)
    with pytest.raises(DependencyTransientError) as err:
        await arm.get("apis/a1")
    assert err.value.reason == "arm_unreachable"
