"""Assemble changelog fragments (changelog.d/*.md) into the CHANGELOG.md [Unreleased] block.

Usage:
    python scripts/changelog_assemble.py --check     # validate fragments, exit 1 on a problem
    python scripts/changelog_assemble.py --preview   # print the assembled changelog, change nothing
    python scripts/changelog_assemble.py --write     # splice fragments in and delete them

A fragment is named `<PRP file stem>.md` (PRP-NN-kebab-slug) or `issue-<n>.md` and contains only
Keep a Changelog headings (`### Added` ...) with list items under them. Fragments are processed
in sorted file-name order. Every original byte of the changelog is kept; only lines are inserted.

Standard library only. The Unreleased boundary rule is reused from scripts/release/changelog.py.
"""

from __future__ import annotations

import argparse
import importlib.util
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_SPEC = importlib.util.spec_from_file_location(
    "_ns_release_changelog", ROOT / "scripts" / "release" / "changelog.py"
)
assert _SPEC is not None and _SPEC.loader is not None
_release = importlib.util.module_from_spec(_SPEC)
sys.modules["_ns_release_changelog"] = _release
_SPEC.loader.exec_module(_release)

SECTION_ORDER: tuple[str, ...] = _release.SECTION_ORDER
UNRELEASED_RE: re.Pattern[str] = _release.UNRELEASED_RE
NEXT_HEADING_RE: re.Pattern[str] = _release.NEXT_HEADING_RE

NAME_RE = re.compile(r"^(PRP-\d{2}-[a-z0-9-]+|issue-\d+)\.md$")
HEADING_RE = re.compile(r"^### (.+?)[ \t]*$")
ITEM_RE = re.compile(r"^\s*(?:[-*+]|\d+\.)\s+\S")


def parse_fragment(name: str, text: str) -> tuple[dict[str, list[str]], list[str]]:
    """Return ({section: lines}, problems) for one fragment."""
    problems: list[str] = []
    if not NAME_RE.match(name):
        problems.append(f"{name}: file name must be PRP-NN-<slug>.md or issue-<n>.md")
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for raw in text.splitlines():
        line = raw.rstrip()
        if line.startswith("## "):
            problems.append(f"{name}: '## ' headings are not allowed: {line!r}")
            continue
        m = HEADING_RE.match(line)
        if m:
            title = m.group(1)
            if title not in SECTION_ORDER:
                problems.append(f"{name}: heading '### {title}' is not a Keep a Changelog section")
                current = None
            else:
                current = title
                sections.setdefault(title, [])
            continue
        if not line.strip():
            if current is not None and sections[current]:
                sections[current].append("")
            continue
        if current is None:
            problems.append(f"{name}: content before any '### ' heading: {line!r}")
            continue
        sections[current].append(line)
    for title, lines in sections.items():
        while lines and lines[-1] == "":
            lines.pop()
        if not any(ITEM_RE.match(x) for x in lines):
            problems.append(f"{name}: section '### {title}' has no list item")
    if not sections and not problems:
        problems.append(f"{name}: fragment has no section")
    return sections, problems


def list_fragments(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    return sorted(
        p for p in directory.glob("*.md") if p.is_file() and p.name.lower() != "readme.md"
    )


def load_fragments(directory: Path) -> tuple[list[tuple[Path, dict[str, list[str]]]], list[str]]:
    loaded: list[tuple[Path, dict[str, list[str]]]] = []
    problems: list[str] = []
    for path in list_fragments(directory):
        sections, probs = parse_fragment(path.name, path.read_text(encoding="utf-8"))
        problems.extend(probs)
        loaded.append((path, sections))
    return loaded, problems


def splice(text: str, fragments: list[dict[str, list[str]]]) -> str:
    """Insert fragment lines into the [Unreleased] block of `text`, keeping all other bytes."""
    if "\r\n" in text and "\n" not in text.replace("\r\n", ""):
        # UNRELEASED_RE anchors on '$', which does not match before '\r'; splice as LF, restore.
        return splice(text.replace("\r\n", "\n"), fragments).replace("\n", "\r\n")
    unreleased = UNRELEASED_RE.search(text)
    if unreleased is None:
        raise ValueError("CHANGELOG.md has no '## [Unreleased]' heading")
    nxt = NEXT_HEADING_RE.search(text, unreleased.end())
    end = nxt.start() if nxt else len(text)
    nl = "\n"

    block = text[unreleased.end() : end]
    lines = block.splitlines(keepends=True)
    # Locate '### X' headings inside the block.
    heads: dict[str, int] = {}
    for i, ln in enumerate(lines):
        m = HEADING_RE.match(ln.rstrip("\r\n"))
        if m and m.group(1) in SECTION_ORDER and m.group(1) not in heads:
            heads[m.group(1)] = i

    for title in SECTION_ORDER:
        add: list[str] = []
        for frag in fragments:
            if title in frag:
                add.extend(frag[title])
        if not add:
            continue
        new_lines = [x + nl if x else nl for x in add]
        if title in heads:
            start = heads[title]
            later = [i for t, i in heads.items() if i > start]
            stop = min(later) if later else len(lines)
            # Insert after the last non-blank line of this section.
            pos = stop
            while pos > start + 1 and not lines[pos - 1].strip():
                pos -= 1
            if pos > 0 and not lines[pos - 1].endswith(("\n", "\r")):
                lines[pos - 1] += nl
            lines[pos:pos] = new_lines
            shift = len(new_lines)
            heads = {t: (i + shift if i >= pos else i) for t, i in heads.items()}
        else:
            # Create the heading in Keep a Changelog order: before the next later-ordered heading.
            order = SECTION_ORDER.index(title)
            later_idx = [i for t, i in heads.items() if SECTION_ORDER.index(t) > order]
            if later_idx:
                pos = min(later_idx)
                chunk = [f"### {title}{nl}", *new_lines, nl]
            else:
                pos = len(lines)
                while pos > 0 and not lines[pos - 1].strip():
                    pos -= 1
                if pos > 0 and not lines[pos - 1].endswith(("\n", "\r")):
                    lines[pos - 1] += nl
                chunk = [nl, f"### {title}{nl}", *new_lines]
                if pos == 0:
                    chunk = [nl, *chunk[1:]]
            lines[pos:pos] = chunk
            heads = {t: (i + len(chunk) if i >= pos else i) for t, i in heads.items()}
            heads[title] = pos + (0 if later_idx else 1)
    new_block = "".join(lines)
    if not nxt:
        return text[: unreleased.end()] + new_block
    if not new_block.endswith(("\n", "\r")):
        new_block += nl
    return text[: unreleased.end()] + new_block + text[end:]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Assemble changelog.d fragments into CHANGELOG.md.")
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--preview", action="store_true")
    mode.add_argument("--write", action="store_true")
    p.add_argument("--changelog", type=Path, default=ROOT / "CHANGELOG.md")
    p.add_argument("--fragments", type=Path, default=ROOT / "changelog.d")
    return p


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    args = build_parser().parse_args(argv)
    loaded, problems = load_fragments(args.fragments)
    if problems:
        for item in problems:
            print(f"FAIL: {item}")
        return 1
    if args.check:
        print(f"OK: {len(loaded)} changelog fragment(s) well formed")
        return 0
    if not loaded:
        print("no changelog fragments; nothing to do")
        return 0
    with args.changelog.open("r", encoding="utf-8", newline="") as fh:
        original = fh.read()
    try:
        updated = splice(original, [sections for _, sections in loaded])
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.preview:
        sys.stdout.write(updated)
        return 0
    with args.changelog.open("w", encoding="utf-8", newline="") as fh:
        fh.write(updated)
    for path, _ in loaded:
        path.unlink()
    print(f"assembled {len(loaded)} fragment(s) into {args.changelog}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
