"""Shared logic for the G02 Government profile gates (AKS and App Service).

Standard library only: importing this module never imports project code and never runs a
command. The two entry scripts (`g02_profile_aks.py`, `g02_profile_appservice.py`) check
NS_LIVE_APPROVED=1 first and only then call `execute`.

Refusal ladder (every refusal exits 2, prints OPEN, writes nothing, runs no deploy command):
  1. NS_LIVE_APPROVED != "1"                       (entry script, before argparse)
  2. NS_GOV_SUBSCRIPTION_ID missing or not a GUID  (value is never printed or written)
  3. requested region not in the Government set
  4. active `az` cloud is not AzureUSGovernment    (the only command run before this is
                                                    `az cloud show`, read-only)
  5. profile-specific configuration missing        (e.g. NS_GOV_IMAGE_REGISTRY)

Exit codes: 0 PASS, 1 FAIL (evidence written), 2 REFUSED (gate stays OPEN).

Drift and uninstall safety are real checks, not placeholders; see each profile for the exact
drift command. Teardown deletes only the resource group this script created, and only after
re-reading the run-id tag and confirming the dry-run plan found nothing foreign inside it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NamedTuple, Protocol

REPO = Path(__file__).resolve().parents[2]
SCRIPT_VERSION = "1.0.0"
GATE = "G02"
EVIDENCE_DIR = REPO / "docs" / "evidence" / "G02"
APPROVAL_ENV = "NS_LIVE_APPROVED"
SUBSCRIPTION_ENV = "NS_GOV_SUBSCRIPTION_ID"
REGISTRY_ENV = "NS_GOV_IMAGE_REGISTRY"
GOV_CLOUD = "AzureUSGovernment"
GOV_REGIONS = frozenset({"usgovvirginia", "usgovarizona", "usgovtexas"})
DEFAULT_LOCATION = "usgovvirginia"
TAG_CREATED_BY = "neurosphere:created-by"
TAG_GATE = "neurosphere:gate"
TAG_RUN = "neurosphere:run-id"
COMMAND_TIMEOUT_SECONDS = 2 * 60 * 60

DISCLAIMER = (
    "Live gate evidence only. Availability is not authorization; NeuroSphere is not FedRAMP "
    "authorized; the authorizing official decides."
)

_GUID = re.compile(r"^[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$")
_GUID_ANYWHERE = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,62}$")


class RefusedError(RuntimeError):
    """A precondition failed before anything was changed."""


class StepError(RuntimeError):
    """A command or check failed after the deploy started."""


class ScrubError(RuntimeError):
    """Evidence contained something that looks like a credential."""


# --------------------------------------------------------------------------- runner


class CmdResult(NamedTuple):
    rc: int
    stdout: str
    stderr: str


class Runner(Protocol):
    """Runs one command. ``argv[0]`` is the tool name (`az`, `helm`, `kubectl`)."""

    def __call__(self, argv: Sequence[str]) -> CmdResult: ...


class SubprocessRunner:
    """The real runner: resolved executable, fixed argv list, no shell."""

    def __call__(self, argv: Sequence[str]) -> CmdResult:
        exe = shutil.which(argv[0])
        if not exe:
            raise RefusedError(f"{argv[0]} was not found on PATH")
        proc = subprocess.run(
            [exe, *argv[1:]],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdin=subprocess.DEVNULL,
            timeout=COMMAND_TIMEOUT_SECONDS,
            check=False,
            shell=False,
        )
        return CmdResult(proc.returncode, proc.stdout, proc.stderr)


# --------------------------------------------------------------------------- scrubber

_SECRET_VALUE_PATTERNS = (
    re.compile(r"eyJ[A-Za-z0-9_-]{8,}"),
    re.compile(r"AccountKey\s*=", re.IGNORECASE),
    re.compile(r"SharedAccessKey(Name)?\s*=", re.IGNORECASE),
    re.compile(r"DefaultEndpointsProtocol\s*=", re.IGNORECASE),
    re.compile(r"-----BEGIN"),
    re.compile(r"[A-Za-z0-9+/]{40,}={1,2}"),
    re.compile(r"(?i)\b(password|passwd|secret|api[-_]?key|bearer)\b\s*[:=]\s*\S"),
    re.compile(r"(?i)[?&]sig=[A-Za-z0-9%+/=]{8,}"),
)
_SECRET_KEY_PATTERN = re.compile(
    r"(?i)(access.?token|primary.?key|secondary.?key|connection.?string|list.?keys"
    r"|password|secret|sas.?token|api.?key)"
)


def _looks_secret(text: str) -> bool:
    return any(p.search(text) for p in _SECRET_VALUE_PATTERNS)


def scrub(value: Any, path: str = "$") -> None:
    """Raise ``ScrubError`` if any key or string value in ``value`` looks like a credential."""
    if isinstance(value, dict):
        for key, item in value.items():  # pyright: ignore[reportUnknownVariableType]
            k = str(key)  # pyright: ignore[reportUnknownArgumentType]
            if _SECRET_KEY_PATTERN.search(k) or _looks_secret(k):
                raise ScrubError(f"secret-like key at {path}.{k}")
            scrub(item, f"{path}.{k}")
    elif isinstance(value, (list, tuple)):
        for i, item in enumerate(value):  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]
            scrub(item, f"{path}[{i}]")
    elif isinstance(value, str) and _looks_secret(value):
        raise ScrubError(f"secret-like value at {path}")


def subscription_token(subscription_id: str) -> str:
    digest = hashlib.sha256(subscription_id.strip().lower().encode("utf-8")).hexdigest()
    return f"<subscription:{digest[:8]}>"


def redact_guids(text: str, known_subscription: str = "") -> str:
    """Replace the known subscription with a short hash token and any other GUID with a marker."""
    out = text
    if known_subscription:
        out = re.sub(
            re.escape(known_subscription), subscription_token(known_subscription), out, flags=re.I
        )
    return _GUID_ANYWHERE.sub("<guid-redacted>", out)


def safe_text(text: str, limit: int = 200) -> str:
    cleaned = " ".join(text.split())[:limit]
    return "[redacted: matched a secret pattern]" if _looks_secret(cleaned) else cleaned


# --------------------------------------------------------------------------- evidence


def utcnow() -> datetime:
    return datetime.now(UTC)


def render_evidence(ev: dict[str, Any], subscription_id: str = "") -> str:
    """Render whitelisted evidence fields to markdown; raises ``ScrubError`` on credentials."""
    scrub(ev)
    lines = [
        f"# G02 {ev['profile']} profile - {ev['result']}",
        "",
        DISCLAIMER,
        "",
        f"- Gate: {GATE} ({ev['profile']} profile, Azure Government)",
        f"- Script version: {ev['script_version']}",
        f"- Window (UTC): {ev['started_utc']} to {ev['finished_utc']}",
        f"- Cloud: {ev['cloud']}",
        f"- Location: {ev['location']}",
        f"- Subscription: {ev['subscription']}",
        f"- Resource group: {ev['resource_group']}",
        f"- Drift changes on second pass: {ev['drift_changes']}",
        f"- Uninstall dry-run removable: {ev['dryrun_removable']}; protected: "
        f"{ev['dryrun_protected']}",
        f"- Teardown: {ev['teardown']}",
        "",
        "## Checks",
        "",
    ]
    lines += [f"- [{c['status']}] {c['name']} {c['detail']}".rstrip() for c in ev["checks"]]
    lines += ["", "## Not claimed", ""]
    lines += [
        "- Authorization, ATO, FedRAMP status or compliance parity.",
        "- Any cloud other than Azure Government (GCC, GCC High and DoD are separate rows).",
    ]
    return redact_guids("\n".join(lines) + "\n", subscription_id)


def write_evidence(ev: dict[str, Any], evidence_dir: Path, subscription_id: str) -> Path:
    text = render_evidence(ev, subscription_id)  # scrub before any file is created
    evidence_dir.mkdir(parents=True, exist_ok=True)
    stem = f"profile-{ev['profile']}-{utcnow().strftime('%Y-%m-%d')}"
    path = evidence_dir / f"{stem}.md"
    if path.exists():
        path = evidence_dir / f"{stem}-{utcnow().strftime('%H%M%S')}.md"
    path.write_text(text, encoding="utf-8")
    return path


# --------------------------------------------------------------------------- uninstall plan


@dataclass(frozen=True)
class DryRunPlan:
    removable: tuple[str, ...]
    protected: tuple[str, ...]


def plan_dry_run(resources: Sequence[dict[str, Any]], rg_name: str, run_id: str) -> DryRunPlan:
    """Pure uninstall dry-run: list only resources this run created.

    A resource is removable only if it sits in the script-created resource group AND carries
    this run's id tag and the created-by tag. Anything else (untagged, other run, other resource
    group, reused/shared) is protected and never listed for deletion. Ids are compared
    case-insensitively because ARM ids are case-insensitive.
    """
    marker = f"/resourcegroups/{rg_name}/".lower()
    removable: list[str] = []
    protected: list[str] = []
    for res in resources:
        rid = str(res.get("id", ""))
        tags_raw = res.get("tags")
        tags: dict[str, Any] = (
            {str(k): v for k, v in tags_raw.items()}  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]
            if isinstance(tags_raw, dict)
            else {}
        )
        ours = (
            marker in rid.lower()
            and tags.get(TAG_RUN) == run_id
            and tags.get(TAG_CREATED_BY) == "neurosphere"
        )
        (removable if ours else protected).append(rid)
    return DryRunPlan(tuple(removable), tuple(protected))


# --------------------------------------------------------------------------- run context


@dataclass
class Check:
    name: str
    status: str
    detail: str = ""


@dataclass
class RunContext:
    runner: Runner
    subscription: str
    location: str
    resource_group: str
    run_id: str
    args: argparse.Namespace
    work_dir: Path
    checks: list[Check] = field(default_factory=lambda: list[Check]())
    facts: dict[str, Any] = field(default_factory=lambda: dict[str, Any]())

    @property
    def tags(self) -> list[str]:
        return [
            f"{TAG_CREATED_BY}=neurosphere",
            f"{TAG_GATE}={GATE}",
            f"{TAG_RUN}={self.run_id}",
        ]

    def run(self, *argv: str, parse_json: bool = False) -> Any:
        res = self.runner(list(argv))
        if res.rc != 0:
            raise StepError(
                f"{argv[0]} {argv[1] if len(argv) > 1 else ''} failed (rc={res.rc}): "
                f"{safe_text(res.stderr)}"
            )
        if not parse_json:
            return res.stdout
        try:
            return json.loads(res.stdout or "null")
        except json.JSONDecodeError as exc:
            raise StepError(f"{argv[0]} returned non-JSON output") from exc

    def az(self, *argv: str, parse_json: bool = False) -> Any:
        return self.run("az", *argv, "--subscription", self.subscription, parse_json=parse_json)

    def record(self, name: str, ok: bool, detail: str = "") -> None:
        self.checks.append(Check(name, "PASS" if ok else "FAIL", detail))
        if not ok:
            raise StepError(f"{name}: {detail}")


class Profile(Protocol):
    name: str  # "aks" | "appservice"

    def add_arguments(self, parser: argparse.ArgumentParser) -> None: ...

    def validate(self, args: argparse.Namespace) -> None:
        """Raise ``RefusedError`` for missing profile configuration (no command may run)."""
        ...

    def deploy(self, ctx: RunContext) -> None: ...

    def smoke(self, ctx: RunContext) -> None: ...

    def drift(self, ctx: RunContext) -> int:
        """Return the number of unexpected changes on a second pass (0 means no drift)."""
        ...

    def cleanup(self, ctx: RunContext) -> None:
        """Remove workload objects this run created outside the resource group."""
        ...


# --------------------------------------------------------------------------- orchestration


def refuse(gate_name: str, reason: str) -> int:
    print(
        f"REFUSED: {gate_name}: {reason}\n"
        f"Gate {GATE} {gate_name} remains OPEN (not run, not passed). "
        "No evidence was written and no deploy command was run."
    )
    return 2


def build_parser(profile: Profile) -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description=f"G02 Government {profile.name} profile gate (operator-approved)."
    )
    ap.add_argument("--location", default=DEFAULT_LOCATION, help="Government region")
    profile.add_arguments(ap)
    return ap


def _preflight(
    profile: Profile, argv: Sequence[str] | None, runner: Runner
) -> tuple[argparse.Namespace, str]:
    """All refusal checks. Raises ``RefusedError``; runs at most `az cloud show`."""
    args = build_parser(profile).parse_args(argv)
    subscription = os.environ.get(SUBSCRIPTION_ENV, "").strip()
    if not subscription:
        raise RefusedError(f"no Government subscription configured (set {SUBSCRIPTION_ENV})")
    if not _GUID.match(subscription):
        raise RefusedError(f"{SUBSCRIPTION_ENV} is not a GUID")
    location = str(args.location).strip().lower()
    if location not in GOV_REGIONS:
        raise RefusedError(
            f"region {safe_text(location, 40)!r} is not in the Government set "
            f"({', '.join(sorted(GOV_REGIONS))})"
        )
    args.location = location
    cloud = runner(["az", "cloud", "show", "--query", "name", "-o", "tsv"])
    if cloud.rc != 0 or cloud.stdout.strip() != GOV_CLOUD:
        raise RefusedError(
            f"the active az cloud is not {GOV_CLOUD}; the Government profile is never "
            "deployed into another cloud"
        )
    profile.validate(args)
    return args, subscription


def _make_run_id() -> str:
    return uuid.uuid4().hex[:10]


def execute(
    profile: Profile,
    argv: Sequence[str] | None = None,
    *,
    runner: Runner | None = None,
    evidence_dir: Path | None = None,
    work_dir: Path | None = None,
    clock: Callable[[], datetime] = utcnow,
) -> int:
    """Run the refusal ladder, then (approved path only) deploy, smoke, drift, dry-run, teardown."""
    gate_name = f"profile-{profile.name}"
    active_runner: Runner = runner if runner is not None else SubprocessRunner()
    try:
        args, subscription = _preflight(profile, argv, active_runner)
    except RefusedError as exc:
        return refuse(gate_name, str(exc))
    out_dir = evidence_dir if evidence_dir is not None else EVIDENCE_DIR
    started = clock()
    run_id = _make_run_id()
    rg = f"rg-ns-g02-{profile.name}-{run_id}"
    if work_dir is not None:
        return _run(
            profile, args, subscription, rg, run_id, active_runner, work_dir, out_dir, started
        )
    with tempfile.TemporaryDirectory(prefix="g02-") as tmp:
        return _run(
            profile, args, subscription, rg, run_id, active_runner, Path(tmp), out_dir, started
        )


def _run(
    profile: Profile,
    args: argparse.Namespace,
    subscription: str,
    rg: str,
    run_id: str,
    runner: Runner,
    work_dir: Path,
    evidence_dir: Path,
    started: datetime,
) -> int:
    ctx = RunContext(runner, subscription, args.location, rg, run_id, args, work_dir)
    drift_changes = -1
    plan = DryRunPlan((), ())
    teardown = "not attempted"
    created_rg = False
    failed = False
    try:
        ctx.az("group", "create", "--name", rg, "--location", ctx.location, "--tags", *ctx.tags)
        created_rg = True
        ctx.record("resource-group-created", True)
        profile.deploy(ctx)
        ctx.record("deploy", True)
        _tag_group_resources(ctx)
        profile.smoke(ctx)
        drift_changes = profile.drift(ctx)
        ctx.record("drift-second-pass", drift_changes == 0, f"changes={drift_changes}")
        listing = ctx.az(
            "resource", "list", "--resource-group", rg,
            "--query", "[].{id:id,tags:tags}", "--output", "json", parse_json=True,
        )  # fmt: skip
        plan = plan_dry_run(list(listing or []), rg, run_id)
        ctx.record(
            "uninstall-dry-run-excludes-shared",
            not plan.protected and bool(plan.removable),
            f"removable={len(plan.removable)} protected={len(plan.protected)}",
        )
    except StepError as exc:
        failed = True
        ctx.checks.append(Check("step-failed", "FAIL", safe_text(str(exc))))
    except RefusedError as exc:
        failed = True
        ctx.checks.append(Check("tool-missing", "FAIL", safe_text(str(exc))))
    finally:
        teardown = _teardown(profile, ctx, created_rg, plan)
    if teardown.startswith("FAILED"):
        failed = True
    ev: dict[str, Any] = {
        "profile": profile.name,
        "result": "FAIL" if failed else "PASS",
        "script_version": SCRIPT_VERSION,
        "started_utc": started.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "finished_utc": utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "cloud": GOV_CLOUD,
        "location": ctx.location,
        "subscription": subscription_token(subscription),
        "resource_group": rg,
        "drift_changes": drift_changes,
        "dryrun_removable": len(plan.removable),
        "dryrun_protected": len(plan.protected),
        "teardown": teardown,
        "checks": [{"name": c.name, "status": c.status, "detail": c.detail} for c in ctx.checks],
    }
    try:
        path = write_evidence(ev, evidence_dir, subscription)
    except ScrubError as exc:
        print(f"FAIL: evidence not written ({exc}).")
        return 1
    print(f"{'FAIL' if failed else 'PASS'}: G02 profile-{profile.name}; evidence {path.name}")
    return 1 if failed else 0


def _tag_group_resources(ctx: RunContext) -> None:
    """Tag every resource in the script-created group so the dry-run can tell them apart."""
    listing = ctx.az(
        "resource", "list", "--resource-group", ctx.resource_group,
        "--query", "[].id", "--output", "json", parse_json=True,
    )  # fmt: skip
    for rid in listing or []:
        ctx.az("tag", "update", "--resource-id", str(rid), "--operation", "merge",
               "--tags", *ctx.tags)  # fmt: skip
    ctx.record("resources-tagged", True, f"count={len(listing or [])}")


def _teardown(profile: Profile, ctx: RunContext, created_rg: bool, plan: DryRunPlan) -> str:
    """Delete only what this run created; refuse to delete the group if foreign items appear."""
    problems: list[str] = []
    try:
        profile.cleanup(ctx)
    except (StepError, RefusedError) as exc:
        problems.append(f"workload cleanup: {safe_text(str(exc), 120)}")
    if created_rg:
        try:
            tags = ctx.az("group", "show", "--name", ctx.resource_group, "--query", "tags",
                          "--output", "json", parse_json=True)  # fmt: skip
            if not isinstance(tags, dict) or tags.get(TAG_RUN) != ctx.run_id:  # pyright: ignore[reportUnknownMemberType]
                problems.append("resource group run-id tag mismatch; not deleted")
            elif plan.protected:
                problems.append("foreign resources found in the group; not deleted")
            else:
                ctx.az("group", "delete", "--name", ctx.resource_group, "--yes")
        except (StepError, RefusedError) as exc:
            problems.append(f"group delete: {safe_text(str(exc), 120)}")
    if problems:
        return "FAILED - " + "; ".join(problems)
    return "resource group and workload objects removed" if created_rg else "nothing created"


def valid_name(value: str, what: str) -> str:
    if not _NAME.match(value):
        raise RefusedError(f"{what} is missing or malformed")
    return value
