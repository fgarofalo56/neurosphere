"""The analytics builder selects, reports and never connects at build time (PRP-11 item 3)."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from neurosphere_api.runtime import CompositionOverrides
from neurosphere_api.runtime.builders import analytics as analytics_builder
from neurosphere_api.runtime.builders import default_builders
from neurosphere_api.runtime.status import OPTIONAL_COMPONENTS
from neurosphere_core.analytics.databricks import DatabricksAnalytics
from neurosphere_core.analytics.fixture import FixtureAnalytics
from neurosphere_core.cloud import CloudName, Settings
from runtime_api.runtime_helpers import Composed, compose  # pyright: ignore[reportMissingImports]

HOST = "adb-1234567890123456.7.azuredatabricks.net"
GOV_HOST = "adb-1234567890123456.7.databricks.azure.us"
WAREHOUSE = "0123456789abcdef"
REGISTRY_TOKEN = "tok-analytics-builder-opaque"  # noqa: S105 - opaque test value


def _databricks_env(
    monkeypatch: pytest.MonkeyPatch, host: str = HOST, region: str = "eastus2"
) -> None:
    monkeypatch.setenv("NS_ANALYTICS_BACKEND", "databricks")
    monkeypatch.setenv("NS_ANALYTICS_REGION", region)
    monkeypatch.setenv("NS_ANALYTICS_DATABRICKS_HOST", host)
    monkeypatch.setenv("NS_ANALYTICS_DATABRICKS_WAREHOUSE_ID", WAREHOUSE)
    monkeypatch.setenv("NS_ANALYTICS_DATABRICKS_CATALOG", "main")
    monkeypatch.setenv("NS_ANALYTICS_DATABRICKS_SCHEMA", "ns")


async def _token() -> str:
    return REGISTRY_TOKEN


def _compose(handler: Any = None, settings: Settings | None = None) -> tuple[Composed, list[Any]]:
    seen: list[httpx.Request] = []
    backends: dict[str, object] = {}
    if handler is not None:

        def wrapped(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return handler(request)

        backends["analytics_http_client"] = httpx.AsyncClient(
            transport=httpx.MockTransport(wrapped), base_url=f"https://{HOST}"
        )
        backends["analytics_token_provider"] = _token
    composed = compose(
        CompositionOverrides(backends=backends),
        builders=(analytics_builder.BUILDER,),
        settings=settings,
    )
    return composed, seen


def _ok_one_row(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "statement_id": "s1",
            "status": {"state": "SUCCEEDED"},
            "result": {"data_array": [["1"]]},
        },
    )


def test_component_is_optional_and_builder_registered_last() -> None:
    assert "analytics_adapter" in OPTIONAL_COMPONENTS
    assert default_builders()[-1] is analytics_builder.BUILDER


@pytest.mark.parametrize("value", [None, "none", "NONE"])
def test_unset_or_none_is_disabled(monkeypatch: pytest.MonkeyPatch, value: str | None) -> None:
    if value is not None:
        monkeypatch.setenv("NS_ANALYTICS_BACKEND", value)
    composed, _ = _compose()
    status = composed.registry.get("analytics_adapter")
    assert status.state == "disabled"
    assert not status.blocks_readiness
    assert not hasattr(composed.app.state, "analytics_adapter")


def test_fixture_under_local_builds_the_fixture_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NS_ANALYTICS_BACKEND", "fixture")
    composed, _ = _compose()
    assert composed.registry.get("analytics_adapter").state == "ok"
    assert isinstance(composed.app.state.analytics_adapter, FixtureAnalytics)
    assert isinstance(composed.app.state.analytics_region, str)


def test_fixture_outside_local_fails_with_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NS_ANALYTICS_BACKEND", "fixture")
    settings = Settings(env="dev", cloud=CloudName.COMMERCIAL)
    composed, _ = _compose(settings=settings)
    status = composed.registry.get("analytics_adapter")
    assert status.state == "failed"
    assert status.code == "analytics_fixture_not_local"
    assert not hasattr(composed.app.state, "analytics_adapter")


async def test_databricks_builds_over_the_product_executor(monkeypatch: pytest.MonkeyPatch) -> None:
    _databricks_env(monkeypatch)
    composed, seen = _compose(_ok_one_row)
    assert composed.registry.get("analytics_adapter").state == "ok"
    assert isinstance(composed.app.state.analytics_adapter, DatabricksAnalytics)
    assert composed.app.state.analytics_region == "eastus2"
    assert seen == []  # no network at build time
    assert await composed.app.state.analytics_health() is True
    (request,) = seen
    assert request.headers["authorization"] == f"Bearer {REGISTRY_TOKEN}"
    assert json.loads(request.content)["statement"] == "SELECT 1"


@pytest.mark.parametrize("backend", ["fabric", "synapse"])
def test_tds_backends_report_executor_unavailable(
    monkeypatch: pytest.MonkeyPatch, backend: str
) -> None:
    monkeypatch.setenv("NS_ANALYTICS_BACKEND", backend)
    monkeypatch.setenv("NS_ANALYTICS_REGION", "eastus2")
    composed, seen = _compose(_ok_one_row)
    status = composed.registry.get("analytics_adapter")
    assert (status.state, status.code) == ("failed", "analytics_executor_unavailable")
    assert seen == []
    assert not hasattr(composed.app.state, "analytics_adapter")


def test_government_with_a_commercial_host_never_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _databricks_env(monkeypatch, host=HOST, region="usgovvirginia")
    composed, seen = _compose(_ok_one_row, Settings(cloud=CloudName.GOVERNMENT))
    status = composed.registry.get("analytics_adapter")
    assert status.state == "failed"
    assert status.code == "analytics_config_invalid"
    assert seen == []
    assert not hasattr(composed.app.state, "analytics_adapter")


def test_government_databricks_is_unverified(monkeypatch: pytest.MonkeyPatch) -> None:
    _databricks_env(monkeypatch, host=GOV_HOST, region="usgovvirginia")
    composed, seen = _compose(_ok_one_row, Settings(cloud=CloudName.GOVERNMENT))
    status = composed.registry.get("analytics_adapter")
    # Either the matrix disables it for the region or the token audience is unverified:
    # a failed component with a reason code in both cases, never an adapter.
    assert status.state == "failed"
    assert status.code is not None
    assert seen == []
    assert not hasattr(composed.app.state, "analytics_adapter")


def test_government_region_refused_by_the_profile_keeps_a_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _databricks_env(monkeypatch, host=GOV_HOST, region="usdodcentral")
    composed, _ = _compose(_ok_one_row, Settings(cloud=CloudName.GOVERNMENT))
    status = composed.registry.get("analytics_adapter")
    assert status.state == "failed"
    assert status.code in {"capability_unavailable", "analytics_config_invalid"}


def test_missing_databricks_settings_fail_by_reason_without_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NS_ANALYTICS_BACKEND", "databricks")
    monkeypatch.setenv("NS_ANALYTICS_DATABRICKS_HOST", HOST)
    composed, _ = _compose()
    status = composed.registry.get("analytics_adapter")
    assert (status.state, status.code) == ("failed", "analytics_settings_invalid")
    assert HOST not in repr(status)


def test_unknown_backend_value_is_a_settings_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NS_ANALYTICS_BACKEND", "bigquery")
    composed, _ = _compose()
    status = composed.registry.get("analytics_adapter")
    assert (status.state, status.code) == ("failed", "analytics_settings_invalid")
    assert "bigquery" not in repr(status)


def test_misconfiguration_fails_only_the_analytics_component(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NS_ANALYTICS_BACKEND", "databricks")
    composed, _ = _compose()
    others = [n for n in composed.registry.components if n != "analytics_adapter"]
    assert all(composed.registry.get(n).state != "failed" for n in others)
    assert composed.registry.get("analytics_adapter").state == "failed"
