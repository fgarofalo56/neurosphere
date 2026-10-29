"""Fake ARM for the gateway registry tests: a ``MockTransport`` handler serving one APIM service.

Records every request so tests can assert read-only behaviour. Serves paging (``nextLink`` on the
API list), injected 429s, a pool backend with a circuit breaker, a policy fragment WITH a body and
a subscription WITH a key (both must be dropped by the snapshot).
"""

from __future__ import annotations

import time
from typing import Any

import httpx
from azure.core.credentials import AccessToken

SUBSCRIPTION = "11111111-2222-4333-8444-555555555555"
RID = (
    f"/subscriptions/{SUBSCRIPTION}/resourceGroups/rg-apim"
    "/providers/Microsoft.ApiManagement/service/apim-demo"
)
WORKSPACE_GUID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
WORKSPACE_RID = (
    f"/subscriptions/{SUBSCRIPTION}/resourceGroups/rg-obs"
    "/providers/Microsoft.OperationalInsights/workspaces/law-demo"
)
SECRET_MARKER = "SUPER-SECRET-KEY-VALUE"  # noqa: S105 - fake marker proving keys are dropped
XML_MARKER = "<policies><inbound><set-header name='x-secret'/></inbound></policies>"


class FakeCredential:
    async def get_token(self, *scopes: str, **_: object) -> AccessToken:
        return AccessToken("fake-token", int(time.time()) + 3600)

    async def close(self) -> None:
        return None


def _list(value: list[dict[str, Any]], next_link: str | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"value": value}
    if next_link:
        body["nextLink"] = next_link
    return body


class FakeArm:
    def __init__(
        self,
        *,
        sku: str = "StandardV2",
        llm_logs: bool = True,
        mcp_logs: bool = False,
        throttle: int = 0,
        throttle_forever: bool = False,
        next_link_host: str = "management.azure.com",
        service_status: int = 200,
        diag_category_group: str | None = None,
    ) -> None:
        self.sku = sku
        self.llm_logs = llm_logs
        self.mcp_logs = mcp_logs
        self.throttle = throttle
        self.throttle_forever = throttle_forever
        self.next_link_host = next_link_host
        self.service_status = service_status
        self.diag_category_group = diag_category_group
        self.requests: list[httpx.Request] = []
        self.sleeps: list[float] = []

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    @property
    def methods(self) -> set[str]:
        return {r.method for r in self.requests}

    @property
    def paths(self) -> list[str]:
        return [r.url.path for r in self.requests]

    def _diagnostics(self) -> dict[str, Any]:
        logs: list[dict[str, Any]] = [{"category": "GatewayLogs", "enabled": True}]
        logs.append({"category": "GatewayLlmLogs", "enabled": self.llm_logs})
        logs.append({"category": "GatewayMCPLogs", "enabled": self.mcp_logs})
        if self.diag_category_group:
            logs = [{"categoryGroup": self.diag_category_group, "enabled": True}]
        return _list(
            [
                {
                    "name": "to-law",
                    "properties": {"workspaceId": WORKSPACE_RID, "logs": logs},
                }
            ]
        )

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        low = path.lower()
        base = RID.lower()
        if self.throttle_forever or (self.throttle > 0 and low == f"{base}/apis"):
            if not self.throttle_forever:
                self.throttle -= 1
            return httpx.Response(429, headers={"Retry-After": "2"}, json={})
        if low == base:
            if self.service_status != 200:
                return httpx.Response(self.service_status, json={})
            return httpx.Response(
                200, json={"name": "apim-demo", "sku": {"name": self.sku, "capacity": 1}}
            )
        if low == f"{base}/providers/microsoft.insights/diagnosticsettings":
            return httpx.Response(200, json=self._diagnostics())
        if low == f"{base}/apis":
            if "skiptoken" not in str(request.url):
                link = (
                    f"https://{self.next_link_host}{RID}/apis?api-version=2024-05-01&$skiptoken=p2"
                )
                return httpx.Response(
                    200,
                    json=_list(
                        [
                            {
                                "name": "chat",
                                "properties": {
                                    "displayName": "Chat",
                                    "path": "openai",
                                    "protocols": ["https"],
                                    "type": "http",
                                    "subscriptionRequired": True,
                                    "apiRevision": "1",
                                },
                            }
                        ],
                        link,
                    ),
                )
            return httpx.Response(
                200,
                json=_list(
                    [{"name": "tools", "properties": {"displayName": "Tools", "path": "tools"}}]
                ),
            )
        if low == f"{base}/apis/chat/operations":
            return httpx.Response(
                200,
                json=_list(
                    [
                        {
                            "name": "completions",
                            "properties": {"method": "POST", "urlTemplate": "/chat/completions"},
                        }
                    ]
                ),
            )
        if low == f"{base}/apis/tools/operations":
            return httpx.Response(200, json=_list([]))
        if low == f"{base}/products":
            return httpx.Response(
                200,
                json=_list(
                    [
                        {
                            "name": "starter",
                            "properties": {
                                "displayName": "Starter",
                                "state": "published",
                                "subscriptionRequired": True,
                                "approvalRequired": False,
                            },
                        }
                    ]
                ),
            )
        if low == f"{base}/products/starter/apis":
            return httpx.Response(200, json=_list([{"name": "chat"}]))
        if low == f"{base}/backends":
            return httpx.Response(200, json=self._backends())
        if low == f"{base}/policyfragments":
            return httpx.Response(
                200,
                json=_list(
                    [
                        {
                            "name": "frag-1",
                            "properties": {"description": "rate limit", "value": XML_MARKER},
                        }
                    ]
                ),
            )
        if low == f"{base}/subscriptions":
            return httpx.Response(
                200,
                json=_list(
                    [
                        {
                            "name": "sub-1",
                            "properties": {
                                "displayName": "Team A",
                                "scope": f"{RID}/products/starter",
                                "state": "active",
                                "primaryKey": SECRET_MARKER,
                                "secondaryKey": SECRET_MARKER,
                            },
                        }
                    ]
                ),
            )
        return httpx.Response(404, json={"error": "unexpected path " + path})

    @staticmethod
    def _backends() -> dict[str, Any]:
        return _list(
            [
                {
                    "name": "foundry-east",
                    "properties": {
                        "type": "Single",
                        "url": "https://east.openai.azure.com/openai",
                        "circuitBreaker": {
                            "rules": [
                                {
                                    "name": "trip-on-429",
                                    "tripDuration": "PT1M",
                                    "failureCondition": {
                                        "count": 3,
                                        "interval": "PT10S",
                                        "statusCodeRanges": [
                                            {"min": 429, "max": 429},
                                            {"min": 500, "max": 599},
                                        ],
                                    },
                                }
                            ]
                        },
                    },
                },
                {
                    "name": "foundry-pool",
                    "properties": {
                        "type": "Pool",
                        "pool": {
                            "services": [
                                {
                                    "id": f"{RID}/backends/foundry-east",
                                    "weight": 3,
                                    "priority": 1,
                                },
                                {"id": f"{RID}/backends/foundry-west", "weight": 1, "priority": 2},
                            ]
                        },
                    },
                },
            ]
        )
