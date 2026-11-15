"""Structural freshness check for PRPs/INDEX.md (standard library only).

Every PRP file under PRPs/backlog, PRPs/active and PRPs/shipped must appear exactly once in
PRPs/INDEX.md, in the section matching its directory; backlog rows must carry the priority,
order and review of the file's frontmatter. Byte-exact freshness stays with the kit's
`prp_index.py check`.

Usage: python scripts/prp_index_check.py   (exit 1, one line per problem)
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

DIR_SECTIONS = {
    "backlog": {"Backlog", "Blocked"},
    "active": {"Active", "Blocked"},
    "shipped": {"Shipped", "Abandoned"},
}
ROW_LINK_RE = re.compile(r"\[(?P<name>PRP-[^\]]+)\]\((?P<dir>[a-z]+)/(?P<file>[^)]+)\)")


def _frontmatter(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    if not text.startswith("---"):
        return out
    end = text.find("\n---", 3)
    for line in text[3:end].splitlines():
        if ":" in line and not line.startswith(" "):
            key, _, value = line.partition(":")
            out[key.strip()] = value.strip()
    return out


def check_index(root: Path) -> list[str]:
    problems: list[str] = []
    index = root / "PRPs" / "INDEX.md"
    if not index.exists():
        return ["PRPs/INDEX.md is missing"]
    rows: dict[str, list[tuple[str, str, list[str]]]] = {}
    section = ""
    for line in index.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            section = line[3:].strip()
            continue
        m = ROW_LINK_RE.search(line)
        if not m or not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        rows.setdefault(m.group("name"), []).append((section, m.group("dir"), cells))
        if not (root / "PRPs" / m.group("dir") / m.group("file")).exists():
            problems.append(
                f"INDEX row links to a missing file: {m.group('dir')}/{m.group('file')}"
            )

    seen: set[str] = set()
    for directory, allowed in DIR_SECTIONS.items():
        for path in sorted((root / "PRPs" / directory).glob("PRP-*.md")):
            name = path.stem
            seen.add(name)
            entries = rows.get(name, [])
            if not entries:
                problems.append(f"{name}: missing from PRPs/INDEX.md")
                continue
            if len(entries) > 1:
                problems.append(f"{name}: listed {len(entries)} times in PRPs/INDEX.md")
            sec, link_dir, cells = entries[0]
            if sec not in allowed or link_dir != directory:
                problems.append(
                    f"{name}: listed under '{sec}' ({link_dir}/) but the file is in {directory}/"
                )
                continue
            if directory == "backlog" and sec == "Backlog":
                fm = _frontmatter(path.read_text(encoding="utf-8"))
                if len(cells) < 7:
                    problems.append(f"{name}: INDEX backlog row has too few columns")
                    continue
                for label, want, got in (
                    ("priority", fm.get("priority"), cells[1]),
                    ("order", fm.get("order"), cells[2]),
                    ("review", fm.get("review"), cells[-1]),
                ):
                    if want != got:
                        problems.append(
                            f"{name}: INDEX {label} '{got}' differs from frontmatter '{want}'"
                        )
    for name in sorted(set(rows) - seen):
        problems.append(f"{name}: in PRPs/INDEX.md but no file under backlog/active/shipped")
    return problems


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    problems = check_index(ROOT)
    for item in problems:
        print(f"FAIL: {item}")
    if not problems:
        print("OK: PRPs/INDEX.md matches the PRP files")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
