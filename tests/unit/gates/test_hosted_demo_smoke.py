"""PRP-32 item 6: _hosted_demo_smoke.py against httpx.MockTransport and a fake `az` runner."""

from __future__ import annotations

import importlib.util
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType

import httpx
import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "gates" / "_hosted_demo_smoke.py"
FRONTEND = "https://nsdemo-ui.azurewebsites.net"
API_HOST = "nsdemo-api.azurewebsites.net"
TENANT = "11111111-1111-4111-8111-111111111111"
CLIENT = "22222222-2222-4222-8222-222222222222"
ZERO = "00000000-0000-0000-0000-000000000000"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("hosted_demo_smoke_under_test", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


smoke = _load()


def _config(**over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "cloud": "commercial",
        "tenantId": TENANT,
        "clientId": CLIENT,
        "apiBaseUrl": "/",
        "apiScope": f"api://{CLIENT}/access_as_user",
    }
    base.update(over)
    return base


class Edge:
    """Mutable description of what the fake deployment answers."""

    def __init__(self) -> None:
        self.config: dict[str, object] = _config()
        self.config_cache = "no-store"
        self.root = 200
        self.me = 401
        self.readyz = 404
        self.api_direct: int | None = 403  # None = connection failure

    def handler(self, request: httpx.Request) -> httpx.Response:
        host = request.url.host
        path = request.url.path
        if host == API_HOST:
            if self.api_direct is None:
                raise httpx.ConnectError("refused", request=request)
            return httpx.Response(self.api_direct)
        if path == "/":
            return httpx.Response(self.root)
        if path == "/config.json":
            return httpx.Response(
                200, json=self.config, headers={"Cache-Control": self.config_cache}
            )
        if path == "/api/v1/me/domains":
            return httpx.Response(self.me)
        if path == "/readyz":
            return httpx.Response(self.readyz)
        return httpx.Response(404)


class FakeAz:
    def __init__(self, state: str = "Running", health: float | None = 100.0) -> None:
        self.state = state
        self.health = health
        self.calls: list[list[str]] = []

    def __call__(self, args: Sequence[str]) -> object:
        self.calls.append(list(args))
        if args[:2] == ["webapp", "show"]:
            out = {
                "state": self.state,
                "id": "/subscriptions/s/sites/" + args[args.index("-n") + 1],
            }
            return smoke.AzResult(0, json.dumps(out), "")
        data = [] if self.health is None else [{"average": 100.0}, {"average": self.health}]
        body = {"value": [{"timeseries": [{"data": data}]}]}
        return smoke.AzResult(0, json.dumps(body), "")


SITES = [smoke.SiteTarget(n, "rg-demo") for n in ("api", "workers", "ui")]


def _run(edge: Edge, az: FakeAz | None = None):
    return smoke.run_smoke(
        frontend_url=FRONTEND,
        api_host=API_HOST,
        sites=SITES,
        az_runner=az or FakeAz(),
        transport=httpx.MockTransport(edge.handler),
    )


def _failed(result) -> set[str]:
    return {c.name for c in result.failures}


def test_all_checks_pass_on_the_expected_responses() -> None:
    result = _run(Edge())
    assert result.ok, result.failures
    assert len(result.checks) == 5 + 2 * len(SITES)


def test_api_host_connection_failure_counts_as_refused() -> None:
    edge = Edge()
    edge.api_direct = None
    assert _run(edge).ok


def test_api_host_200_fails() -> None:
    edge = Edge()
    edge.api_direct = 200
    assert _failed(_run(edge)) == {"api-host-refuses-direct"}


def test_zero_guid_in_config_fails() -> None:
    edge = Edge()
    edge.config = _config(tenantId=ZERO)
    assert _failed(_run(edge)) == {"frontend-config-json"}


@pytest.mark.parametrize("base", ["https://nsdemo-api.azurewebsites.net/", "", "/api", "//x"])
def test_apibaseurl_other_than_slash_fails(base: str) -> None:
    edge = Edge()
    edge.config = _config(apiBaseUrl=base)
    assert _failed(_run(edge)) == {"frontend-config-json"}


def test_missing_key_fails() -> None:
    edge = Edge()
    del edge.config["apiScope"]
    assert _failed(_run(edge)) == {"frontend-config-json"}


def test_missing_no_store_fails() -> None:
    edge = Edge()
    edge.config_cache = "public, max-age=60"
    assert _failed(_run(edge)) == {"frontend-config-json"}


def test_unauthenticated_200_instead_of_401_fails() -> None:
    edge = Edge()
    edge.me = 200
    assert _failed(_run(edge)) == {"api-unauthenticated-401"}


def test_readyz_200_fails() -> None:
    edge = Edge()
    edge.readyz = 200
    assert _failed(_run(edge)) == {"readyz-not-proxied"}


def test_frontend_root_not_200_fails() -> None:
    edge = Edge()
    edge.root = 502
    assert _failed(_run(edge)) == {"frontend-root"}


def test_site_not_running_fails() -> None:
    result = _run(Edge(), FakeAz(state="Stopped"))
    assert _failed(result) == {f"site-running:{s.name}" for s in SITES}


@pytest.mark.parametrize("health", [0.0, None])
def test_unhealthy_or_missing_metric_fails(health: float | None) -> None:
    result = _run(Edge(), FakeAz(health=health))
    assert _failed(result) == {f"site-health:{s.name}" for s in SITES}


def test_az_failure_is_a_failed_check_not_an_exception() -> None:
    def broken(args: Sequence[str]) -> object:
        return smoke.AzResult(1, "", "boom")

    result = _run(Edge(), broken)  # type: ignore[arg-type]
    assert not result.ok
    assert f"site-running:{SITES[0].name}" in _failed(result)


def test_metric_call_uses_a_supported_grain_and_the_metrics_flag() -> None:
    az = FakeAz()
    _run(Edge(), az)
    calls = [c for c in az.calls if c[:3] == ["monitor", "metrics", "list"]]
    assert len(calls) == len(SITES)
    for call in calls:
        assert "--metrics" in call
        assert "--metric" not in call
        assert call[call.index("--metrics") + 1] == "HealthCheckStatus"
        assert call[call.index("--interval") + 1] == "PT5M"
        assert call[call.index("--offset") + 1] == "1h"


def test_metric_az_error_is_reported_scrubbed_not_as_no_datapoints() -> None:
    guid = "33333333-3333-4333-8333-333333333333"

    def az(args: Sequence[str]) -> object:
        if args[:2] == ["webapp", "show"]:
            shown = {"state": "Running", "id": "/subscriptions/s/x"}
            return smoke.AzResult(0, json.dumps(shown), "")
        err = f"ERROR: (BadRequest) bad grain {guid} at https://management.example/x\nsecond line"
        return smoke.AzResult(1, "", err)

    result = _run(Edge(), az)  # type: ignore[arg-type]
    health = [c for c in result.checks if c.name.startswith("site-health:")]
    assert health and all(not c.passed for c in health)
    for check in health:
        assert "BadRequest" in check.detail
        assert "no HealthCheckStatus datapoints" not in check.detail
        assert "second line" not in check.detail
        assert guid not in check.detail
        assert "https://" not in check.detail


def test_api_host_equal_to_frontend_host_is_rejected() -> None:
    result = smoke.run_smoke(
        frontend_url=FRONTEND,
        api_host="nsdemo-ui.azurewebsites.net",
        sites=[],
        az_runner=FakeAz(),
        transport=httpx.MockTransport(Edge().handler),
    )
    assert not result.ok


def test_results_carry_no_ids_or_urls() -> None:
    blob = json.dumps(_run(Edge()).to_dict())
    for secret in (TENANT, CLIENT):
        assert secret not in blob
