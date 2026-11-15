"""The dashboards analytics badge over the builder's health callable (PRP-11 item 3)."""

from __future__ import annotations

import httpx
import pytest
from neurosphere_api.dashboards.analytics import AnalyticsProbe, resolve_analytics
from neurosphere_api.runtime import CompositionOverrides
from neurosphere_api.runtime.builders import analytics as analytics_builder
from runtime_api.runtime_helpers import compose  # pyright: ignore[reportMissingImports]

HOST = "adb-1234567890123456.7.azuredatabricks.net"


async def _token() -> str:
    return "tok-health-opaque"


def _probe(monkeypatch: pytest.MonkeyPatch, handler: object) -> AnalyticsProbe:
    for name, value in (
        ("NS_ANALYTICS_BACKEND", "databricks"),
        ("NS_ANALYTICS_REGION", "eastus2"),
        ("NS_ANALYTICS_DATABRICKS_HOST", HOST),
        ("NS_ANALYTICS_DATABRICKS_WAREHOUSE_ID", "0123456789abcdef"),
        ("NS_ANALYTICS_DATABRICKS_CATALOG", "main"),
        ("NS_ANALYTICS_DATABRICKS_SCHEMA", "ns"),
    ):
        monkeypatch.setenv(name, value)
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),  # type: ignore[arg-type]
        base_url=f"https://{HOST}",
    )
    composed = compose(
        CompositionOverrides(
            backends={"analytics_http_client": client, "analytics_token_provider": _token}
        ),
        builders=(analytics_builder.BUILDER,),
    )
    state = composed.app.state
    return AnalyticsProbe(
        adapter=state.analytics_adapter,
        region=state.analytics_region,
        health=state.analytics_health,
    )


async def test_healthy_backend_reports_available(monkeypatch: pytest.MonkeyPatch) -> None:
    def ok(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "statement_id": "s1",
                "status": {"state": "SUCCEEDED"},
                "result": {"data_array": [["1"]]},
            },
        )

    info = await resolve_analytics(_probe(monkeypatch, ok), lag_seconds=1.0)
    assert info.state == "available"


async def test_failing_health_call_reports_delayed(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error_code": "TEMPORARILY_UNAVAILABLE"})

    info = await resolve_analytics(_probe(monkeypatch, broken), lag_seconds=1.0)
    assert info.state == "delayed"
