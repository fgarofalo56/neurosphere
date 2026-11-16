"""CI-oriented hosted smoke (PRP-63 item 1).

A thin wrapper over ``_hosted_demo_smoke.run_smoke`` for the delivery pipeline. It resolves the
frontend and API hosts and the site names from the ``hosted-demo`` deployment outputs, optionally
restarts the frontend site so nginx re-resolves the API upstream, retries the whole smoke a bounded
number of times while the sites warm up, writes a machine-readable result and a Markdown summary
(``$GITHUB_STEP_SUMMARY`` when set) and exits non-zero on any failed check.

It makes no change to Azure other than the optional frontend restart, and needs ``az`` to be
logged in already (the workflow does that with OpenID Connect). It never prints a response body,
token or header value; check details come from ``_hosted_demo_smoke`` and carry statuses only.
Unlike ``hosted_demo.py`` it does not need ``NS_LIVE_APPROVED``: it is read-only apart from the
restart, and the workflow only runs it after the protected environment approved the deploy.

Exit codes: 0 every check passed, 1 a check failed after the last attempt, 2 refused (bad input,
no ``az``, deployment outputs unusable).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _hosted_demo_common as cm
import _hosted_demo_smoke as sm

AZ_TIMEOUT_SECONDS = 300
DEFAULT_ATTEMPTS = 6
DEFAULT_BACKOFF_SECONDS = 20.0
MAX_ATTEMPTS = 20
_GUID = re.compile(r"^[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$")
_RG = re.compile(r"^[A-Za-z0-9._()-]{1,90}$")
_SITE_OUTPUTS = ("frontendSiteName", "apiSiteName", "workersSiteName")


class RefusedError(Exception):
    """Bad input or an unusable environment; nothing was checked."""


@dataclass(frozen=True)
class Targets:
    frontend_host: str
    api_host: str
    frontend_site: str
    sites: tuple[sm.SiteTarget, ...]


def _az_text(res: sm.AzResult) -> str:
    line = (res.stderr or "").strip().splitlines()
    return line[0][:200] if line else f"exit {res.rc}"


def resolve_targets(az: sm.AzRunner, subscription: str, resource_group: str) -> Targets:
    """Read the deployment outputs; raise RefusedError when the hosts are missing."""
    res = az(
        [
            "deployment",
            "group",
            "show",
            "--resource-group",
            resource_group,
            "--subscription",
            subscription,
            "--name",
            cm.DEPLOYMENT_NAME,
            "--query",
            "properties.outputs",
            "--output",
            "json",
        ]
    )
    if res.rc != 0:
        raise RefusedError(f"could not read the deployment outputs: {_az_text(res)}")
    try:
        raw = json.loads(res.stdout or "{}")
    except ValueError as exc:
        raise RefusedError("deployment outputs were not JSON") from exc
    if not isinstance(raw, dict):
        raise RefusedError("deployment outputs were not an object")
    out: dict[str, str] = {}
    for name, body in raw.items():  # pyright: ignore[reportUnknownVariableType]
        value: Any = body.get("value") if isinstance(body, dict) else body  # pyright: ignore[reportUnknownMemberType]
        out[str(name)] = str(value or "")  # pyright: ignore[reportUnknownArgumentType]
    frontend_host = out.get("frontendHostName", "")
    api_host = out.get("apiHostName", "")
    if not frontend_host or not api_host:
        raise RefusedError("deployment outputs lack frontendHostName/apiHostName")
    sites = tuple(
        sm.SiteTarget(name=out[k], resource_group=resource_group)
        for k in _SITE_OUTPUTS
        if out.get(k)
    )
    return Targets(frontend_host, api_host, out.get("frontendSiteName", ""), sites)


def restart_frontend(az: sm.AzRunner, subscription: str, resource_group: str, site: str) -> str:
    """Restart the frontend site (update path step 4); returns a short status line."""
    if not site:
        return "skipped: no frontendSiteName output"
    res = az(
        [
            "webapp",
            "restart",
            "--name",
            site,
            "--resource-group",
            resource_group,
            "--subscription",
            subscription,
        ]
    )
    return "restarted" if res.rc == 0 else f"restart failed: {_az_text(res)}"


def run_with_retries(
    targets: Targets,
    az: sm.AzRunner,
    *,
    attempts: int,
    backoff_seconds: float,
    transport: httpx.BaseTransport | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[sm.SmokeResult, int]:
    """Run the smoke up to ``attempts`` times (sites warm up after a restart); return the last
    result and the number of attempts used. Backoff grows linearly, so the total wait is bounded."""
    attempts = max(1, min(attempts, MAX_ATTEMPTS))
    result = sm.SmokeResult()
    used = 0
    for attempt in range(1, attempts + 1):
        used = attempt
        result = sm.run_smoke(
            frontend_url=f"https://{targets.frontend_host}",
            api_host=targets.api_host,
            sites=targets.sites,
            az_runner=az,
            transport=transport,
        )
        if result.ok:
            break
        if attempt < attempts:
            sleep(backoff_seconds * attempt)
    return result, used


def render_summary(result: sm.SmokeResult, attempts: int, restart: str) -> str:
    lines = [
        "## Hosted smoke",
        "",
        f"Result: **{'PASS' if result.ok else 'FAIL'}** after {attempts} attempt(s). "
        f"Frontend restart: {restart}.",
        "",
        "| check | result | detail |",
        "|---|---|---|",
    ]
    for c in result.checks:
        detail = c.detail.replace("|", "/").replace("\n", " ")
        lines.append(f"| {c.name} | {'pass' if c.passed else 'FAIL'} | {detail} |")
    if not result.checks:
        lines.append("| (none) | FAIL | no checks ran |")
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="PRP-63 hosted smoke for the delivery pipeline.")
    ap.add_argument("--subscription", required=True, help="subscription id")
    ap.add_argument("--resource-group", default=cm.DEFAULT_RG)
    ap.add_argument("--result-json", required=True, help="path of the machine-readable result")
    ap.add_argument("--attempts", type=int, default=DEFAULT_ATTEMPTS)
    ap.add_argument("--backoff-seconds", type=float, default=DEFAULT_BACKOFF_SECONDS)
    ap.add_argument(
        "--restart-frontend",
        action="store_true",
        help="restart the frontend site first so nginx re-resolves the API upstream",
    )
    return ap


class SubprocessAz:
    """The real runner: list args, no shell."""

    def __init__(self, az_path: str) -> None:
        self._az = az_path

    def __call__(self, args: Sequence[str]) -> sm.AzResult:
        proc = subprocess.run(
            [self._az, *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdin=subprocess.DEVNULL,
            timeout=AZ_TIMEOUT_SECONDS,
            check=False,
            shell=False,
        )
        return sm.AzResult(proc.returncode, proc.stdout, proc.stderr)


def main(
    argv: Sequence[str] | None = None,
    *,
    az: sm.AzRunner | None = None,
    transport: httpx.BaseTransport | None = None,
    sleep: Callable[[float], None] = time.sleep,
    env: Mapping[str, str] | None = None,
) -> int:
    environ = os.environ if env is None else env
    args = build_parser().parse_args(argv)
    try:
        if not _GUID.match(args.subscription):
            raise RefusedError("--subscription is not a GUID")
        if not _RG.match(args.resource_group):
            raise RefusedError("--resource-group has unexpected characters")
        if az is None:
            az_path = shutil.which("az")
            if not az_path:
                raise RefusedError("the Azure CLI (az) was not found on PATH")
            az = SubprocessAz(az_path)
        targets = resolve_targets(az, args.subscription, args.resource_group)
        restart = "not requested"
        if args.restart_frontend:
            restart = restart_frontend(
                az, args.subscription, args.resource_group, targets.frontend_site
            )
        result, used = run_with_retries(
            targets,
            az,
            attempts=args.attempts,
            backoff_seconds=args.backoff_seconds,
            transport=transport,
            sleep=sleep,
        )
    except RefusedError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2

    body = result.to_dict()
    body.update(attempts=used, frontend_restart=restart)
    out_path = Path(args.result_json)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary = render_summary(result, used, restart)
    summary_path = environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as handle:
            handle.write(summary)
    for c in result.checks:
        print(f"{'ok' if c.passed else 'FAILED'}: {c.name}: {c.detail}")
    print(f"{'PASS' if result.ok else 'FAIL'}: {used} attempt(s); result at {out_path}")
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
