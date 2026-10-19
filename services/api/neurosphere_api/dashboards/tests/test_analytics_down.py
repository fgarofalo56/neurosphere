"""The endpoint serves from hot aggregates whatever the analytics adapter is doing. A stopped,
raising, hanging or absent adapter changes the reported state, never the status code, and no
reason string names a vendor."""

from typing import Any

import pytest
from neurosphere_core.aggregates import format_bucket

from neurosphere_api.dashboards import analytics as analytics_module
from neurosphere_api.dashboards.analytics import AnalyticsProbe
from neurosphere_api.dashboards.tests.support import (
    ALICE,
    FINANCE,
    NOW,
    cost_point,
    make_api,
)

VENDORS = ("fabric", "synapse", "databricks", "microsoft", "azure")


class Adapter:
    backend = "fixture"
    cloud = "commercial"


class RaisingHealth:
    async def __call__(self) -> bool:
        raise ConnectionError("endpoint refused")


async def _stopped() -> bool:
    return False


async def _healthy() -> bool:
    return True


async def _hangs() -> bool:
    import asyncio

    await asyncio.Event().wait()
    return True


def _seed_fresh(api: Any) -> None:
    api.seed(cost_point(FINANCE, 1, "8.00"))
    api.set_status(watermark=format_bucket(NOW), billing=format_bucket(NOW))


def _assert_served(response: Any) -> dict[str, Any]:
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["series"][0]["total"]["value"] == 8.0  # from aggregates
    return body


def _assert_no_vendor(body: dict[str, Any]) -> None:
    reason = (body["analytics"]["reason"] or "").lower()
    assert not any(v in reason for v in VENDORS)


def test_absent_adapter_is_disabled_with_a_reason() -> None:
    api = make_api()
    _seed_fresh(api)
    body = _assert_served(api.get(ALICE, FINANCE, "cost"))  # nothing on app.state at all
    assert body["analytics"]["state"] == "disabled"
    assert body["analytics"]["reason"]
    _assert_no_vendor(body)


def test_explicit_none_probe_is_disabled() -> None:
    api = make_api()
    _seed_fresh(api)
    api.use_analytics(AnalyticsProbe())
    body = _assert_served(api.get(ALICE, FINANCE, "cost"))
    assert body["analytics"]["state"] == "disabled"


def test_stopped_adapter_is_disabled_with_a_reason() -> None:
    api = make_api()
    _seed_fresh(api)
    api.use_analytics(AnalyticsProbe(adapter=Adapter(), health=_stopped))
    body = _assert_served(api.get(ALICE, FINANCE, "cost"))
    assert body["analytics"]["state"] == "disabled"
    assert body["analytics"]["reason"]
    _assert_no_vendor(body)


@pytest.mark.parametrize("metric", ["cost", "latency", "errors", "coverage"])
def test_raising_adapter_is_delayed_never_5xx(metric: str) -> None:
    api = make_api()
    _seed_fresh(api)
    api.use_analytics(AnalyticsProbe(adapter=Adapter(), health=RaisingHealth()))
    response = api.get(ALICE, FINANCE, metric)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["analytics"]["state"] == "delayed"
    assert body["analytics"]["reason"]
    _assert_no_vendor(body)


def test_hanging_adapter_times_out_to_delayed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(analytics_module, "HEALTH_TIMEOUT_SECONDS", 0.05)
    api = make_api()
    _seed_fresh(api)
    api.use_analytics(AnalyticsProbe(adapter=Adapter(), health=_hangs))
    body = _assert_served(api.get(ALICE, FINANCE, "cost"))
    assert body["analytics"]["state"] == "delayed"


def test_attribute_access_that_raises_does_not_break_the_endpoint() -> None:
    class Hostile:
        backend = "fixture"
        cloud = "commercial"

        @property
        def health(self) -> Any:
            raise RuntimeError("boom")

    api = make_api()
    _seed_fresh(api)
    api.use_analytics(AnalyticsProbe(adapter=Hostile()))
    response = api.get(ALICE, FINANCE, "cost")
    assert response.status_code == 200, response.text
    assert response.json()["analytics"]["state"] in ("disabled", "delayed")


def test_healthy_adapter_with_fresh_aggregates_is_available() -> None:
    api = make_api()
    _seed_fresh(api)
    api.use_analytics(AnalyticsProbe(adapter=Adapter(), health=_healthy))
    body = _assert_served(api.get(ALICE, FINANCE, "cost"))
    assert body["analytics"] == {"state": "available", "reason": None}
    assert body["freshness"]["lag_seconds"] == 0.0
    assert body["freshness"]["billing_source_freshness"] == format_bucket(NOW)


def test_lagging_aggregates_report_delayed_even_with_a_healthy_adapter() -> None:
    api = make_api()
    api.seed(cost_point(FINANCE, 1, "8.00"))
    api.set_status(watermark="2027-01-15T06:00:00Z")  # 2.5h behind NOW
    api.use_analytics(AnalyticsProbe(adapter=Adapter(), health=_healthy))
    body = _assert_served(api.get(ALICE, FINANCE, "cost"))
    assert body["analytics"]["state"] == "delayed"
    assert body["freshness"]["lag_seconds"] == 9000.0


def test_backend_disabled_by_the_capability_matrix_is_disabled() -> None:
    class Gov:
        backend = "databricks"
        cloud = "government"

    api = make_api()
    _seed_fresh(api)
    # An unverifiable region fails closed to disabled, without naming the backend.
    api.use_analytics(AnalyticsProbe(adapter=Gov(), region="not-a-region", health=_healthy))
    body = _assert_served(api.get(ALICE, FINANCE, "cost"))
    assert body["analytics"]["state"] == "disabled"
    _assert_no_vendor(body)


def test_reader_failure_is_503_not_a_leak() -> None:
    class Broken:
        async def query(self, *args: object, **kw: object) -> object:
            raise RuntimeError("cosmos exploded: secret-detail")

        async def status(self, customer_id: str) -> None:
            return None

    api = make_api()
    api.use_reader(Broken())
    response = api.get(ALICE, FINANCE, "cost")
    assert response.status_code == 503
    assert "secret-detail" not in response.text
