"""Post-deploy smoke for the hosted demo (PRP-32 item 6): pure logic, no I/O of its own.

HTTP goes through ``httpx`` with an injectable transport; app state and the ``HealthCheckStatus``
metric go through an injectable ``az`` runner. Nothing here prints or returns a response body, a
token or a header value other than ``Cache-Control``; results carry statuses and short reasons only.
``hosted_demo.py smoke`` wires this to the real transport and the real ``az``.
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, NamedTuple, Protocol
from urllib.parse import urlsplit

import httpx

REQUEST_TIMEOUT_SECONDS = 20.0
CONFIG_KEYS = ("cloud", "tenantId", "clientId", "apiBaseUrl", "apiScope")
# HealthCheckStatus is reported as a percentage of healthy instances; anything below this is not.
HEALTHY_MIN = 99.0
# Azure Monitor accepts only 5 minute, 1 hour and 1 day grains for HealthCheckStatus. The offset
# uses az's ``##d##h`` format.
METRIC_INTERVAL = "PT5M"
METRIC_WINDOW = "1h"


class AzResult(NamedTuple):
    rc: int
    stdout: str
    stderr: str


class AzRunner(Protocol):
    """Runs one `az` invocation (arguments exclude the `az` executable itself)."""

    def __call__(self, args: Sequence[str]) -> AzResult: ...


@dataclass(frozen=True)
class SiteTarget:
    """One App Service site to inspect."""

    name: str
    resource_group: str


@dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    detail: str


@dataclass
class SmokeResult:
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.checks) and all(c.passed for c in self.checks)

    @property
    def failures(self) -> list[CheckResult]:
        return [c for c in self.checks if not c.passed]

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "checks": [
                {"name": c.name, "passed": c.passed, "detail": c.detail} for c in self.checks
            ],
        }

    def _add(self, name: str, passed: bool, detail: str) -> None:
        self.checks.append(CheckResult(name, passed, detail))


def _origin(value: str) -> str:
    """Normalise a frontend URL to ``https://host[:port]`` (no path)."""
    parts = urlsplit(value if "//" in value else f"https://{value}")
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise ValueError("frontend_url must be an http(s) URL with a host")
    return f"{parts.scheme}://{parts.netloc}"


def _hostname(value: str) -> str:
    parts = urlsplit(value if "//" in value else f"//{value}")
    if not parts.hostname:
        raise ValueError("a hostname is required")
    return parts.hostname.lower()


def _is_real_guid(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = uuid.UUID(value)
    except ValueError:
        return False
    return parsed.int != 0


def _check_frontend_root(client: httpx.Client, origin: str, out: SmokeResult) -> None:
    name = "frontend-root"
    try:
        status = client.get(f"{origin}/").status_code
    except httpx.HTTPError as exc:
        out._add(name, False, f"request failed: {type(exc).__name__}")
        return
    out._add(name, status == 200, f"GET / -> {status}")


def _config_problems(response: httpx.Response) -> list[str]:
    problems: list[str] = []
    if response.status_code != 200:
        return [f"status {response.status_code}, expected 200"]
    if "no-store" not in response.headers.get("cache-control", "").lower():
        problems.append("Cache-Control lacks no-store")
    try:
        body = response.json()
    except ValueError:
        return [*problems, "body is not JSON"]
    if not isinstance(body, dict):
        return [*problems, "body is not a JSON object"]
    missing = [k for k in CONFIG_KEYS if k not in body]
    if missing:
        problems.append(f"missing keys: {', '.join(missing)}")
    for key in ("tenantId", "clientId"):
        if key in body and not _is_real_guid(body[key]):
            problems.append(f"{key} is not a non-zero GUID")
    if "apiBaseUrl" in body and body["apiBaseUrl"] != "/":
        problems.append('apiBaseUrl is not exactly "/"')
    return problems


def _check_config(client: httpx.Client, origin: str, out: SmokeResult) -> None:
    name = "frontend-config-json"
    try:
        response = client.get(f"{origin}/config.json")
    except httpx.HTTPError as exc:
        out._add(name, False, f"request failed: {type(exc).__name__}")
        return
    problems = _config_problems(response)
    out._add(name, not problems, "; ".join(problems) if problems else "ok")


def _check_status(
    client: httpx.Client,
    out: SmokeResult,
    *,
    name: str,
    url: str,
    label: str,
    accept: Callable[[int], bool],
    expected: str,
) -> None:
    try:
        status = client.get(url).status_code
    except httpx.HTTPError as exc:
        out._add(name, False, f"request failed: {type(exc).__name__}")
        return
    out._add(name, accept(status), f"{label} -> {status}, expected {expected}")


def _check_api_refused(client: httpx.Client, api_host: str, out: SmokeResult) -> None:
    name = "api-host-refuses-direct"
    try:
        status = client.get(f"https://{api_host}/healthz").status_code
    except httpx.HTTPError as exc:
        out._add(name, True, f"unreachable ({type(exc).__name__}), treated as refused")
        return
    out._add(name, status == 403, f"direct API host -> {status}, expected 403 or unreachable")


def _latest_average(metrics: object) -> float | None:
    if not isinstance(metrics, dict):
        return None
    latest: float | None = None
    for metric in metrics.get("value", []):
        for series in metric.get("timeseries", []):
            for point in series.get("data", []):
                value = point.get("average")
                if isinstance(value, int | float):
                    latest = float(value)
    return latest


_GUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_URL_OR_ID = re.compile(r"https?://\S+|/subscriptions/\S+")


def _az_error_line(stderr: str) -> str:
    """First non-empty line of an az error, with ids and URLs removed and length bounded."""
    first = next((ln.strip() for ln in stderr.splitlines() if ln.strip()), "no error text")
    first = _URL_OR_ID.sub("<redacted>", first)
    first = _GUID.sub("<guid>", first)
    return first[:200]


def _json(result: AzResult) -> object | None:
    if result.rc != 0:
        return None
    try:
        return json.loads(result.stdout)
    except ValueError:
        return None


def _check_site(az_runner: AzRunner, site: SiteTarget, out: SmokeResult) -> None:
    state_name = f"site-running:{site.name}"
    health_name = f"site-health:{site.name}"
    shown = _json(
        az_runner(
            [
                "webapp",
                "show",
                "-g",
                site.resource_group,
                "-n",
                site.name,
                "--query",
                "{state:state,id:id}",
                "-o",
                "json",
            ]
        )
    )
    if not isinstance(shown, dict):
        out._add(state_name, False, "az webapp show failed")
        out._add(health_name, False, "skipped: site not readable")
        return
    state = shown.get("state")
    out._add(state_name, state == "Running", f"state {state!r}, expected 'Running'")
    resource_id = shown.get("id")
    if not isinstance(resource_id, str) or not resource_id:
        out._add(health_name, False, "site has no resource id")
        return
    metrics_result = az_runner(
        [
            "monitor",
            "metrics",
            "list",
            "--resource",
            resource_id,
            "--metrics",
            "HealthCheckStatus",
            "--interval",
            METRIC_INTERVAL,
            "--aggregation",
            "Average",
            "--offset",
            METRIC_WINDOW,
            "-o",
            "json",
        ]
    )
    if metrics_result.rc != 0:
        out._add(
            health_name,
            False,
            f"az monitor metrics list failed: {_az_error_line(metrics_result.stderr)}",
        )
        return
    value = _latest_average(_json(metrics_result))
    if value is None:
        out._add(health_name, False, "no HealthCheckStatus datapoints")
        return
    out._add(health_name, value >= HEALTHY_MIN, f"latest HealthCheckStatus {value:g}")


def run_smoke(
    *,
    frontend_url: str,
    api_host: str,
    sites: Sequence[SiteTarget],
    az_runner: AzRunner,
    transport: httpx.BaseTransport | None = None,
) -> SmokeResult:
    """Run every unauthenticated and control-plane check; never raises on a failed check."""
    origin = _origin(frontend_url)
    api = _hostname(api_host)
    out = SmokeResult()
    if api == (urlsplit(origin).hostname or "").lower():
        out._add("inputs", False, "api_host equals the frontend host")
        return out
    with httpx.Client(
        transport=transport, timeout=REQUEST_TIMEOUT_SECONDS, follow_redirects=False
    ) as client:
        _check_frontend_root(client, origin, out)
        _check_config(client, origin, out)
        _check_status(
            client,
            out,
            name="api-unauthenticated-401",
            url=f"{origin}/api/v1/me/domains",
            label="GET /api/v1/me/domains",
            accept=lambda s: s == 401,
            expected="401",
        )
        _check_status(
            client,
            out,
            name="readyz-not-proxied",
            url=f"{origin}/readyz",
            label="GET /readyz",
            accept=lambda s: s != 200,
            expected="anything but 200",
        )
        _check_api_refused(client, api, out)
    for site in sites:
        _check_site(az_runner, site, out)
    return out
