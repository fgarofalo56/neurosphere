"""RestProjectReader against the documented Foundry REST paths (respx; no network)."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx
from neurosphere_connector_foundry import (
    CapabilityStatus,
    FoundryDiscoveryConnector,
    RestProjectReader,
    capability_reports,
    project_endpoint,
)
from neurosphere_connector_foundry.reader import map_http_status
from neurosphere_core.cloud.profile import CloudName
from neurosphere_core.errors import (
    DependencyTransientError,
    ForbiddenError,
    RateLimitedError,
    UnauthorizedError,
)

ENDPOINT = project_endpoint(CloudName.COMMERCIAL, "res-one", "proj-one")
GOV_ENDPOINT = project_endpoint(CloudName.GOVERNMENT, "res-one", "proj-one")
SECRET_TOKEN = "tok-secret-value"  # noqa: S105  # test fixture, not a credential


async def _token() -> str:
    return SECRET_TOKEN


def _reader(
    cloud: CloudName = CloudName.COMMERCIAL, *, sleeps: list[float] | None = None, **kw: Any
) -> RestProjectReader:
    async def fake_sleep(seconds: float) -> None:
        if sleeps is not None:
            sleeps.append(seconds)

    endpoint = ENDPOINT if cloud is CloudName.COMMERCIAL else GOV_ENDPOINT
    return RestProjectReader(
        endpoint=endpoint, token_provider=_token, cloud=cloud, sleep=fake_sleep, **kw
    )


async def _collect(it: Any) -> list[Any]:
    return [x async for x in it]


@respx.mock
async def test_agents_cursor_pagination_uses_after_and_documented_params() -> None:
    route = respx.get(f"{ENDPOINT}/agents").mock(
        side_effect=[
            httpx.Response(
                200,
                json={
                    "data": [{"id": "a1", "name": "one"}, {"id": "a2", "name": "two"}],
                    "has_more": True,
                    "last_id": "a2",
                },
            ),
            httpx.Response(
                200,
                json={
                    "data": [{"id": "a3", "name": "three", "versions": {"latest": {"id": "v"}}}],
                    "has_more": False,
                    "last_id": "a3",
                },
            ),
        ]
    )
    reader = _reader()
    rows = await _collect(reader.list_agents(page_size=2))
    assert [r["name"] for r in rows] == ["one", "two", "three"]
    assert rows[2]["versions"] == {"latest": {"id": "v"}}
    first, second = (c.request for c in route.calls)
    assert first.url.params["api-version"] == "v1"
    assert first.url.params["limit"] == "2"
    assert "after" not in first.url.params
    assert second.url.params["after"] == "a2"
    assert first.headers["authorization"] == f"Bearer {SECRET_TOKEN}"
    assert "foundry-features" not in first.headers  # preview opt-in is never sent
    assert reader.budget_exceeded == frozenset()


@respx.mock
async def test_agents_page_size_is_clamped_to_documented_range() -> None:
    route = respx.get(f"{ENDPOINT}/agents").mock(
        return_value=httpx.Response(200, json={"data": [], "has_more": False})
    )
    await _collect(_reader().list_agents(page_size=5000))
    assert route.calls[0].request.url.params["limit"] == "100"


@respx.mock
async def test_agents_missing_has_more_falls_back_to_full_page_heuristic() -> None:
    respx.get(f"{ENDPOINT}/agents").mock(
        side_effect=[
            httpx.Response(200, json={"data": [{"id": "a1"}, {"id": "a2"}]}),
            httpx.Response(200, json={"data": [{"id": "a3"}]}),
        ]
    )
    rows = await _collect(_reader().list_agents(page_size=2))
    assert [r["id"] for r in rows] == ["a1", "a2", "a3"]


@respx.mock
async def test_agents_page_budget_exceeded_is_partial_not_unbounded() -> None:
    route = respx.get(f"{ENDPOINT}/agents").mock(
        side_effect=lambda request: httpx.Response(  # pyright: ignore[reportUnknownLambdaType]
            200,
            json={
                "data": [{"id": f"id-{len(route.calls)}"}],
                "has_more": True,
                "last_id": f"id-{len(route.calls)}",
            },
        )
    )
    reader = _reader(max_pages=3)
    rows = await _collect(reader.list_agents(page_size=1))
    assert len(rows) == 3
    assert route.call_count == 3
    assert reader.budget_exceeded == frozenset({"agents"})


@respx.mock
async def test_agents_non_advancing_cursor_stops() -> None:
    route = respx.get(f"{ENDPOINT}/agents").mock(
        return_value=httpx.Response(
            200, json={"data": [{"id": "same"}], "has_more": True, "last_id": "same"}
        )
    )
    reader = _reader(max_pages=50)
    await _collect(reader.list_agents(page_size=1))
    assert route.call_count == 2  # second page repeats the cursor, so the loop stops
    assert reader.budget_exceeded == frozenset({"agents"})


@respx.mock
async def test_deployments_paging_follows_next_link_and_maps_fields() -> None:
    next_url = f"{ENDPOINT}/deployments?api-version=v1&page=2"
    route = respx.get(f"{ENDPOINT}/deployments").mock(
        side_effect=[
            httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "name": "gpt",
                            "type": "ModelDeployment",
                            "modelName": "gpt-4.1",
                            "modelVersion": "2025-04-14",
                            "modelPublisher": "OpenAI",
                            "sku": {"name": "Standard", "capacity": 10},
                            "capabilities": {"chat_completion": "true"},
                            "connectionName": "conn",
                        }
                    ],
                    "nextLink": next_url,
                },
            ),
            httpx.Response(200, json={"value": [{"name": "emb"}]}),
        ]
    )
    reader = _reader()
    rows = await _collect(reader.list_deployments())
    assert [r["name"] for r in rows] == ["gpt", "emb"]
    assert rows[0]["model_name"] == "gpt-4.1"
    assert rows[0]["model_version"] == "2025-04-14"
    assert rows[0]["model_publisher"] == "OpenAI"
    assert rows[0]["connection_name"] == "conn"
    assert rows[1]["model_name"] is None  # absent stays None
    assert route.calls[0].request.url.params["api-version"] == "v1"
    assert route.calls[1].request.url.params["page"] == "2"
    assert reader.budget_exceeded == frozenset()


@respx.mock
async def test_deployments_page_budget_exceeded_and_connector_marks_partial() -> None:
    link = f"{ENDPOINT}/deployments?api-version=v1&page="
    counter = {"n": 0}

    def page(request: httpx.Request) -> httpx.Response:
        counter["n"] += 1
        return httpx.Response(
            200,
            json={"value": [{"name": f"d{counter['n']}"}], "nextLink": f"{link}{counter['n']}"},
        )

    respx.get(url__startswith=f"{ENDPOINT}/deployments").mock(side_effect=page)
    respx.get(f"{ENDPOINT}/agents").mock(
        return_value=httpx.Response(200, json={"data": [], "has_more": False})
    )
    reader = _reader(max_pages=2)
    connector = FoundryDiscoveryConnector(
        reader=reader, cloud=CloudName.COMMERCIAL, project_endpoint=ENDPOINT
    )
    result = await connector.discover()
    assert counter["n"] == 2
    assert result.deployments is not None and len(result.deployments) == 2
    assert result.deployments_truncated is True
    cov = await connector.coverage()
    assert cov.partial is True


@respx.mock
async def test_next_link_off_host_is_never_followed_with_token() -> None:
    respx.get(f"{ENDPOINT}/deployments").mock(
        return_value=httpx.Response(
            200,
            json={"value": [{"name": "d"}], "nextLink": "https://evil.example/deployments"},
        )
    )
    evil = respx.get("https://evil.example/deployments").mock(return_value=httpx.Response(200))
    reader = _reader()
    rows = await _collect(reader.list_deployments())
    assert len(rows) == 1
    assert not evil.called
    assert reader.budget_exceeded == frozenset({"deployments"})


@respx.mock
async def test_429_retries_with_capped_backoff_then_succeeds() -> None:
    respx.get(f"{ENDPOINT}/agents").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "7"}),
            httpx.Response(200, json={"data": [{"id": "a"}], "has_more": False}),
        ]
    )
    sleeps: list[float] = []
    rows = await _collect(_reader(sleeps=sleeps).list_agents(page_size=10))
    assert len(rows) == 1
    assert sleeps == [7]


@respx.mock
async def test_429_exhausted_raises_rate_limited_with_capped_retry_after() -> None:
    route = respx.get(f"{ENDPOINT}/agents").mock(
        return_value=httpx.Response(429, headers={"Retry-After": "86400"})
    )
    sleeps: list[float] = []
    with pytest.raises(RateLimitedError) as info:
        await _collect(_reader(sleeps=sleeps, max_retries=2).list_agents(page_size=10))
    assert route.call_count == 3  # first try + 2 bounded retries
    assert sleeps == [30, 30]  # Retry-After capped at 30 s
    assert info.value.retry_after_seconds == 30


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (401, UnauthorizedError),
        (403, ForbiddenError),
        (500, DependencyTransientError),
        (503, DependencyTransientError),
        (404, DependencyTransientError),
    ],
)
@respx.mock
async def test_error_statuses_map_without_leaking_body_or_token(
    status: int, expected: type[Exception]
) -> None:
    respx.get(f"{ENDPOINT}/deployments").mock(
        return_value=httpx.Response(status, text="BODY-SECRET " + SECRET_TOKEN)
    )
    with pytest.raises(expected) as info:
        await _collect(_reader().list_deployments())
    text = f"{info.value!s} {info.value!r} {getattr(info.value, 'detail', '')}"
    assert "BODY-SECRET" not in text and SECRET_TOKEN not in text


@respx.mock
async def test_transport_error_and_bad_json_are_transient() -> None:
    respx.get(f"{ENDPOINT}/agents").mock(side_effect=httpx.ConnectError("boom " + SECRET_TOKEN))
    with pytest.raises(DependencyTransientError) as info:
        await _collect(_reader().list_agents(page_size=10))
    assert SECRET_TOKEN not in f"{info.value!s}{info.value!r}"

    respx.get(f"{ENDPOINT}/deployments").mock(
        return_value=httpx.Response(200, content=json.dumps(["not", "an", "object"]).encode())
    )
    with pytest.raises(DependencyTransientError):
        await _collect(_reader().list_deployments())


@respx.mock
async def test_token_provider_failure_is_unauthorized() -> None:
    async def broken() -> str:
        raise RuntimeError("cannot reach IMDS")

    reader = RestProjectReader(endpoint=ENDPOINT, token_provider=broken, cloud=CloudName.COMMERCIAL)
    with pytest.raises(UnauthorizedError):
        await _collect(reader.list_agents(page_size=10))


def test_map_http_status_defaults() -> None:
    assert isinstance(map_http_status(429), RateLimitedError)
    assert isinstance(map_http_status(502), DependencyTransientError)


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://res-one.services.ai.azure.com/api/projects/p",  # not https
        "https://evil.example/api/projects/p",
        "https://res-one.services.ai.azure.us/api/projects/p",  # wrong cloud
    ],
)
def test_endpoint_must_match_cloud_host(endpoint: str) -> None:
    with pytest.raises(ValueError, match="Foundry project endpoint"):
        RestProjectReader(endpoint=endpoint, token_provider=_token, cloud=CloudName.COMMERCIAL)


@respx.mock
async def test_government_reader_hits_government_host_and_reports_unavailable() -> None:
    route = respx.get(f"{GOV_ENDPOINT}/agents").mock(
        return_value=httpx.Response(200, json={"data": [], "has_more": False})
    )
    respx.get(f"{GOV_ENDPOINT}/deployments").mock(
        return_value=httpx.Response(200, json={"value": []})
    )
    connector = FoundryDiscoveryConnector(
        reader=_reader(CloudName.GOVERNMENT),
        cloud=CloudName.GOVERNMENT,
        project_endpoint=GOV_ENDPOINT,
    )
    result = await connector.discover()
    assert route.called
    assert result.agents == []  # genuinely none found
    by_name = {r.capability: r.status for r in result.capabilities}
    assert by_name["hosted_agents"] is CapabilityStatus.UNAVAILABLE
    assert by_name["web_search"] is CapabilityStatus.UNAVAILABLE


def test_commercial_capabilities_still_unknown() -> None:
    assert {r.status for r in capability_reports(CloudName.COMMERCIAL)} == {
        CapabilityStatus.UNKNOWN
    }
