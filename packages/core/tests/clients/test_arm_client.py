"""ARM / Log Analytics client factories: base URL, bearer scope, refresh, cloud guard."""

from __future__ import annotations

import time

import httpx
import pytest
from azure.core.credentials import AccessToken
from neurosphere_core.clients import (
    arm_client,
    assert_host_in_cloud,
    log_analytics_client,
    log_analytics_query_host,
)
from neurosphere_core.cloud import CloudName, profile_for
from neurosphere_core.errors import CapabilityUnavailableError


class _FakeCredential:
    """Async credential double; each call returns a fresh token with a chosen lifetime."""

    def __init__(self, lifetime_seconds: int) -> None:
        self.lifetime = lifetime_seconds
        self.scopes: list[str] = []

    async def get_token(self, *scopes: str, **_: object) -> AccessToken:
        self.scopes.append(scopes[0])
        n = len(self.scopes)
        return AccessToken(f"tok-{n}", int(time.time()) + self.lifetime)

    async def close(self) -> None:
        return None


def _echo(seen: list[httpx.Request]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={})

    return httpx.MockTransport(handler)


@pytest.mark.parametrize(
    ("cloud", "host"),
    [
        (CloudName.COMMERCIAL, "management.azure.com"),
        (CloudName.GOVERNMENT, "management.usgovcloudapi.net"),
    ],
)
async def test_arm_client_base_url_scope_and_header(cloud: CloudName, host: str) -> None:
    seen: list[httpx.Request] = []
    cred = _FakeCredential(3600)
    async with arm_client(profile_for(cloud), cred, transport=_echo(seen)) as client:  # type: ignore[arg-type]
        await client.get("subscriptions?api-version=2022-12-01")
    assert seen[0].url.host == host
    assert seen[0].headers["Authorization"] == "Bearer tok-1"
    assert cred.scopes == [f"https://{host}/.default"]


@pytest.mark.parametrize(
    ("cloud", "host"),
    [
        (CloudName.COMMERCIAL, "api.loganalytics.io"),
        (CloudName.GOVERNMENT, "api.loganalytics.us"),
    ],
)
async def test_log_analytics_client(cloud: CloudName, host: str) -> None:
    profile = profile_for(cloud)
    assert log_analytics_query_host(profile) == host
    seen: list[httpx.Request] = []
    cred = _FakeCredential(3600)
    async with log_analytics_client(profile, cred, transport=_echo(seen)) as client:  # type: ignore[arg-type]
        await client.post("v1/workspaces/w/query", json={"query": "x"})
    assert seen[0].url.host == host
    assert cred.scopes == [f"https://{host}/.default"]


async def test_token_cached_when_far_from_expiry() -> None:
    seen: list[httpx.Request] = []
    cred = _FakeCredential(3600)
    profile = profile_for(CloudName.COMMERCIAL)
    async with arm_client(profile, cred, transport=_echo(seen)) as client:  # type: ignore[arg-type]
        await client.get("a")
        await client.get("b")
    assert len(cred.scopes) == 1
    assert [r.headers["Authorization"] for r in seen] == ["Bearer tok-1", "Bearer tok-1"]


async def test_token_refreshed_within_five_minutes_of_expiry() -> None:
    seen: list[httpx.Request] = []
    cred = _FakeCredential(200)  # inside the 300s skew: every request refreshes
    profile = profile_for(CloudName.COMMERCIAL)
    async with arm_client(profile, cred, transport=_echo(seen)) as client:  # type: ignore[arg-type]
        await client.get("a")
        await client.get("b")
    assert [r.headers["Authorization"] for r in seen] == ["Bearer tok-1", "Bearer tok-2"]


async def test_government_client_refuses_commercial_host_and_sends_no_token() -> None:
    seen: list[httpx.Request] = []
    cred = _FakeCredential(3600)
    profile = profile_for(CloudName.GOVERNMENT)
    async with arm_client(profile, cred, transport=_echo(seen)) as client:  # type: ignore[arg-type]
        with pytest.raises(CapabilityUnavailableError):
            await client.get("https://management.azure.com/subscriptions")
    assert seen == []
    assert cred.scopes == []


@pytest.mark.parametrize(
    "url",
    [
        "https://management.azure.com/",
        "https://api.loganalytics.io/",
        "https://contoso.azure-api.net/",
        "https://evil.example.com/",
        "https://management.usgovcloudapi.net.evil.com/",
    ],
)
def test_government_guard_refuses_non_government_hosts(url: str) -> None:
    with pytest.raises(CapabilityUnavailableError) as exc:
        assert_host_in_cloud(profile_for(CloudName.GOVERNMENT), url)
    assert exc.value.code == "capability_unavailable"


@pytest.mark.parametrize(
    ("cloud", "url"),
    [
        (CloudName.GOVERNMENT, "https://contoso.azure-api.us/x"),
        (CloudName.GOVERNMENT, "https://login.microsoftonline.us/"),
        (CloudName.COMMERCIAL, "https://contoso.azure-api.net/x"),
        (CloudName.COMMERCIAL, "https://management.azure.com/"),
    ],
)
def test_guard_accepts_in_cloud_hosts(cloud: CloudName, url: str) -> None:
    assert_host_in_cloud(profile_for(cloud), url)


def test_commercial_guard_refuses_government_host() -> None:
    with pytest.raises(CapabilityUnavailableError):
        assert_host_in_cloud(profile_for(CloudName.COMMERCIAL), "https://contoso.azure-api.us/")
