"""Check planning-document alignment and repository hygiene. Not a product test.

Exit code 1 with a list of failures, or 0 with a PASS line. Also runs under
pytest via tests/test_planning_alignment.py.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

ROOT = Path(__file__).resolve().parents[1]
MASTER = ROOT / "PRPs" / "PRP-MASTER-neurosphere.md"
BACKLOG = ROOT / "PRPs" / "backlog"
DOCS = [
    "docs/PRD.md",
    "PRP.md",
    "docs/ARCHITECTURE.md",
    "CLAUDE.md",
    "AGENTS.md",
    "README.md",
    "docs/RESEARCH-AND-GATES.md",
]
PRP_FILE_RE = re.compile(r"^PRP-(\d{2})-[a-z0-9-]+\.md$")
FRONTMATTER_KEYS = ("name", "status", "review", "created", "model", "phase", "ns", "depends_on")
CREDENTIAL_PATH_RE = re.compile(
    r"(^|/)\.env($|\.)|\.pem$|\.key$|\.pfx$|\.p12$|credentials\.json$|service-account.*\.json$|(^|/)secrets/",
    re.IGNORECASE,
)

failures: list[str] = []


def fail(msg: str) -> None:
    failures.append(msg)


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8-sig")


def frontmatter(text: str) -> dict[str, str]:
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    block = text[3:end]
    out: dict[str, str] = {}
    for line in block.splitlines():
        if ":" in line and not line.startswith(" "):
            key, _, value = line.partition(":")
            out[key.strip()] = value.strip()
    return out


def check_core_docs() -> dict[str, str]:
    texts: dict[str, str] = {}
    for name in DOCS:
        path = ROOT / name
        if not path.exists():
            fail(f"missing artifact: {name}")
            continue
        text = read(name)
        if not text.strip():
            fail(f"empty artifact: {name}")
        if text.count("```") % 2:
            fail(f"unbalanced code fences: {name}")
        for banned in ("No Microsoft Fabric / OneLake", "No real-data ingestion paths"):
            if banned in text:
                fail(f"superseded instruction present in {name}: {banned!r}")
        texts[name] = text
    for index in range(1, 11):
        tag = f"NS-{index:02d}"
        if tag not in texts.get("docs/PRD.md", ""):
            fail(f"{tag} missing from docs/PRD.md")
    for platform in ("Fabric", "Synapse", "Databricks"):
        for name in ("docs/PRD.md", "PRP.md", "CLAUDE.md"):
            if platform not in texts.get(name, ""):
                fail(f"{platform} not mentioned in {name}")
    arch = texts.get("docs/ARCHITECTURE.md", "")
    mermaid = arch.count("```mermaid")
    if mermaid != 5:
        fail(f"docs/ARCHITECTURE.md has {mermaid} mermaid blocks, expected 5")
    for name in ("README.md", "docs/RESEARCH-AND-GATES.md"):
        six = re.search(r"\bsix\b.*\bMermaid\b|\bMermaid\b.*\bsix\b", texts.get(name, ""), re.I)
        if six:
            fail(f"{name} still claims six Mermaid diagrams; there are five")
    return texts


def check_json_configs() -> None:
    for name in (".claude/settings.json", ".mcp.json", "infra/compose/eventhubs.config.json"):
        path = ROOT / name
        if not path.exists():
            fail(f"missing config: {name}")
            continue
        try:
            json.loads(path.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError as exc:
            fail(f"invalid JSON in {name}: {exc}")


def check_workflows() -> None:
    wf_dir = ROOT / ".github" / "workflows"
    if not wf_dir.is_dir():
        fail("missing .github/workflows")
        return
    for wf in wf_dir.glob("*.yml"):
        text = wf.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), 1):
            stripped = line.lstrip()
            allowed = stripped.startswith("#") or "no-match-ok" in line
            if re.search(r"\|\|\s*true", line) and not allowed:
                fail(f"{wf.relative_to(ROOT)}:{lineno} suppresses a failure with '|| true'")


def check_tracked_paths() -> None:
    try:
        out = subprocess.run(
            ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return
    for path in out.splitlines():
        if path == ".env.example":
            continue
        if CREDENTIAL_PATH_RE.search(path):
            fail(f"credential-shaped path is tracked: {path}")
    for legacy in ("data/synthetic_data.py", "services/dab/README.md", "docs/ZERO-MOVE.md"):
        if legacy in out.splitlines():
            fail(f"legacy demo file still tracked: {legacy}")


def check_prps(texts: dict[str, str]) -> None:
    if not MASTER.exists():
        fail("missing PRPs/PRP-MASTER-neurosphere.md")
        return
    master = MASTER.read_text(encoding="utf-8")
    index_ids = set(re.findall(r"\bPRP-(\d{2})\b", master))
    if not index_ids:
        fail("master index lists no PRP ids")
    backlog = {}
    for path in BACKLOG.glob("PRP-*.md"):
        m = PRP_FILE_RE.match(path.name)
        if not m:
            fail(f"PRP file name not in PRP-NN-kebab.md form: {path.name}")
            continue
        backlog[m.group(1)] = path
    for other in ("active", "shipped"):
        for path in (ROOT / "PRPs" / other).glob("PRP-*.md"):
            m = PRP_FILE_RE.match(path.name)
            if m:
                backlog[m.group(1)] = path
    for pid in sorted(index_ids - set(backlog)):
        fail(f"PRP-{pid} is in the master index but has no file under PRPs/")
    for pid in sorted(set(backlog) - index_ids):
        fail(f"PRP-{pid} exists under PRPs/ but is not in the master index")

    ns_covered: set[str] = set()
    for _pid, path in sorted(backlog.items()):
        text = path.read_text(encoding="utf-8")
        fm = frontmatter(text)
        rel = path.relative_to(ROOT)
        for key in FRONTMATTER_KEYS:
            if key not in fm:
                fail(f"{rel}: frontmatter missing '{key}'")
        if fm.get("review") not in ("required", "none"):
            fail(f"{rel}: review must be 'required' or 'none'")
        if fm.get("model") not in ("sonnet", "opus", "haiku"):
            fail(f"{rel}: model must be sonnet|opus|haiku")
        if "## Implementation blueprint" not in text:
            fail(f"{rel}: missing '## Implementation blueprint'")
        if "Owned files" not in text:
            fail(f"{rel}: no work item declares owned files")
        if "verify-gates.ps1" not in text and "run-tests.ps1" not in text:
            fail(f"{rel}: no gate command")
        if "\\.claude" in text or ".claude\\hooks" in text:
            fail(f"{rel}: gate path uses backslashes; use forward slashes")
        if text.count("```") % 2:
            fail(f"{rel}: unbalanced code fences")
        ns_covered.update(re.findall(r"\bNS-(\d{2})\b", fm.get("ns", "")))
    for index in range(1, 11):
        tag = f"{index:02d}"
        if backlog and tag not in ns_covered:
            fail(f"NS-{tag} is not covered by any PRP frontmatter 'ns' field")
    check_status_table()


def check_status_table() -> None:
    """The master index status table must match the PRPs/ directory layout."""
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "prp_status.py"), "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        fail(result.stdout.strip() or result.stderr.strip() or "prp_status.py --check failed")


def main() -> int:
    texts = check_core_docs()
    check_json_configs()
    check_workflows()
    check_tracked_paths()
    check_prps(texts)
    if failures:
        print("FAIL: planning validation")
        for item in failures:
            print(f"  - {item}")
        return 1
    print(
        "PASS: baseline artifacts, NS-01..10 mapping, platform choices, JSON, fences, "
        "workflow hygiene, tracked paths, PRP index coverage"
    )
    print("NOT VALIDATED: Mermaid render, live cloud adapters, compliance, product tests or DR")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
