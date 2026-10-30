"""Static checks for docs/runbooks and docs/walkthroughs (PRP-25 item 3).

Parses fenced shell commands and checks that what they reference exists in the repository.
Nothing here runs a command.
"""

from __future__ import annotations

import json
import re
import shlex
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
RUNBOOKS = ROOT / "docs" / "runbooks"
WALKTHROUGHS = ROOT / "docs" / "walkthroughs"
NEW_USER_TEST = RUNBOOKS / "new-user-test.md"

REQUIRED_RUNBOOKS = ["install", "migration", "operations", "dr", "security"]
PERSONAS = ["viewer", "analyst", "steward", "admin", "auditor"]
DRAFT_BANNER = "**Status: DRAFT.**"

FENCE = re.compile(r"```(?:bash|sh|shell|console)?\n(.*?)```", re.DOTALL)
LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
SCENARIO = re.compile(r"^Sandbox scenario: `([a-z_]+)`", re.MULTILINE)
INLINE_ROUTE = re.compile(r"`(/[a-z][a-z0-9/-]*)`")
PATH_SUFFIXES = (".py", ".sh", ".json", ".ps1", ".md", ".yml", ".yaml")


def _docs() -> list[Path]:
    return sorted(RUNBOOKS.glob("*.md")) + sorted(WALKTHROUGHS.glob("*.md"))


def _make_targets() -> set[str]:
    targets: set[str] = set()
    for mk in [ROOT / "Makefile", ROOT / "scripts" / "sandbox" / "sandbox.mk"]:
        text = mk.read_text(encoding="utf-8")
        targets.update(re.findall(r"^([A-Za-z0-9_-]+):", text, re.MULTILINE))
        for line in text.splitlines():
            if line.startswith(".PHONY:"):
                targets.update(line.split(":", 1)[1].split())
    return targets


def _commands(path: Path) -> list[str]:
    cmds: list[str] = []
    for block in FENCE.findall(path.read_text(encoding="utf-8")):
        for line in block.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            cmds.extend(part.strip() for part in line.split("&&") if part.strip())
    return cmds


def _all_commands() -> list[tuple[Path, str]]:
    return [(p, c) for p in _docs() for c in _commands(p)]


def test_docs_exist() -> None:
    assert _docs(), "no runbooks or walkthroughs found"
    assert NEW_USER_TEST.is_file()


@pytest.mark.parametrize("path,cmd", _all_commands(), ids=lambda v: str(v)[-60:])
def test_command_references_exist(path: Path, cmd: str) -> None:
    assert "\\" not in cmd, f"{path.name}: backslash in command: {cmd}"
    tokens = shlex.split(cmd, posix=True)
    if tokens[:1] == ["export"]:
        return
    targets = _make_targets()
    if tokens[0] == "make":
        for tok in tokens[1:]:
            if "=" in tok or tok.startswith("-"):
                continue
            assert tok in targets, f"{path.name}: unknown make target {tok!r}"
    if tokens[0] == "pnpm" and len(tokens) == 2:
        scripts = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))["scripts"]
        assert tokens[1] in scripts or tokens[1] in {"install"}, f"{path.name}: {cmd}"
    for tok in tokens[1:]:
        if tok.startswith(("-", "http", "<")) or "<" in tok or "=" in tok:
            continue
        if tok.endswith(PATH_SUFFIXES) and "/" in tok and not tok.startswith("temp/"):
            assert (ROOT / tok).exists(), f"{path.name}: missing path {tok}"
        if re.match(r"^(tests|packages|infra|scripts|services)/", tok):
            assert (ROOT / tok).exists(), f"{path.name}: missing path {tok}"


def _test_completed() -> bool:
    text = NEW_USER_TEST.read_text(encoding="utf-8")

    def field(name: str) -> str:
        m = re.search(rf"^- {name}: (.*)$", text, re.MULTILINE)
        return m.group(1).strip() if m else "OPEN"

    return field("Tester") != "OPEN" and field("Date") != "OPEN" and field("Result") == "PASSED"


def test_runbooks_are_draft_until_new_user_test_recorded() -> None:
    for name in REQUIRED_RUNBOOKS:
        path = RUNBOOKS / f"{name}.md"
        assert path.is_file(), f"missing runbook {name}"
        if not _test_completed():
            assert DRAFT_BANNER in path.read_text(encoding="utf-8"), f"{name}: no DRAFT banner"


def test_new_user_test_template_has_fields_and_no_fabricated_result() -> None:
    text = NEW_USER_TEST.read_text(encoding="utf-8")
    for field in ["Tester", "Date", "Deviations", "Result"]:
        assert re.search(rf"^- {field}[^:]*: ", text, re.MULTILINE), f"missing field {field}"


@pytest.mark.parametrize("persona", PERSONAS)
def test_persona_walkthrough_references_real_scenario(persona: str) -> None:
    path = WALKTHROUGHS / f"{persona}.md"
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    match = SCENARIO.search(text)
    assert match, f"{persona}: no 'Sandbox scenario:' line"
    scenario = match.group(1)
    sandbox = ROOT / "sandbox"
    corpus = "".join(
        p.read_text(encoding="utf-8")
        for p in list(sandbox.glob("*.py")) + list((sandbox / "stack").glob("*.json"))
    )
    assert scenario in corpus or (sandbox / f"{scenario}.py").is_file(), scenario
    assert (sandbox / "stack" / "personas.json").is_file()
    slug = f"`{persona}`"
    assert slug in text
    personas = json.loads((sandbox / "stack" / "personas.json").read_text(encoding="utf-8"))
    assert persona in {p["slug"] for p in personas["personas"]}
    assert "make seed-stack" in text, f"{persona}: no seed command"


def test_walkthrough_routes_exist_in_route_manifest() -> None:
    manifest = json.loads(
        (ROOT / "frontend" / "src" / "app" / "route-manifest.json").read_text(encoding="utf-8")
    )
    routes = set(manifest["routes"])
    for path in sorted(WALKTHROUGHS.glob("*.md")):
        for route in INLINE_ROUTE.findall(path.read_text(encoding="utf-8")):
            if route.startswith(("/workspaces", "/dashboards", "/catalog", "/map")) or route in {
                "/audit",
                "/actions",
                "/actions/detail",
                "/admin/execution-control",
                "/mcp-admin",
                "/sandbox",
                "/gateways",
                "/deploy/capabilities",
                "/reconciliation",
                "/replay/traces",
                "/reports",
                "/review",
                "/review/item",
                "/recommendations",
            }:
                assert route in routes, f"{path.name}: unknown route {route}"


def test_no_em_dashes_and_no_backslash_paths() -> None:
    for path in _docs():
        text = path.read_text(encoding="utf-8")
        assert "—" not in text, f"{path.name}: em-dash"
        for tok in re.findall(r"`([^`\n]+)`", text):
            assert "\\" not in tok, f"{path.name}: backslash in {tok!r}"


def test_no_compliance_claims_or_bypass_language() -> None:
    for path in _docs():
        low = path.read_text(encoding="utf-8").lower()
        for banned in ["fedramp authorized", "fedramp-authorized", "compliance parity achieved"]:
            assert banned not in low, f"{path.name}: {banned}"
        assert "bypass" not in low.replace("no unrestricted bypass", ""), path.name


def test_relative_links_resolve() -> None:
    for path in _docs():
        for target in LINK.findall(path.read_text(encoding="utf-8")):
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            file_part = target.split("#", 1)[0]
            assert (path.parent / file_part).resolve().exists(), f"{path.name}: 404 {target}"
