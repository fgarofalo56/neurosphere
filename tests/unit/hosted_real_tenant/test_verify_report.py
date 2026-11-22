"""verify: per-source PASS/FAIL/OPEN from a fake hosted API; retry bound; privacy of evidence."""

from __future__ import annotations

import importlib.util
import json
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from types import ModuleType
from typing import Any
from urllib.parse import urlsplit

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "gates" / "hosted_real_tenant.py"
HOST = "api-fake.example.net"
DOMAIN = "commercial:fakecust:domain:fake-domain:alpha"
ENV = {"NS_LIVE_APPROVED": "1", "NS_SANDBOX_HOSTED_DEPLOYMENT_ID": "fake-deploy"}
TOKEN_VALUE = "fake-bearer-value"


def load() -> ModuleType:
    name = "hosted_real_tenant_under_test"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def registration(tmp_path: Path, **extra: object) -> Path:
    doc = {
        "schema": 1,
        "deployment_id": "fake-deploy",
        "cloud": "AzureCloud",
        "api_host": HOST,
        "customer_id": "fakecust",
        "data_mode": "real-tenant",
        **extra,
    }
    path = tmp_path / "registration.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def az_ok(args: Sequence[str]) -> object:
    mod = load()
    if list(args)[:2] == ["cloud", "show"]:
        return mod.AzResult(0, "AzureCloud\n")
    return mod.AzResult(0, TOKEN_VALUE + "\n")


def states(**by_source: str) -> dict[str, Any]:
    return {"sources": [{"source": k, "state": v} for k, v in by_source.items()]}


class FakeApi:
    def __init__(
        self,
        *,
        status: Callable[[], dict[str, Any]],
        entities: list[dict[str, Any]] | None = None,
        gateways: list[dict[str, Any]] | None = None,
        billing_lines: int = 0,
        status_code: int = 200,
    ) -> None:
        self.status = status
        self.entities = entities or []
        self.gateways = gateways or []
        self.billing_lines = billing_lines
        self.status_code = status_code
        self.urls: list[str] = []
        self.bearers: set[str] = set()
        # Azure Monitor AI row (PRP-141): admin status and latency dashboard, unreadable by default.
        self.admin_status: tuple[int, dict[str, Any]] = (404, {})
        self.dashboard: tuple[int, dict[str, Any]] = (404, {})

    def __call__(self, url: str, bearer: str) -> object:
        mod = load()
        self.bearers.add(bearer)
        self.urls.append(url)
        path = urlsplit(url).path
        if path == "/api/v1/sources/status":
            return mod.HttpResponse(self.status_code, self.status())
        if path == "/api/v1/admin/sources/status":
            return mod.HttpResponse(*self.admin_status)
        if path.startswith("/api/v1/dashboards/domains/"):
            return mod.HttpResponse(*self.dashboard)
        if path == "/api/v1/me/domains":
            return mod.HttpResponse(200, {"items": [{"domain_id": DOMAIN}]})
        if path == "/api/v1/catalog/entities":
            return mod.HttpResponse(200, {"items": self.entities, "next_cursor": None})
        if path.endswith("/gateways"):
            return mod.HttpResponse(200, {"items": self.gateways})
        if path.startswith("/api/v1/reconciliation/domains/"):
            lines = [{"source": "billing"}] * self.billing_lines + [{"source": "gateway"}]
            return mod.HttpResponse(200, {"sources": lines})
        raise AssertionError(f"unexpected url path {path}")


def foundry_entity(n: int) -> dict[str, Any]:
    return {
        "id": f"commercial:fakecust:foundry:agent:a{n}",
        "attributes": {"discovered_from": "foundry"},
    }


def verify(
    tmp_path: Path,
    api: FakeApi,
    *extra: str,
    sleep: Callable[[float], None] | None = None,
    clock: Callable[[], float] | None = None,
    env: dict[str, str] | None = None,
    **reg: object,
) -> tuple[int, dict[str, Any]]:
    ev = tmp_path / "ev"
    argv = [
        "verify",
        "--registration",
        str(registration(tmp_path, **reg)),
        "--api-audience",
        "fake-audience",
        "--evidence-dir",
        str(ev),
        *extra,
    ]
    code = load().main(
        argv,
        env=env or ENV,
        az_runner=az_ok,
        http=api,
        sleep=sleep or (lambda _s: None),
        clock=clock,
        today="2026-11-21",
    )
    path = ev / "2026-11-21-verify.json"
    return code, json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def test_connected_sources_pass_and_monitor_is_always_open(tmp_path: Path) -> None:
    api = FakeApi(
        status=lambda: states(
            foundry="connected", gateway="connected", billing="connected", azure_monitor="connected"
        ),
        entities=[foundry_entity(1), foundry_entity(2)],
        gateways=[{"poll_status": "ok"}],
        billing_lines=2,
    )
    code, doc = verify(tmp_path, api)
    assert code == 0
    results = {k: v["result"] for k, v in doc["sources"].items()}
    assert results == {
        "foundry": "PASS",
        "gateway": "PASS",
        "billing": "PASS",
        "azure_monitor": "OPEN",
    }
    assert doc["sources"]["azure_monitor"]["reason"] == "status_unavailable"
    assert doc["sources"]["foundry"]["counts"] == {"foundry_entities": 2}
    assert doc["synthetic"]["result"] == "PASS"
    assert doc["overall"] == "OPEN"
    assert api.bearers == {TOKEN_VALUE}


def test_not_connected_source_is_open_never_pass(tmp_path: Path) -> None:
    api = FakeApi(
        status=lambda: states(
            foundry="not_connected", gateway="not_connected", billing="not_connected"
        ),
        entities=[foundry_entity(1)],  # data exists, but the source is not connected
        gateways=[{"poll_status": "ok"}],
        billing_lines=3,
    )
    _code, doc = verify(tmp_path, api)
    for name in ("foundry", "gateway", "billing"):
        assert doc["sources"][name]["result"] == "OPEN"
        assert doc["sources"][name]["reason"] == "source_not_connected"


def test_connected_without_data_is_open(tmp_path: Path) -> None:
    api = FakeApi(status=lambda: states(foundry="connected_no_data", billing="connected"))
    _code, doc = verify(tmp_path, api)
    assert doc["sources"]["foundry"]["reason"] == "no_data_yet"
    assert doc["sources"]["billing"]["result"] == "OPEN"


def test_gateway_poll_failed_is_fail(tmp_path: Path) -> None:
    api = FakeApi(status=lambda: states(gateway="connected"), gateways=[{"poll_status": "failed"}])
    code, doc = verify(tmp_path, api)
    assert doc["sources"]["gateway"]["result"] == "FAIL"
    assert doc["sources"]["gateway"]["reason"] == "poll_failed"
    assert code == 1


def test_synthetic_records_fail_the_report(tmp_path: Path) -> None:
    api = FakeApi(
        status=lambda: states(foundry="connected"),
        entities=[foundry_entity(1), {"id": "commercial:synthco:sandbox:agent:x"}],
    )
    code, doc = verify(tmp_path, api)
    assert doc["synthetic"]["result"] == "FAIL"
    assert doc["synthetic"]["counts"]["synthetic_records"] == 1
    assert doc["overall"] == "FAIL" and code == 1


def test_status_endpoint_unavailable_makes_every_source_open(tmp_path: Path) -> None:
    api = FakeApi(status=lambda: {}, status_code=403, entities=[foundry_entity(1)])
    _code, doc = verify(tmp_path, api)
    assert {v["reason"] for k, v in doc["sources"].items() if k != "azure_monitor"} == {
        "status_unavailable"
    }
    assert doc["api_status"]["sources_status"] == 403


def test_role_propagation_retry_is_bounded_and_recovers(tmp_path: Path) -> None:
    now = [0.0]
    slept: list[float] = []

    def sleep(seconds: float) -> None:
        slept.append(seconds)
        now[0] += seconds

    answers = [states(foundry="failing"), states(foundry="failing"), states(foundry="connected")]

    def status() -> dict[str, Any]:
        return answers.pop(0) if len(answers) > 1 else answers[0]

    api = FakeApi(status=status, entities=[foundry_entity(1)])
    _code, doc = verify(tmp_path, api, sleep=sleep, clock=lambda: now[0])
    assert doc["sources"]["foundry"]["result"] == "PASS"
    assert slept == [30, 30]
    assert doc["propagation_waited_seconds"] == 60


def test_retry_stops_at_the_bound_and_reports_fail(tmp_path: Path) -> None:
    now = [0.0]
    slept: list[float] = []

    def sleep(seconds: float) -> None:
        slept.append(seconds)
        now[0] += seconds

    api = FakeApi(status=lambda: states(foundry="failing"))
    code, doc = verify(
        tmp_path,
        api,
        "--propagation-seconds",
        "100",
        "--retry-interval-seconds",
        "40",
        sleep=sleep,
        clock=lambda: now[0],
    )
    assert slept == [40, 40]  # a third sleep would pass the 100 second bound
    assert doc["sources"]["foundry"]["result"] == "FAIL"
    assert code == 1


def test_verify_refuses_without_approval_government_and_local_host(tmp_path: Path) -> None:
    api = FakeApi(status=lambda: states())
    cases: tuple[tuple[dict[str, str], dict[str, Any]], ...] = (
        ({k: v for k, v in ENV.items() if k != "NS_LIVE_APPROVED"}, {}),
        ({**ENV, "NS_CLOUD": "government"}, {}),
        (ENV, {"cloud": "AzureUSGovernment"}),
        (ENV, {"api_host": "localhost"}),
        (ENV, {"api_host": "127.0.0.1"}),
    )
    for env, reg in cases:
        code, _doc = verify(tmp_path, api, env=env, **reg)
        assert code == 2
    assert api.urls == []


def test_verify_refuses_api_host_that_is_not_the_registered_one(tmp_path: Path) -> None:
    api = FakeApi(status=lambda: states())
    code, _doc = verify(tmp_path, api, "--api-host", "other.example.net")
    assert code == 2 and api.urls == []


@pytest.mark.parametrize("forbidden", [HOST, DOMAIN, TOKEN_VALUE, "fakecust", "/subscriptions"])
def test_evidence_holds_no_host_id_or_token(tmp_path: Path, forbidden: str) -> None:
    api = FakeApi(
        status=lambda: states(foundry="connected"),
        entities=[foundry_entity(1)],
        gateways=[{"poll_status": "ok"}],
    )
    verify(tmp_path, api)
    text = (tmp_path / "ev" / "2026-11-21-verify.json").read_text(encoding="utf-8")
    assert forbidden not in text


class PagedApi(FakeApi):
    """Catalog that always answers with a continuation cursor (never ends)."""

    def __init__(self, *, pages: list[list[dict[str, Any]]], **kw: Any) -> None:
        super().__init__(**kw)
        self.pages = pages
        self.catalog_calls = 0

    def __call__(self, url: str, bearer: str) -> object:
        if urlsplit(url).path == "/api/v1/catalog/entities":
            mod = load()
            self.urls.append(url)
            page = self.pages[min(self.catalog_calls, len(self.pages) - 1)]
            self.catalog_calls += 1
            return mod.HttpResponse(200, {"items": page, "next_cursor": "more"})
        return super().__call__(url, bearer)


def test_truncated_scan_with_nothing_found_is_open_not_pass(tmp_path: Path) -> None:
    api = PagedApi(
        pages=[[{"id": "commercial:fakecust:agent:x"}]],
        status=lambda: states(foundry="connected"),
    )
    code, doc = verify(tmp_path, api)
    assert api.catalog_calls == 5
    assert doc["catalog_truncated"] is True
    assert doc["synthetic"]["result"] == "OPEN"
    assert doc["synthetic"]["reason"] == "catalog_scan_truncated"
    assert doc["sources"]["foundry"]["result"] == "OPEN"
    assert doc["sources"]["foundry"]["reason"] == "catalog_scan_truncated"
    assert code == 0


def test_truncated_scan_with_a_synthetic_record_still_fails(tmp_path: Path) -> None:
    api = PagedApi(
        pages=[[{"id": "commercial:synthco:sandbox:agent:x"}]],
        status=lambda: states(foundry="connected"),
    )
    code, doc = verify(tmp_path, api)
    assert doc["synthetic"]["result"] == "FAIL"
    assert code == 1


def test_truncated_scan_with_a_foundry_entity_may_pass(tmp_path: Path) -> None:
    api = PagedApi(pages=[[foundry_entity(1)]], status=lambda: states(foundry="connected"))
    _code, doc = verify(tmp_path, api)
    assert doc["sources"]["foundry"]["result"] == "PASS"
    assert doc["synthetic"]["reason"] == "catalog_scan_truncated"


def test_complete_scan_is_not_flagged_truncated(tmp_path: Path) -> None:
    api = FakeApi(status=lambda: states(foundry="connected"), entities=[foundry_entity(1)])
    _code, doc = verify(tmp_path, api)
    assert doc["catalog_truncated"] is False
    assert doc["synthetic"]["reason"] == "no_synthetic_records"
