"""The docs nav is an explicit publish allowlist (PRP-25 item 1)."""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"

# Paths that must never be published, relative to docs/.
FORBIDDEN_PREFIXES = ("evidence/", "compliance/", "security/", "ops/", "design/", "deploy/")
FORBIDDEN_NAMES = ("RESEARCH-AND-GATES.md", "DECISIONS-LOG.md", "PRD.md")
# Top-level docs/ entries that exclude_docs may re-include.
ALLOWED_TOP_LEVEL = {"index.md", "adr"}


def _config() -> dict:
    text = (ROOT / "mkdocs.yml").read_text(encoding="utf-8")
    return yaml.safe_load(text)


def _nav_pages(node: object) -> list[str]:
    if isinstance(node, str):
        return [node]
    if isinstance(node, list):
        return [p for item in node for p in _nav_pages(item)]
    if isinstance(node, dict):
        return [p for value in node.values() for p in _nav_pages(value)]
    return []


def test_nav_pages_exist() -> None:
    pages = _nav_pages(_config()["nav"])
    assert pages, "nav must list pages explicitly"
    missing = [p for p in pages if not (DOCS / p).is_file()]
    assert not missing, f"nav pages missing from docs/: {missing}"


def test_nav_pages_are_allowlisted_and_not_internal() -> None:
    for page in _nav_pages(_config()["nav"]):
        assert page.split("/")[0] in {"index.md", "adr"}, f"{page} is outside the allowlist"
        assert not page.startswith(FORBIDDEN_PREFIXES), f"{page} is internal"
        assert Path(page).name not in FORBIDDEN_NAMES, f"{page} is internal planning"


def test_exclude_docs_reincludes_only_allowlist() -> None:
    lines = [ln.strip() for ln in _config()["exclude_docs"].splitlines() if ln.strip()]
    assert "/*" in lines, "everything at the top of docs/ must be excluded first"
    reincluded = {ln[2:].rstrip("/") for ln in lines if ln.startswith("!/")}
    assert reincluded == ALLOWED_TOP_LEVEL
    assert not any("evidence" in ln for ln in lines if ln.startswith("!"))


def test_strict_mode_is_on() -> None:
    assert _config()["strict"] is True


def test_workflow_has_no_swallowed_failures_or_secrets() -> None:
    text = (ROOT / ".github/workflows/docs.yml").read_text(encoding="utf-8")
    assert "|| true" not in text
    assert "secrets." not in text
    assert "--strict" in text
