"""PRP-29 item 6: make the Entra API app registration usable for real local sign-in.

Operator-run. Dry-run is the default (Graph GETs only, a before/after diff of redirect URIs and
app role VALUES). ``--apply`` additionally needs ``NS_LIVE_APPROVED=1`` and is checked before any
PATCH or POST is sent.

    python scripts/gates/p29_entra_local.py --app-id <app-id> --tenant-id <tenant-id>
    NS_LIVE_APPROVED=1 python scripts/gates/p29_entra_local.py --app-id <app-id> \
        --tenant-id <tenant-id> --apply --assign-self admin

What ``--apply`` changes (merge only, never removes; a second run sends nothing):

* adds the missing ``spa`` redirect URIs (defaults ``http://localhost:5173`` and
  ``http://localhost:8080``);
* adds the missing app roles ``viewer``, ``analyst``, ``domain_steward``, ``admin``,
  ``security_auditor`` (ids are uuid5 of a fixed namespace and the value), existing roles
  are sent back unchanged minus the read-only ``origin``;
* sets ``api.requestedAccessTokenVersion`` to 2 (the access token ``aud`` is then the API's
  client id GUID);
* with ``--assign-self ROLE``, assigns the signed-in user that app role on the app's service
  principal (skipped when already assigned).

App roles only drive navigation display. Authority comes from the policy store: run
``scripts/sandbox/sbx_grant_operator.py`` as well (docs/dev/local-setup.md).

The app id and tenant id are supplied by the operator and never committed (the repo is public).
Graph calls go through ``az rest``; no token, secret or object id is read into output, printed
or written. Never runs ``az deployment``. Under Git Bash on Windows nothing here is a POSIX
path, so ``MSYS_NO_PATHCONV`` is not needed for this script (the Graph URL starts with https).
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Final
from urllib.parse import quote, urlsplit

GUID_RE: Final = re.compile(r"^[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$")
DEFAULT_REDIRECT_URIS: Final = ("http://localhost:5173", "http://localhost:8080")
GRAPH_BASE: Final = {
    "commercial": "https://graph.microsoft.com/v1.0",
    "government": "https://graph.microsoft.us/v1.0",
}
ROLE_NAMESPACE: Final = uuid.uuid5(uuid.NAMESPACE_DNS, "neurosphere.entra-app-roles.v1")
ROLE_FIELDS: Final = (
    "allowedMemberTypes",
    "description",
    "displayName",
    "id",
    "isEnabled",
    "value",
)
TOKEN_VERSION: Final = 2
EXIT_REFUSED: Final = 2

#: (value, description). The display name is the value; ids come from :func:`role_id`.
ROLE_DEFINITIONS: Final = (
    ("viewer", "Read the catalog, costs and map within granted domains."),
    ("analyst", "Viewer plus reports, exports and proposing actions."),
    ("domain_steward", "Analyst plus curating the catalog of the stewarded domains."),
    ("admin", "Manage configuration and policy; time-bound privileged role."),
    ("security_auditor", "Read audit and policy evidence; time-bound privileged role."),
)

#: ``az`` runner: arguments after ``az`` (and an optional JSON body) -> stdout text.
AzRunner = Callable[[Sequence[str], Mapping[str, Any] | None], str]


class AzError(RuntimeError):
    """An ``az`` call failed. The message never carries az output (it could echo a token)."""


def role_id(value: str) -> str:
    return str(uuid.uuid5(ROLE_NAMESPACE, value))


def role_body(value: str, description: str) -> dict[str, Any]:
    return {
        "allowedMemberTypes": ["User"],
        "description": description,
        "displayName": value,
        "id": role_id(value),
        "isEnabled": True,
        "value": value,
    }


def default_az(args: Sequence[str], body: Mapping[str, Any] | None = None) -> str:
    """Run ``az``. The JSON body goes through a temp file (``--body @file``) because cmd.exe
    mangles inline JSON quotes when ``az.cmd`` is launched on Windows."""
    exe = shutil.which("az")
    if exe is None:
        raise AzError("az CLI not found on PATH")
    command = [exe, *args]
    tmp_path: Path | None = None
    try:
        if body is not None:
            with tempfile.NamedTemporaryFile(
                "w", suffix=".json", delete=False, encoding="utf-8"
            ) as handle:
                json.dump(body, handle)
                tmp_path = Path(handle.name)
            command += ["--body", f"@{tmp_path}"]
        done = subprocess.run(command, capture_output=True, text=True, check=False, timeout=120)
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)
    if done.returncode != 0:
        raise AzError(f"az exited {done.returncode}")
    return done.stdout


class Graph:
    def __init__(self, az: AzRunner, cloud: str) -> None:
        self._az = az
        self._base = GRAPH_BASE[cloud]

    def request(self, method: str, path: str, body: Mapping[str, Any] | None = None) -> Any:
        args = ["rest", "--method", method.lower(), "--url", self._base + path]
        if body is not None:
            args += ["--headers", "Content-Type=application/json"]
        out = self._az(args, body)
        return json.loads(out) if out.strip() else {}

    def get(self, path: str) -> Any:
        return self.request("GET", path)

    def az_text(self, args: Sequence[str]) -> str:
        return self._az(args, None)

    def signed_in_user_id(self) -> str:
        return self.az_text(["ad", "signed-in-user", "show", "--query", "id", "-o", "tsv"]).strip()


def _host_path(uri: str) -> tuple[str, str]:
    parts = urlsplit(uri)
    return (parts.hostname or "", parts.path.rstrip("/"))


def _is_localhost(uri: str) -> bool:
    return urlsplit(uri).hostname in ("localhost", "127.0.0.1", "::1")


def port_collision_warnings(
    new_spa: Sequence[str], web: Sequence[str], public_client: Sequence[str]
) -> list[str]:
    """Localhost matching ignores the port, so a web/publicClient localhost URI with the same
    host and path as a spa URI being added is picked arbitrarily by the login server."""
    warnings: list[str] = []
    for uri in new_spa:
        if not _is_localhost(uri):
            continue
        for kind, existing in (("web", web), ("publicClient", public_client)):
            for other in existing:
                if _is_localhost(other) and _host_path(other) == _host_path(uri):
                    warnings.append(
                        f"WARNING: spa {uri} and {kind} {other} differ only by port; Entra "
                        "ignores localhost ports when matching and may pick either platform "
                        "type's behaviour"
                    )
    return warnings


def plan_roles(existing: Sequence[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    """The full appRoles list to send (existing unchanged minus ``origin``) and added values."""
    kept = [{k: role[k] for k in ROLE_FIELDS if k in role} for role in existing]
    present = {role.get("value") for role in existing}
    added = [value for value, _ in ROLE_DEFINITIONS if value not in present]
    descriptions = dict(ROLE_DEFINITIONS)
    return kept + [role_body(value, descriptions[value]) for value in added], added


class Plan:
    def __init__(self) -> None:
        self.patch: dict[str, Any] = {}
        self.lines: list[str] = []
        self.warnings: list[str] = []


def build_plan(app: Mapping[str, Any], redirect_uris: Sequence[str]) -> Plan:
    plan = Plan()
    spa_now = list((app.get("spa") or {}).get("redirectUris") or [])
    spa_add = [uri for uri in dict.fromkeys(redirect_uris) if uri not in spa_now]
    plan.lines.append("spa.redirectUris before: " + json.dumps(spa_now))
    plan.lines.append("spa.redirectUris after:  " + json.dumps(spa_now + spa_add))
    if spa_add:
        plan.patch["spa"] = {"redirectUris": spa_now + spa_add}
    plan.warnings += port_collision_warnings(
        spa_add,
        list((app.get("web") or {}).get("redirectUris") or []),
        list((app.get("publicClient") or {}).get("redirectUris") or []),
    )

    existing_roles = list(app.get("appRoles") or [])
    roles, added = plan_roles(existing_roles)
    plan.lines.append(
        "appRoles before (values): " + json.dumps([r.get("value") for r in existing_roles])
    )
    plan.lines.append("appRoles after (values):  " + json.dumps([r.get("value") for r in roles]))
    for role in existing_roles:
        if role.get("value") in dict(ROLE_DEFINITIONS) and role.get("isEnabled") is False:
            plan.warnings.append(f"WARNING: app role {role.get('value')} exists but is disabled")
    if added:
        plan.patch["appRoles"] = roles
    version = (app.get("api") or {}).get("requestedAccessTokenVersion")
    plan.lines.append(f"api.requestedAccessTokenVersion: {version} -> {TOKEN_VERSION}")
    if version != TOKEN_VERSION:
        plan.patch["api"] = {"requestedAccessTokenVersion": TOKEN_VERSION}
    return plan


def _assign_self(
    graph: Graph, app: Mapping[str, Any], role_value: str, *, apply: bool
) -> list[str]:
    app_id = app["appId"]
    rid = next(
        (r["id"] for r in app.get("appRoles") or [] if r.get("value") == role_value),
        role_id(role_value),
    )
    sp_path = f"/servicePrincipals(appId='{quote(app_id)}')?$select=id"
    try:
        sp = graph.get(sp_path)
    except AzError:
        return [
            f"assign-self {role_value}: no service principal found for the app "
            "(create it first: az ad sp create --id <app-id>)"
        ]
    sp_id = sp["id"]
    me = graph.signed_in_user_id()
    assigned = graph.get(
        f"/servicePrincipals/{sp_id}/appRoleAssignedTo?$select=principalId,appRoleId"
    )
    for item in assigned.get("value", []):
        if item.get("principalId") == me and item.get("appRoleId") == rid:
            return [f"assign-self {role_value}: already assigned (no change)"]
    if not apply:
        return [f"assign-self {role_value}: would assign the signed-in user (dry-run)"]
    graph.request(
        "POST",
        f"/servicePrincipals/{sp_id}/appRoleAssignedTo",
        {"principalId": me, "resourceId": sp_id, "appRoleId": rid},
    )
    return [f"assign-self {role_value}: assigned the signed-in user"]


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--app-id", required=True, help="API app (client) id GUID")
    p.add_argument("--tenant-id", required=True, help="tenant GUID that owns the app")
    p.add_argument(
        "--redirect-uri",
        action="append",
        dest="redirect_uris",
        help="SPA redirect URI to ensure (repeatable); default localhost 5173 and 8080",
    )
    p.add_argument("--assign-self", metavar="ROLE", choices=[v for v, _ in ROLE_DEFINITIONS])
    p.add_argument("--cloud", choices=sorted(GRAPH_BASE), default="commercial")
    p.add_argument("--apply", action="store_true", help="write changes (needs NS_LIVE_APPROVED=1)")
    return p


def main(
    argv: Sequence[str] | None = None,
    *,
    az: AzRunner | None = None,
    env: Mapping[str, str] | None = None,
) -> int:
    args = _parser().parse_args(argv)
    environ = os.environ if env is None else env
    for name, value in (("--app-id", args.app_id), ("--tenant-id", args.tenant_id)):
        if GUID_RE.fullmatch(value) is None:
            print(f"ERROR: {name} must be a GUID.", file=sys.stderr)
            return EXIT_REFUSED
    if args.apply and environ.get("NS_LIVE_APPROVED") != "1":
        print(
            "REFUSED: --apply needs operator approval; set NS_LIVE_APPROVED=1. "
            "Nothing was changed.",
            file=sys.stderr,
        )
        return EXIT_REFUSED

    graph = Graph(az or default_az, args.cloud)
    redirect_uris = args.redirect_uris or list(DEFAULT_REDIRECT_URIS)
    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"p29_entra_local ({mode}) cloud={args.cloud}")
    try:
        signed_in_tenant = graph.az_text(["account", "show", "--query", "tenantId", "-o", "tsv"])
        if signed_in_tenant.strip().lower() != args.tenant_id.lower():
            print("ERROR: the active az tenant is not --tenant-id; run az login.", file=sys.stderr)
            return 1
        app = graph.get(
            f"/applications(appId='{quote(args.app_id)}')"
            "?$select=id,appId,spa,web,publicClient,api,appRoles"
        )
        plan = build_plan(app, redirect_uris)
        for line in (*plan.lines, *plan.warnings):
            print(line)
        if plan.patch and args.apply:
            graph.request("PATCH", f"/applications/{app['id']}", plan.patch)
            print("PATCH sent: " + ", ".join(sorted(plan.patch)))
        elif plan.patch:
            print("would PATCH: " + ", ".join(sorted(plan.patch)) + " (dry-run)")
        else:
            print("application already up to date (no change)")
        if args.assign_self:
            for line in _assign_self(graph, app, args.assign_self, apply=args.apply):
                print(line)
    except AzError as exc:
        print(f"ERROR: {exc}; are you logged in to the right cloud and tenant?", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
