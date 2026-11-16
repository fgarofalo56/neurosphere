"""``BearerDeployHttp`` (PRP-55 item 3): one token scope per host of the deployment cloud, a
foreign or non-https host is refused before a token is requested, the credential is lazy."""

from __future__ import annotations

import httpx
import pytest
from neurosphere_core.cloud import CloudName, profile_for
from neurosphere_core.deploy.fabric import fabric_endpoints_for
from neurosphere_core.errors import DependencyTransientError, InvalidSchemaError
from neurosphere_workers.actions.deploy_http import (
    BearerDeployHttp,
    arm_token_scope,
    deploy_scopes,
)

from .fake_arm import FakeCredential

GOV_SCOPE = "https://configured.example.us/.default"


def test_scopes_follow_the_cloud_profile() -> None:
    commercial = profile_for(CloudName.COMMERCIAL)
    government = profile_for(CloudName.GOVERNMENT)
    assert arm_token_scope(commercial) == "https://management.azure.com/.default"
    assert arm_token_scope(government) == "https://management.usgovcloudapi.net/.default"
    assert deploy_scopes(commercial, fabric_endpoints_for(CloudName.COMMERCIAL)) == {
        "management.azure.com": "https://management.azure.com/.default",
        "api.fabric.microsoft.com": "https://api.fabric.microsoft.com/.default",
    }
    gov = deploy_scopes(
        government, fabric_endpoints_for(CloudName.GOVERNMENT, token_scope=GOV_SCOPE)
    )
    assert gov == {
        "management.usgovcloudapi.net": "https://management.usgovcloudapi.net/.default",
        "highapi.fabric.microsoft.us": GOV_SCOPE,
    }
    assert all("azure.com" not in host for host in gov)


def test_fabric_endpoints_of_another_cloud_are_never_bridged() -> None:
    with pytest.raises(InvalidSchemaError) as raised:
        deploy_scopes(profile_for(CloudName.GOVERNMENT), fabric_endpoints_for(CloudName.COMMERCIAL))
    assert raised.value.reason == "cloud_mismatch"


async def test_each_host_gets_its_own_scope_and_the_body_is_parsed() -> None:
    seen: list[tuple[str, str | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.host, request.headers.get("authorization")))
        return httpx.Response(200, json={"ok": True}, headers={"Retry-After": "3"})

    credential = FakeCredential()
    profile = profile_for(CloudName.COMMERCIAL)
    http = BearerDeployHttp(
        httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        lambda: credential,  # type: ignore[arg-type, return-value]
        deploy_scopes(profile, fabric_endpoints_for(CloudName.COMMERCIAL)),
    )
    arm = await http.request("GET", "https://management.azure.com/subscriptions?api-version=1")
    fabric = await http.request("POST", "https://api.fabric.microsoft.com/v1/workspaces", {"a": 1})
    assert arm.status_code == fabric.status_code == 200
    assert arm.body == {"ok": True} and arm.header("retry-after") == "3"
    assert credential.scopes == [
        "https://management.azure.com/.default",
        "https://api.fabric.microsoft.com/.default",
    ]
    assert [h for h, _ in seen] == ["management.azure.com", "api.fabric.microsoft.com"]
    assert all(auth == "Bearer fake-token-not-a-secret" for _, auth in seen)


@pytest.mark.parametrize(
    "url",
    [
        "https://management.usgovcloudapi.net/subscriptions",  # another cloud
        "http://management.azure.com/subscriptions",  # not https
        "https://evilmanagement.azure.com/x",  # look-alike host
        "https://api.fabric.microsoft.com/v1/workspaces",  # Fabric not wired
    ],
)
async def test_foreign_hosts_are_refused_before_a_token_is_requested(url: str) -> None:
    created: list[FakeCredential] = []

    def factory() -> FakeCredential:
        created.append(FakeCredential())
        return created[-1]

    http = BearerDeployHttp(
        httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200))),
        factory,  # type: ignore[arg-type]
        deploy_scopes(profile_for(CloudName.COMMERCIAL)),
    )
    with pytest.raises(InvalidSchemaError) as raised:
        await http.request("GET", url)
    assert raised.value.reason == "host_not_allowed"
    assert created == []  # the credential was never even built


async def test_an_unreachable_host_is_transient_and_empty_bodies_are_none() -> None:
    def broken(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    profile = profile_for(CloudName.COMMERCIAL)
    http = BearerDeployHttp(
        httpx.AsyncClient(transport=httpx.MockTransport(broken)),
        FakeCredential,  # type: ignore[arg-type]
        deploy_scopes(profile),
    )
    with pytest.raises(DependencyTransientError) as raised:
        await http.request("GET", "https://management.azure.com/x")
    assert raised.value.reason == "deploy_host_unreachable"

    empty = BearerDeployHttp(
        httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(204))),
        FakeCredential,  # type: ignore[arg-type]
        deploy_scopes(profile),
    )
    assert (await empty.request("GET", "https://management.azure.com/x")).body is None


def test_at_least_one_scope_is_required() -> None:
    with pytest.raises(ValueError):
        BearerDeployHttp(httpx.AsyncClient(), FakeCredential, {})  # type: ignore[arg-type]
