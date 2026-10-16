"""Consented resource scan: visibility, consent, read-only, reader behaviour, route authz."""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import httpx
import neurosphere_api.deploy.scan as scan_pkg
import pytest
from authz.authz_helpers import Harness  # pyright: ignore[reportMissingImports]
from neurosphere_api.deploy.scan import (
    SCAN_QUERY,
    HttpxResourceGraphReader,
    ScanRequest,
    ScanService,
    build_router,
    configure_scan,
)
from neurosphere_core.cloud import CloudName, profile_for
from neurosphere_core.errors import DependencyTransientError, ForbiddenError
from pydantic import ValidationError

from .conftest import ADMIN, VIEWER, FakeCredential

SUB_A = "aaaaaaaa-0000-4000-8000-000000000001"
SUB_B = "bbbbbbbb-0000-4000-8000-000000000002"
SUB_C = "cccccccc-0000-4000-8000-000000000003"


def _row(sub: str, rtype: str, name: str) -> dict[str, Any]:
    return {
        "id": f"/subscriptions/{sub}/resourceGroups/rg/providers/{rtype}/{name}",
        "name": name,
        "type": rtype,
        "location": "eastus",
        "subscriptionId": sub.upper(),
        "tags": {"owner": "platform"},
        "sku": "Standard",
    }


class FakeReader:
    """Mimics ARG: only rows of readable subscriptions come back, whatever is asked."""

    def __init__(self, readable: set[str], rows: list[dict[str, Any]]) -> None:
        self.readable = readable
        self.rows = rows
        self.queried: list[list[str]] = []

    async def list_readable_subscriptions(self) -> frozenset[str]:
        return frozenset(self.readable)

    async def query(self, subscriptions: Sequence[str], query: str) -> list[dict[str, Any]]:
        assert query == SCAN_QUERY
        self.queried.append(list(subscriptions))
        return [r for r in self.rows if r["subscriptionId"].lower() in self.readable]


def _consent(*subs: str) -> dict[str, Any]:
    return {
        "consent_id": "consent-1",
        "consented_by": "owner@example.com",
        "consented_subscriptions": list(subs),
    }


ROWS = [
    _row(SUB_A, "Microsoft.KeyVault/vaults", "kv-a"),
    _row(SUB_B, "Microsoft.Storage/storageAccounts", "stb"),
    _row(SUB_C, "Microsoft.EventHub/namespaces", "eh-c"),
]


# 1 ---------------------------------------------------------------------------------------


async def test_only_readable_subscriptions_appear_and_unreadable_is_not_visible() -> None:
    reader = FakeReader({SUB_A, SUB_B}, ROWS)
    response = await ScanService(reader).scan(
        ScanRequest.model_validate(
            {"consent": _consent(SUB_A, SUB_B, SUB_C), "subscription_ids": [SUB_A, SUB_B, SUB_C]}
        )
    )
    assert response.visibility_limited is True
    assert "only what the calling identity can read" in response.visibility_note
    by_sub = {s.subscription_id: s for s in response.subscriptions}
    assert by_sub[SUB_A].status == "visible"
    assert [r.name for r in by_sub[SUB_A].resources] == ["kv-a"]
    assert by_sub[SUB_A].resources[0].category == "key_vault"
    assert by_sub[SUB_A].resources[0].subscription_id == SUB_A
    assert [r.name for r in by_sub[SUB_B].resources] == ["stb"]
    assert by_sub[SUB_C].status == "not_visible"
    assert by_sub[SUB_C].resources == []
    assert reader.queried == [[SUB_A, SUB_B]]  # C is never queried
    assert all(s.status in ("visible", "not_visible") for s in response.subscriptions)


async def test_readable_subscription_with_no_resources_is_visible_and_empty() -> None:
    response = await ScanService(FakeReader({SUB_A}, [])).scan(
        ScanRequest.model_validate({"consent": _consent(SUB_A), "subscription_ids": [SUB_A]})
    )
    assert response.subscriptions[0].status == "visible"
    assert response.subscriptions[0].resources == []


async def test_rows_from_unrequested_subscriptions_are_dropped() -> None:
    class Leaky(FakeReader):
        async def query(self, subscriptions: Sequence[str], query: str) -> list[dict[str, Any]]:
            return self.rows

    response = await ScanService(Leaky({SUB_A, SUB_C}, ROWS)).scan(
        ScanRequest.model_validate({"consent": _consent(SUB_A), "subscription_ids": [SUB_A]})
    )
    assert [r.name for s in response.subscriptions for r in s.resources] == ["kv-a"]


# 2 ---------------------------------------------------------------------------------------


async def test_scan_refuses_without_consent() -> None:
    reader = FakeReader({SUB_A}, ROWS)
    with pytest.raises(ForbiddenError) as err:
        await ScanService(reader).scan(ScanRequest.model_validate({"subscription_ids": [SUB_A]}))
    assert err.value.reason == "consent_missing"
    assert reader.queried == []


async def test_scan_refuses_subscription_not_covered_by_consent() -> None:
    reader = FakeReader({SUB_A, SUB_B}, ROWS)
    with pytest.raises(ForbiddenError) as err:
        await ScanService(reader).scan(
            ScanRequest.model_validate(
                {"consent": _consent(SUB_A), "subscription_ids": [SUB_A, SUB_B]}
            )
        )
    assert err.value.reason == "consent_not_covering"
    assert reader.queried == []


def test_subscription_ids_must_be_guids() -> None:
    with pytest.raises(ValidationError):
        ScanRequest.model_validate({"subscription_ids": ["not-a-guid'; drop"]})


# 3 ---------------------------------------------------------------------------------------


def _sources() -> dict[str, str]:
    root = Path(scan_pkg.__file__).parent
    return {p.name: p.read_text(encoding="utf-8") for p in root.glob("*.py")}


def test_module_is_read_only() -> None:
    posts = 0
    for name, text in _sources().items():
        assert not re.search(r"\.(put|patch|delete|request|send)\(", text), name
        assert not re.search(r"""["'](PUT|PATCH|DELETE)["']""", text), name
        assert "management.azure.com" not in text and "usgovcloudapi" not in text, name
        posts += len(re.findall(r"client\.post\(", text))
    assert posts == 1
    graph = _sources()["graph.py"]
    assert 'ARG_PATH: Final = "providers/Microsoft.ResourceGraph/resources"' in graph
    assert re.search(r'"POST",\s*url,', graph)
    assert 'url = f"{self._base}{ARG_PATH}?' in graph
    # Only the token scope, the subscription list GET and the ARG POST are built from the host.
    suffixes = re.findall(r'f"\{self\._base\}(\{?[A-Za-z_.]+\}?)', graph)
    assert sorted(suffixes) == sorted(["{SUBSCRIPTIONS_PATH}", "{ARG_PATH}", ".default"])


# 4 ---------------------------------------------------------------------------------------


def _reader(
    handler: Callable[[httpx.Request], httpx.Response],
    cloud: CloudName,
    cred: FakeCredential,
    **kw: Any,
) -> HttpxResourceGraphReader:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return HttpxResourceGraphReader(cred, profile_for(cloud), client=client, **kw)


async def test_government_profile_uses_usgov_host_and_scope(credential: FakeCredential) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.method == "GET":
            return httpx.Response(200, json={"value": [{"subscriptionId": SUB_A.upper()}]})
        return httpx.Response(200, json={"data": [_row(SUB_A, "Microsoft.KeyVault/vaults", "k")]})

    reader = _reader(handler, CloudName.GOVERNMENT, credential)
    assert await reader.list_readable_subscriptions() == {SUB_A}
    rows = await reader.query([SUB_A], SCAN_QUERY)
    assert len(rows) == 1
    assert {r.url.host for r in seen} == {"management.usgovcloudapi.net"}
    assert not any(r.url.host.endswith(".com") for r in seen)
    assert [r.method for r in seen] == ["GET", "POST"]
    assert seen[1].url.path.endswith("/providers/Microsoft.ResourceGraph/resources")
    assert credential.scopes
    assert all(s == "https://management.usgovcloudapi.net/.default" for s in credential.scopes)


async def test_commercial_profile_host(credential: FakeCredential) -> None:
    hosts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        hosts.append(request.url.host)
        return httpx.Response(200, json={"value": []})

    await _reader(handler, CloudName.COMMERCIAL, credential).list_readable_subscriptions()
    assert hosts == [profile_for(CloudName.COMMERCIAL).management_host]


async def test_skip_token_paging_is_followed(credential: FakeCredential) -> None:
    bodies: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        body = json.loads(request.content)
        bodies.append(body)
        if "$skipToken" not in body["options"]:
            return httpx.Response(
                200,
                json={"data": [_row(SUB_A, "Microsoft.KeyVault/vaults", "k1")], "$skipToken": "t1"},
            )
        return httpx.Response(200, json={"data": [_row(SUB_A, "Microsoft.KeyVault/vaults", "k2")]})

    rows = await _reader(handler, CloudName.COMMERCIAL, credential).query([SUB_A], SCAN_QUERY)
    assert [r["name"] for r in rows] == ["k1", "k2"]
    assert bodies[1]["options"]["$skipToken"] == "t1"
    assert bodies[0]["query"] == SCAN_QUERY == bodies[1]["query"]


@pytest.mark.parametrize("status", [429, 500, 503])
async def test_throttle_and_server_errors_are_transient(
    credential: FakeCredential, status: int
) -> None:
    reader = _reader(
        lambda _: httpx.Response(status, headers={"retry-after": "7"}),
        CloudName.COMMERCIAL,
        credential,
    )
    with pytest.raises(DependencyTransientError) as err:
        await reader.query([SUB_A], SCAN_QUERY)
    assert err.value.retry_after_seconds == 7


async def test_timeout_is_transient(credential: FakeCredential) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(DependencyTransientError):
        await _reader(handler, CloudName.COMMERCIAL, credential).list_readable_subscriptions()


async def test_foreign_next_link_is_not_followed(credential: FakeCredential) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.host)
        return httpx.Response(
            200, json={"value": [], "nextLink": "https://evil.example.net/subscriptions?x=1"}
        )

    await _reader(handler, CloudName.COMMERCIAL, credential).list_readable_subscriptions()
    assert len(calls) == 1


# 5 ---------------------------------------------------------------------------------------


def _mounted(mount: Callable[[dict[str, Any]], Harness]) -> Harness:
    h = mount({"/v1/deploy/scan": build_router()})
    configure_scan(h.app, ScanService(FakeReader({SUB_A, SUB_B}, ROWS)))
    return h


def test_route_requires_config_manage(mount: Callable[[dict[str, Any]], Harness]) -> None:
    h = _mounted(mount)
    body = {"consent": _consent(SUB_A), "subscription_ids": [SUB_A]}
    denied = h.client.post("/v1/deploy/scan", json=body, headers=h.auth(VIEWER))
    assert denied.status_code == 403
    assert denied.json()["reason"] == "permission_missing"
    assert h.client.post("/v1/deploy/scan", json=body).status_code == 401


def test_route_end_to_end_and_consent_403(mount: Callable[[dict[str, Any]], Harness]) -> None:
    h = _mounted(mount)
    ok = h.client.post(
        "/v1/deploy/scan",
        json={"consent": _consent(SUB_A, SUB_C), "subscription_ids": [SUB_A, SUB_C]},
        headers=h.auth(ADMIN),
    )
    assert ok.status_code == 200, ok.text
    data = ok.json()
    assert data["visibility_limited"] is True
    assert [(s["subscription_id"], s["status"]) for s in data["subscriptions"]] == [
        (SUB_A, "visible"),
        (SUB_C, "not_visible"),
    ]
    missing = h.client.post(
        "/v1/deploy/scan", json={"subscription_ids": [SUB_A]}, headers=h.auth(ADMIN)
    )
    assert missing.status_code == 403
    assert missing.json()["code"] == "forbidden"
    assert missing.json()["reason"] == "consent_missing"
