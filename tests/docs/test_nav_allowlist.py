"""The docs nav is an explicit publish allowlist (PRP-25 item 1 and round 2 item 5)."""

from __future__ import annotations

import fnmatch
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"

# Paths that must never be published, relative to docs/.
FORBIDDEN_PREFIXES = ("evidence/", "validation/", "design/")
FORBIDDEN_NAMES = ("DECISIONS-LOG.md", "PRD.md")
# Top-level docs/ entries that exclude_docs may re-include.
ALLOWED_TOP_LEVEL = {
    "index.md",
    # Theme CSS/JS plus brand files. `/*` also matches theme files, so this must stay.
    "assets",
    "adr",
    "runbooks",
    "walkthroughs",
    "reference",
    "ARCHITECTURE.md",
    "RESEARCH-AND-GATES.md",
    "dev",
    "ops",
    "release",
    "connectors",
    "deploy",
    "security",
    "compliance",
}
# Only these subfolders of security/ and compliance/ may be published.
PARTIAL_TOP_LEVEL = {"security": "security/runbooks/", "compliance": "compliance/plans/"}
PUBLISHED_PREFIXES = (
    "adr/",
    "runbooks/",
    "walkthroughs/",
    "reference/",
    "dev/",
    "ops/",
    "release/",
    "connectors/",
    "deploy/",
    "security/runbooks/",
    "compliance/plans/",
)
PUBLISHED_FILES = {"index.md", "ARCHITECTURE.md", "RESEARCH-AND-GATES.md"}
# Pages inside a published folder that stay internal. The DoD checklist is a release gate
# whose links must stay relative into evidence/ (tests/release/test_dod_links.py).
UNPUBLISHED_FILES = {"release/dod-checklist.md"}


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


def _rule_matches(rule: str, rel: str) -> bool:
    """Minimal gitignore matcher for the patterns used in exclude_docs.

    A rule matches a file when it matches the file or any ancestor directory.
    Supports a leading slash (anchored), a trailing slash (directories only) and `*`.
    """
    dir_only = rule.endswith("/")
    pattern = rule.strip("/")
    anchored = rule.startswith("/") or "/" in pattern
    parts = rel.split("/")
    for i in range(1, len(parts) + 1):
        if dir_only and i == len(parts):
            continue
        target = "/".join(parts[:i]) if anchored else parts[i - 1]
        if fnmatch.fnmatchcase(target, pattern):
            return True
    return False


def _built_pages() -> set[str]:
    """Markdown pages MkDocs would build: docs/**/*.md minus the exclude_docs rules."""
    rules = [ln.strip() for ln in _config()["exclude_docs"].splitlines() if ln.strip()]
    pages = set()
    for path in DOCS.rglob("*.md"):
        rel = path.relative_to(DOCS).as_posix()
        excluded = False
        for rule in rules:
            negate = rule.startswith("!")
            if _rule_matches(rule[1:] if negate else rule, rel):
                excluded = not negate
        if not excluded:
            pages.add(rel)
    return pages


def _is_allowlisted(page: str) -> bool:
    if page in UNPUBLISHED_FILES:
        return False
    return page in PUBLISHED_FILES or page.startswith(PUBLISHED_PREFIXES)


def test_nav_pages_exist() -> None:
    pages = _nav_pages(_config()["nav"])
    assert pages, "nav must list pages explicitly"
    missing = [p for p in pages if not (DOCS / p).is_file()]
    assert not missing, f"nav pages missing from docs/: {missing}"


def test_nav_pages_are_allowlisted_and_not_internal() -> None:
    for page in _nav_pages(_config()["nav"]):
        assert _is_allowlisted(page), f"{page} is outside the allowlist"
        assert not page.startswith(FORBIDDEN_PREFIXES), f"{page} is internal"
        assert Path(page).name not in FORBIDDEN_NAMES, f"{page} is internal planning"


def test_exclude_docs_reincludes_only_allowlist() -> None:
    lines = [ln.strip() for ln in _config()["exclude_docs"].splitlines() if ln.strip()]
    assert "/*" in lines, "everything at the top of docs/ must be excluded first"
    reincluded = {
        ln[2:].rstrip("/")
        for ln in lines
        if ln.startswith("!/") and ln[2:].rstrip("/").count("/") == 0
    }
    assert reincluded == ALLOWED_TOP_LEVEL
    assert not any("evidence" in ln for ln in lines if ln.startswith("!"))
    for parent, child in PARTIAL_TOP_LEVEL.items():
        assert f"/{parent}/*" in lines, f"{parent}/ must be narrowed to {child}"
        assert f"!/{child}" in lines


def test_built_page_set_equals_allowlist_and_nav() -> None:
    built = _built_pages()
    nav = set(_nav_pages(_config()["nav"]))
    assert built == nav, f"built but not in nav: {built - nav}; in nav but not built: {nav - built}"
    unexpected = {p for p in built if not _is_allowlisted(p)}
    assert not unexpected, f"built pages outside the allowlist: {unexpected}"
    # every allowlisted page on disk is published (nothing silently dropped)
    on_disk = {
        p.relative_to(DOCS).as_posix()
        for p in DOCS.rglob("*.md")
        if _is_allowlisted(p.relative_to(DOCS).as_posix())
    }
    assert built == on_disk, f"allowlisted but not built: {on_disk - built}"


def test_internal_pages_are_not_built() -> None:
    built = _built_pages()
    leaked = {
        p for p in built if p.startswith(FORBIDDEN_PREFIXES) or Path(p).name in FORBIDDEN_NAMES
    }
    assert not leaked, f"internal pages would be published: {leaked}"
    for p in DOCS.glob("evidence/**/*.md"):
        assert p.relative_to(DOCS).as_posix() not in built
    for other in (
        "security/threat-model.md",
        "compliance/responsibility-matrix.md",
        *UNPUBLISHED_FILES,
    ):
        assert other not in built


def test_theme_assets_are_published_and_docs_assets_hold_no_pages() -> None:
    """The site shipped unstyled once: `/*` in exclude_docs also dropped Material's assets."""
    lines = [ln.strip() for ln in _config()["exclude_docs"].splitlines() if ln.strip()]
    assert "!/assets/" in lines, "theme CSS/JS under assets/ would be excluded"
    assert not list((DOCS / "assets").rglob("*.md")), "docs/assets/ is for static files only"
    for css in _config().get("extra_css", []):
        assert (DOCS / css).is_file(), f"extra_css {css} missing from docs/"


def test_strict_mode_is_on() -> None:
    assert _config()["strict"] is True


def test_workflow_has_no_swallowed_failures_or_secrets() -> None:
    text = (ROOT / ".github/workflows/docs.yml").read_text(encoding="utf-8")
    assert "|| true" not in text
    assert "secrets." not in text
    assert "--strict" in text
