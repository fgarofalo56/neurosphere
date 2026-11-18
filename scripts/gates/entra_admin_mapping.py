"""PRP-138 item 8: map an Entra app role to the NeuroSphere ``admin`` role (operator script).

Three subcommands; ``plan`` is the default and changes nothing.

    python scripts/gates/entra_admin_mapping.py plan --cloud commercial \
        --app-id <api-app-id> --tenant-id <tenant-id> [--assign-user <guid-or-upn>]
    NS_LIVE_APPROVED=1 python scripts/gates/entra_admin_mapping.py apply --cloud commercial \
        --app-id <api-app-id> --tenant-id <tenant-id> --approve entra-app \
        (--group-object-id <guid> | --assign-user <guid-or-upn>)
    NS_LIVE_APPROVED=1 uv run python scripts/gates/entra_admin_mapping.py verify \
        --cloud commercial --app-id <api-app-id> --tenant-id <tenant-id> --base-url https://<api>

* ``plan``: Microsoft Graph reads only (``az rest`` GET). Prints the app role values before and
  after and whether the given group or user already holds the ``admin`` app role.
* ``apply``: needs ``NS_LIVE_APPROVED=1`` and ``--approve entra-app``, both checked before any
  ``az`` call. Adds the ``admin`` app role when it is missing (allowed member type ``User``
  only; built with ``plan_roles`` from ``p29_entra_local.py``), assigns exactly one group or
  user to it, and prints the ``NS_AUTH_ROLE_MAPPINGS`` value and the ``entraRoleMappings``
  parameter. A second run finds nothing to do and sends no write.
* ``verify`` (live gate G-138): needs ``NS_LIVE_APPROVED=1`` or it reports the gate OPEN (exit
  2). It asks ``az account get-access-token`` for a token for the API app (held in memory only),
  calls ``GET /api/v1/me/access`` and ``GET /api/v1/admin/system/status`` and writes evidence to
  ``docs/evidence/PRP-138/``. UNVERIFIED: that az can obtain that token in the operator's
  tenant; when it cannot, the manual browser check is printed and the gate stays OPEN (exit 3).

Every subcommand first checks that the active ``az cloud show`` matches ``--cloud`` and that the
active tenant is ``--tenant-id``, so a Government request never reaches the Commercial Graph host
or the reverse. Output carries counts and "assigned"/"not assigned", never a token, a secret or a
group, user or service principal object id. The tenant id and API app id are operator-supplied
identifiers (not secrets) and appear only in the printed mapping value. Never runs
``az deployment``. Exit codes: 0 done or PASS, 1 failed, 2 refused (nothing changed; for
``verify`` the gate stays OPEN), 3 OPEN (verify approved but no token could be obtained).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, NamedTuple
from urllib.parse import quote, urlsplit

if TYPE_CHECKING:
    import httpx

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")  # pyright: ignore[reportAttributeAccessIssue]

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from p29_entra_local import (  # noqa: E402
    EXIT_REFUSED,
    GRAPH_BASE,
    GUID_RE,
    AzError,
    az_command,
    plan_roles,
    role_id,
)

REPO: Final = Path(__file__).resolve().parents[2]
EVIDENCE_DIR: Final = REPO / "docs" / "evidence" / "PRP-138"
EXIT_FAILED: Final = 1
EXIT_OPEN: Final = 3
ROLE_VALUE: Final = "admin"
ENTRY_ID: Final = "ns-admins"
APPROVAL_WORD: Final = "entra-app"
AZ_CLOUD_NAME: Final = {"commercial": "AzureCloud", "government": "AzureUSGovernment"}
COMMANDS: Final = ("plan", "apply", "verify")
ME_ACCESS_PATH: Final = "/api/v1/me/access"
SYSTEM_STATUS_PATH: Final = "/api/v1/admin/system/status"
#: Lower-case fragments of a Graph refusal caused by a tenant without Entra ID P1. UNVERIFIED:
#: the exact Graph error text for a group assignment on a free tenant was not observed here.
LICENSE_HINTS: Final = ("licen", "premium", "plan level", " p1")
P1_MESSAGE: Final = (
    "Microsoft Graph refused to assign the group to the app role. Assigning a group to an app "
    "role needs Microsoft Entra ID P1 (or higher) in this tenant. No assignment was made. "
    "Assign the person directly instead: re-run apply with --assign-user <object id or UPN>."
)

#: ``az`` runner: arguments after ``az`` (and an optional JSON body) -> stdout text.
AzRunner = Callable[[Sequence[str], Mapping[str, Any] | None], str]


class AzCallError(AzError):
    """An ``az`` call failed. Carries only the exit code and a reason code, never az output."""

    def __init__(self, returncode: int, reason: str) -> None:
        super().__init__(f"az exited {returncode} ({reason})")
        self.returncode = returncode
        self.reason = reason


class RefusedError(RuntimeError):
    """A precondition failed before anything was changed."""


def classify_az_error(stderr: str) -> str:
    """Reduce az error output to a reason code; the text itself is never kept or printed."""
    text = stderr.lower()
    if any(hint in text for hint in LICENSE_HINTS):
        return "license_required"
    if "authorization_requestdenied" in text or "insufficient privileges" in text:
        return "insufficient_privileges"
    if "request_resourcenotfound" in text or "does not exist" in text or "not found" in text:
        return "not_found"
    if "aadsts" in text:
        return "token_refused"
    return "az_failed"


def default_az(args: Sequence[str], body: Mapping[str, Any] | None = None) -> str:
    """Run ``az`` like ``p29_entra_local.default_az`` (bundled python, body via ``@file``, no
    shell), but keep a reason code from stderr so a P1 refusal can be named."""
    exe = shutil.which("az")
    if exe is None:
        raise AzCallError(127, "az_not_found")
    command = [*az_command(exe), *args]
    tmp_path: Path | None = None
    try:
        if body is not None:
            with tempfile.NamedTemporaryFile(
                "w", suffix=".json", delete=False, encoding="utf-8"
            ) as handle:
                json.dump(body, handle)
                tmp_path = Path(handle.name)
            command += ["--body", f"@{tmp_path}"]
        done = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=120,
            stdin=subprocess.DEVNULL,
        )
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)
    if done.returncode != 0:
        raise AzCallError(done.returncode, classify_az_error(done.stderr or ""))
    return done.stdout


class Graph:
    """Graph through ``az rest`` against the one Graph host of ``--cloud``."""

    def __init__(self, az: AzRunner, cloud: str) -> None:
        self._az = az
        self.base = GRAPH_BASE[cloud]
        self.writes = 0

    def _call(self, method: str, url: str, body: Mapping[str, Any] | None = None) -> Any:
        if not url.startswith(self.base + "/"):
            raise RefusedError("refusing a Graph URL outside the Graph host of --cloud")
        args = ["rest", "--method", method.lower(), "--url", url]
        if body is not None:
            args += ["--headers", "Content-Type=application/json"]
            self.writes += 1
        out = self._az(args, body)
        return json.loads(out) if out.strip() else {}

    def get(self, path: str) -> Any:
        return self._call("GET", self.base + path)

    def get_all(self, path: str) -> list[dict[str, Any]]:
        """GET a collection, following ``@odata.nextLink`` on the same Graph host only."""
        items: list[dict[str, Any]] = []
        page: Any = self.get(path)
        for _ in range(100):
            items += [i for i in page.get("value") or [] if isinstance(i, dict)]
            link = page.get("@odata.nextLink")
            if not link:
                return items
            page = self._call("GET", str(link))
        raise RefusedError("too many result pages; refusing to continue")

    def send(self, method: str, path: str, body: Mapping[str, Any]) -> Any:
        return self._call(method, self.base + path, body)


class Target(NamedTuple):
    kind: str  # "group" | "user"
    object_id: str


def _parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--cloud", required=True, choices=sorted(AZ_CLOUD_NAME))
    common.add_argument("--app-id", required=True, help="API app (client) id GUID")
    common.add_argument("--tenant-id", required=True, help="tenant GUID that owns the app")

    principal = argparse.ArgumentParser(add_help=False)
    who = principal.add_mutually_exclusive_group()
    who.add_argument("--group-object-id", help="Entra group object id (needs Entra ID P1)")
    who.add_argument("--assign-user", help="Entra user object id or user principal name")

    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("plan", parents=[common, principal], help="Graph reads only (default)")
    apply = sub.add_parser("apply", parents=[common, principal], help="add role and assign")
    apply.add_argument("--approve", default="", help=f"must be {APPROVAL_WORD}")
    verify = sub.add_parser("verify", parents=[common], help="live gate G-138")
    verify.add_argument("--base-url", required=True, help="deployed API origin, https://...")
    return p


def _normalize_argv(argv: Sequence[str]) -> list[str]:
    args = list(argv)
    if not args or args[0] not in (*COMMANDS, "-h", "--help"):
        return ["plan", *args]
    return args


def _check_ids(args: argparse.Namespace) -> None:
    for name, value in (("--app-id", args.app_id), ("--tenant-id", args.tenant_id)):
        if GUID_RE.fullmatch(value) is None:
            raise RefusedError(f"{name} must be a GUID")
    group = getattr(args, "group_object_id", None)
    if group is not None and GUID_RE.fullmatch(group) is None:
        raise RefusedError("--group-object-id must be a GUID")
    user = getattr(args, "assign_user", None)
    if user is not None and GUID_RE.fullmatch(user) is None and "@" not in user:
        raise RefusedError("--assign-user must be a user object id GUID or a UPN")


def _check_cloud_and_tenant(az: AzRunner, args: argparse.Namespace) -> None:
    """Read-only ``az`` checks; nothing reaches Graph before both pass."""
    active = az(["cloud", "show", "--query", "name", "-o", "tsv"], None).strip()
    expected = AZ_CLOUD_NAME[args.cloud]
    if active != expected:
        raise RefusedError(
            f"the active az cloud is {active or 'unknown'}, but --cloud {args.cloud} needs "
            f"{expected}. Run az cloud set --name {expected} and az login. Nothing was sent."
        )
    tenant = az(["account", "show", "--query", "tenantId", "-o", "tsv"], None).strip()
    if tenant.lower() != args.tenant_id.lower():
        raise RefusedError("the active az tenant is not --tenant-id; run az login --tenant.")


def _resolve_target(graph: Graph, args: argparse.Namespace) -> Target | None:
    if args.group_object_id:
        group = graph.get(f"/groups/{args.group_object_id.lower()}?$select=id")
        return Target("group", str(group.get("id") or ""))
    if args.assign_user:
        user = graph.get(f"/users/{quote(args.assign_user, safe='@')}?$select=id")
        return Target("user", str(user.get("id") or ""))
    return None


def _role_plan(app: Mapping[str, Any]) -> tuple[list[dict[str, Any]], bool, str]:
    """The appRoles list to send (only ``admin`` is added), whether it changes, the role id."""
    existing = [dict(r) for r in app.get("appRoles") or []]
    full, added = plan_roles(existing)
    kept = full[: len(existing)]
    new = [r for r in full[len(existing) :] if r.get("value") == ROLE_VALUE]
    rid = next(
        (str(r["id"]) for r in existing if r.get("value") == ROLE_VALUE), role_id(ROLE_VALUE)
    )
    return kept + new, ROLE_VALUE in added, rid


def _role_warnings(app: Mapping[str, Any]) -> list[str]:
    out: list[str] = []
    for role in app.get("appRoles") or []:
        if role.get("value") != ROLE_VALUE:
            continue
        if role.get("isEnabled") is False:
            out.append("WARNING: the admin app role exists but is disabled; enable it in Entra")
        if "User" not in (role.get("allowedMemberTypes") or []):
            out.append("WARNING: the admin app role does not allow User members")
    return out


def mapping_value(tenant_id: str, app_id: str) -> dict[str, Any]:
    return {
        "tenant_id": tenant_id.lower(),
        "audience": app_id.lower(),
        "entries": [
            {
                "id": ENTRY_ID,
                "claim": "roles",
                "value": ROLE_VALUE,
                "role": ROLE_VALUE,
                "domains": "all",
                "customer_control": True,
            }
        ],
    }


def _bicep(value: Any, indent: int = 0) -> str:
    pad = "  " * indent
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"
    if isinstance(value, list):
        inner = "\n".join(f"{pad}  {_bicep(v, indent + 1)}" for v in value)
        return f"[\n{inner}\n{pad}]"
    if isinstance(value, dict):
        inner = "\n".join(f"{pad}  {k}: {_bicep(v, indent + 1)}" for k, v in value.items())
        return f"{{\n{inner}\n{pad}}}"
    return str(value)


def _print_mapping(args: argparse.Namespace) -> None:
    value = mapping_value(args.tenant_id, args.app_id)
    print("NS_AUTH_ROLE_MAPPINGS (API app setting, one line of JSON, identifiers only):")
    print(json.dumps(value, separators=(",", ":")))
    print("entraRoleMappings (infra/demo main.bicepparam, same object):")
    print("param entraRoleMappings = " + _bicep(value))


def _assignments(graph: Graph, sp_id: str) -> list[dict[str, Any]]:
    return graph.get_all(
        f"/servicePrincipals/{sp_id}/appRoleAssignedTo?$select=principalId,appRoleId"
    )


def _run_entra(az: AzRunner, args: argparse.Namespace, *, apply: bool) -> int:
    target_required = apply
    graph = Graph(az, args.cloud)
    mode = "APPLY" if apply else "PLAN (Graph reads only)"
    print(f"entra_admin_mapping {mode} cloud={args.cloud} role={ROLE_VALUE}")
    _check_cloud_and_tenant(az, args)
    app = graph.get(f"/applications(appId='{quote(args.app_id)}')?$select=id,appId,appRoles")
    app_obj = str(app.get("id") or "")
    if GUID_RE.fullmatch(app_obj) is None:
        raise RefusedError("Graph returned no application for --app-id")
    roles, role_missing, rid = _role_plan(app)
    before = [r.get("value") for r in app.get("appRoles") or []]
    print("appRoles before (values): " + json.dumps(before))
    print("appRoles after (values):  " + json.dumps([r.get("value") for r in roles]))
    for line in _role_warnings(app):
        print(line)

    sp = graph.get(f"/servicePrincipals(appId='{quote(args.app_id)}')?$select=id")
    sp_id = str(sp.get("id") or "")
    if GUID_RE.fullmatch(sp_id) is None:
        raise RefusedError(
            "the app has no service principal in this tenant (an admin creates it with "
            "az ad sp create --id <app-id>); nothing was changed"
        )
    target = _resolve_target(graph, args)
    if target_required and target is None:
        raise RefusedError("apply needs --group-object-id or --assign-user (exactly one)")
    assigned = False
    if target is not None:
        if GUID_RE.fullmatch(target.object_id) is None:
            raise RefusedError(f"Graph returned no {target.kind} for the given value")
        rows = _assignments(graph, sp_id)
        assigned = any(
            str(r.get("principalId", "")).lower() == target.object_id.lower()
            and str(r.get("appRoleId", "")).lower() == rid.lower()
            for r in rows
        )
        print(f"existing assignments to the app: {len(rows)}")
        print(f"{target.kind} -> admin app role: {'assigned' if assigned else 'not assigned'}")

    if not apply:
        print(f"would add app role: {'admin' if role_missing else 'none (already present)'}")
        if target is not None and not assigned:
            print(f"would assign the {target.kind} to the admin app role")
        print("plan only: nothing was changed")
        return 0

    assert target is not None
    changed: list[str] = []
    if role_missing:
        graph.send("PATCH", f"/applications/{app_obj}", {"appRoles": roles})
        changed.append("added the admin app role (allowed member type User)")
    if not assigned:
        body = {"principalId": target.object_id, "resourceId": sp_id, "appRoleId": rid}
        try:
            graph.send("POST", f"/servicePrincipals/{sp_id}/appRoleAssignedTo", body)
        except AzCallError as exc:
            for line in changed:
                print("changed: " + line)
            if target.kind == "group" and exc.reason == "license_required":
                print("REFUSED: " + P1_MESSAGE, file=sys.stderr)
                return EXIT_REFUSED
            if target.kind == "group":
                print(
                    f"ERROR: the group assignment failed ({exc.reason}). If this tenant has no "
                    "Entra ID P1, groups cannot be assigned to app roles; use --assign-user.",
                    file=sys.stderr,
                )
                return EXIT_FAILED
            raise
        changed.append(f"assigned the {target.kind} to the admin app role")
    if changed:
        for line in changed:
            print("changed: " + line)
        print(f"Graph writes sent: {graph.writes}")
    else:
        print("nothing to do: the admin app role exists and the assignment is present (no write)")
    _print_mapping(args)
    print(
        "next: set NS_AUTH_ROLE_MAPPINGS on the API (or deploy with entraRoleMappings), restart, "
        "sign in again for a fresh token, then run verify. See docs/runbooks/entra-role-mapping.md"
    )
    return 0


# --- verify (live gate G-138) ---------------------------------------------------------------


def manual_check(base_url: str) -> str:
    return (
        "Manual check (gate stays OPEN until recorded): sign in to the NeuroSphere console as the "
        "assigned person in a fresh browser session, open Admin > Identity > Your access and "
        f"confirm role admin with source entra_app_role; then open {base_url.rstrip('/')}"
        f"{SYSTEM_STATUS_PATH} through the console (Admin > System) and confirm it loads. Record "
        "the date, status codes and role sources in docs/evidence/PRP-138/ by hand."
    )


def _check_base_url(raw: str) -> str:
    parts = urlsplit(raw)
    local = parts.hostname in ("localhost", "127.0.0.1")
    if parts.scheme != "https" and not (parts.scheme == "http" and local):
        raise RefusedError("--base-url must be https:// (http only for localhost)")
    if not parts.hostname or parts.query or parts.fragment:
        raise RefusedError("--base-url must be an origin such as https://api.example")
    return f"{parts.scheme}://{parts.netloc}"


def _obtain_bearer(az: AzRunner, args: argparse.Namespace) -> str | None:
    """In-memory only. Returns None when az cannot get one (UNVERIFIED path, see docstring)."""
    try:
        out = az(
            [
                "account",
                "get-access-token",
                "--resource",
                f"api://{args.app_id.lower()}",
                "--tenant",
                args.tenant_id.lower(),
                "--query",
                "accessToken",
                "-o",
                "tsv",
            ],
            None,
        )
    except AzError:
        return None
    value = out.strip()
    return value or None


def _role_rows(payload: Any) -> list[dict[str, str]]:
    rows = payload.get("roles") if isinstance(payload, dict) else None
    out: list[dict[str, str]] = []
    for row in rows if isinstance(rows, list) else []:
        if isinstance(row, dict):
            out.append({"role": str(row.get("role", "")), "source": str(row.get("source", ""))})
    return out


def _run_verify(
    az: AzRunner,
    args: argparse.Namespace,
    *,
    transport: httpx.BaseTransport | None,
    evidence_dir: Path,
    now: Callable[[], datetime],
) -> int:
    import httpx

    origin = _check_base_url(args.base_url)
    _check_cloud_and_tenant(az, args)
    started = now()
    bearer = _obtain_bearer(az, args)
    if bearer is None:
        print(
            "G-138 OPEN: az could not obtain an access token for the API app (UNVERIFIED that "
            "it can in this tenant). No API call was made.",
            file=sys.stderr,
        )
        print(manual_check(origin))
        return EXIT_OPEN
    results: dict[str, Any] = {}
    with httpx.Client(transport=transport, timeout=30.0, follow_redirects=False) as client:
        for path in (ME_ACCESS_PATH, SYSTEM_STATUS_PATH):
            try:
                resp = client.get(origin + path, headers={"Authorization": "Bearer " + bearer})
            except httpx.HTTPError as exc:
                results[path] = {"status": None, "error": type(exc).__name__}
                continue
            entry: dict[str, Any] = {"status": resp.status_code}
            if path == ME_ACCESS_PATH and resp.status_code == 200:
                try:
                    payload = resp.json()
                except ValueError:
                    payload = {}
                entry["roles"] = _role_rows(payload)
                if isinstance(payload, dict):
                    entry["mapping_configured"] = bool(payload.get("mapping_configured"))
                    entry["groups_overage"] = bool(payload.get("groups_overage"))
            results[path] = entry
    del bearer
    finished = now()
    roles = results.get(ME_ACCESS_PATH, {}).get("roles", [])
    mapped_admin = any(r["role"] == "admin" and r["source"].startswith("entra_") for r in roles)
    passed = (
        results.get(ME_ACCESS_PATH, {}).get("status") == 200
        and results.get(SYSTEM_STATUS_PATH, {}).get("status") == 200
        and mapped_admin
    )
    evidence = {
        "gate": "G-138",
        "cloud": args.cloud,
        "result": "PASS" if passed else "FAIL",
        "started_utc": started.isoformat(),
        "finished_utc": finished.isoformat(),
        "checks": results,
        "note": "status codes, role names and sources only; no token, claim or object id",
    }
    evidence_dir.mkdir(parents=True, exist_ok=True)
    stamp = started.strftime("%Y%m%dT%H%M%SZ")
    path = evidence_dir / f"verify-{args.cloud}-{stamp}.json"
    path.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    for api_path, entry in results.items():
        print(f"{api_path}: status {entry.get('status')}")
    print(f"roles from /me/access: {json.dumps(roles)}")
    print(f"G-138 {evidence['result']}; evidence written to {path.name}")
    return 0 if passed else EXIT_FAILED


def main(
    argv: Sequence[str] | None = None,
    *,
    az: AzRunner | None = None,
    env: Mapping[str, str] | None = None,
    transport: httpx.BaseTransport | None = None,
    evidence_dir: Path | None = None,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    args = _parser().parse_args(_normalize_argv(raw))
    environ = os.environ if env is None else env
    approved = environ.get("NS_LIVE_APPROVED") == "1"
    try:
        _check_ids(args)
        if args.command == "verify" and not approved:
            print(
                "G-138 OPEN: verify needs operator approval; set NS_LIVE_APPROVED=1. "
                "No token was requested and no API call was made.",
                file=sys.stderr,
            )
            return EXIT_REFUSED
        if args.command == "apply":
            if not approved:
                raise RefusedError("apply needs operator approval; set NS_LIVE_APPROVED=1")
            if args.approve != APPROVAL_WORD:
                raise RefusedError(f"apply needs --approve {APPROVAL_WORD}")
            if not (args.group_object_id or args.assign_user):
                raise RefusedError("apply needs --group-object-id or --assign-user (one)")
        runner = az or default_az
        if args.command == "verify":
            return _run_verify(
                runner,
                args,
                transport=transport,
                evidence_dir=evidence_dir or EVIDENCE_DIR,
                now=now,
            )
        return _run_entra(runner, args, apply=args.command == "apply")
    except RefusedError as exc:
        print(f"REFUSED: {exc}. Nothing was changed.", file=sys.stderr)
        return EXIT_REFUSED
    except AzError as exc:
        print(f"ERROR: {exc}; are you signed in to the right cloud and tenant?", file=sys.stderr)
        return EXIT_FAILED


if __name__ == "__main__":
    raise SystemExit(main())
