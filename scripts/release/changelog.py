"""Generate a Keep-a-Changelog section from conventional commits.

Usage:
    python scripts/release/changelog.py --from <ref> --to HEAD
    python scripts/release/changelog.py --from v0.1.0 --to HEAD --version 0.2.0
    python scripts/release/changelog.py --from v0.1.0 --to HEAD --version 0.2.0 --write

Without --write the section is printed to stdout and nothing is modified. With --write the
section is inserted into CHANGELOG.md (see insert_section for the exact insertion rule);
an existing version heading makes the run refuse with exit code 1 and leaves the file alone.

The parser (parse_commit, render_section) is a pure function over CommitRecord values so tests
can feed fixtures. Only the standard library and `git` (list-argument subprocess) are used.
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

FIELD_SEP = "\x1f"
RECORD_SEP = "\x1e"
LOG_FORMAT = f"%H{FIELD_SEP}%P{FIELD_SEP}%s{FIELD_SEP}%b{RECORD_SEP}"

# Keep-a-Changelog 1.1.0 order.
SECTION_ORDER = ("Added", "Changed", "Deprecated", "Removed", "Fixed", "Security")
TYPE_TO_SECTION = {
    "feat": "Added",
    "fix": "Fixed",
    "perf": "Changed",
    "refactor": "Changed",
    "revert": "Removed",
    "deprecate": "Deprecated",
    "sec": "Security",
}
MAINTENANCE_TYPES = frozenset({"chore", "ci", "docs", "test", "build", "style"})

HEADER_RE = re.compile(
    r"^(?P<type>[A-Za-z]+)(?:\((?P<scope>[^)]*)\))?(?P<bang>!)?: (?P<desc>\S.*)$"
)
FOOTER_RE = re.compile(
    r"^(?P<key>BREAKING[ -]CHANGE|Deprecated|Security): (?P<text>\S.*)$", re.IGNORECASE
)
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
UNRELEASED_RE = re.compile(r"^## \[Unreleased\][ \t]*$", re.MULTILINE)
NEXT_HEADING_RE = re.compile(r"^## \[", re.MULTILINE)


@dataclass(frozen=True)
class CommitRecord:
    sha: str
    parents: tuple[str, ...]
    subject: str
    body: str = ""


@dataclass(frozen=True)
class Entry:
    text: str
    breaking: bool = False


@dataclass
class Parsed:
    sections: dict[str, list[Entry]] = field(default_factory=dict)
    breaking_notes: list[str] = field(default_factory=list)
    unclassified: list[str] = field(default_factory=list)
    maintenance: list[str] = field(default_factory=list)


def is_merge(commit: CommitRecord) -> bool:
    return len(commit.parents) > 1


def _format(scope: str | None, desc: str, breaking: bool) -> str:
    prefix = "**BREAKING** " if breaking else ""
    scoped = f"**{scope}:** " if scope else ""
    return f"{prefix}{scoped}{desc}"


def parse_commit(commit: CommitRecord, parsed: Parsed) -> None:
    """Classify one commit into `parsed`. Merge commits are skipped."""
    if is_merge(commit):
        return
    match = HEADER_RE.match(commit.subject)
    if match is None or (
        match["type"].lower() not in TYPE_TO_SECTION
        and match["type"].lower() not in MAINTENANCE_TYPES
    ):
        parsed.unclassified.append(commit.subject)
        return

    ctype = match["type"].lower()
    scope = match["scope"] or None
    desc = match["desc"].strip()
    footers = [m for line in commit.body.splitlines() if (m := FOOTER_RE.match(line.strip()))]
    breaking_footers = [m["text"].strip() for m in footers if m["key"].upper().startswith("BREAK")]
    breaking = match["bang"] is not None or bool(breaking_footers)

    if breaking:
        parsed.breaking_notes.extend(breaking_footers or [desc])

    added = False
    section: str | None
    if scope is not None and scope.lower() == "security":
        section = "Security"
    else:
        section = TYPE_TO_SECTION.get(ctype)
    if section is None and breaking:
        section = "Changed"  # a breaking change is never hidden as maintenance
    if section is not None:
        parsed.sections.setdefault(section, []).append(
            Entry(_format(scope, desc, breaking), breaking)
        )
        added = True

    for m in footers:
        key = m["key"].lower()
        if key == "deprecated":
            parsed.sections.setdefault("Deprecated", []).append(Entry(m["text"].strip()))
            added = True
        elif key == "security":
            parsed.sections.setdefault("Security", []).append(Entry(m["text"].strip()))
            added = True

    if not added:
        parsed.maintenance.append(_format(scope, f"{ctype}: {desc}", False))


def parse_commits(commits: list[CommitRecord]) -> Parsed:
    parsed = Parsed()
    for commit in commits:
        parse_commit(commit, parsed)
    return parsed


def render_section(
    parsed: Parsed,
    version: str | None = None,
    date: str | None = None,
    include_maintenance: bool = False,
) -> str:
    """Render the Keep-a-Changelog markdown for parsed commits (ends with one newline)."""
    heading = f"## [{version}] - {date}" if version else "## [Unreleased]"
    lines = [heading, ""]
    for name in SECTION_ORDER:
        entries = parsed.sections.get(name)
        if entries:
            lines += [f"### {name}", *(f"- {e.text}" for e in entries), ""]
    if parsed.breaking_notes:
        lines += ["### Breaking changes", *(f"- {n}" for n in parsed.breaking_notes), ""]
    if parsed.unclassified:
        lines += ["### Unclassified", *(f"- {s}" for s in parsed.unclassified), ""]
    if include_maintenance and parsed.maintenance:
        lines += ["### Maintenance", *(f"- {m}" for m in parsed.maintenance), ""]
    elif parsed.maintenance:
        n = len(parsed.maintenance)
        noun = "commit" if n == 1 else "commits"
        lines += [f"_{n} maintenance {noun} omitted._", ""]
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines) + "\n"


def has_version(text: str, version: str) -> bool:
    return re.search(rf"^## \[{re.escape(version)}\]", text, re.MULTILINE) is not None


def insert_section(text: str, section: str) -> str:
    """Insert `section` at the end of the `## [Unreleased]` block.

    The Unreleased block runs from its heading to the next line starting with `## [` (or to
    end of file when no released version exists). The section is inserted exactly at that
    boundary, so the new version sits directly below Unreleased and above older releases.
    Every original byte stays in place: the result is `before + inserted + after`, where
    `before` and `after` are the original text split at the boundary, and only blank-line
    padding and the new section are added in between.
    """
    unreleased = UNRELEASED_RE.search(text)
    if unreleased is None:
        raise ValueError("CHANGELOG.md has no '## [Unreleased]' heading")
    nxt = NEXT_HEADING_RE.search(text, unreleased.end())
    idx = nxt.start() if nxt else len(text)
    before, after = text[:idx], text[idx:]
    if not before.endswith("\n"):
        pad = "\n\n"
    elif before.endswith("\n\n"):
        pad = ""
    else:
        pad = "\n"
    tail = "\n" if after else ""
    return before + pad + section + tail + after


def read_commits(repo: Path, from_ref: str, to_ref: str) -> list[CommitRecord]:
    for ref in (from_ref, to_ref):
        if not ref or ref.startswith("-"):
            raise ValueError(f"invalid git ref: {ref!r}")
    result = subprocess.run(
        ["git", "log", "--no-color", f"--format={LOG_FORMAT}", f"{from_ref}..{to_ref}"],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git log failed: {result.stderr.strip()}")
    commits: list[CommitRecord] = []
    for raw in result.stdout.split(RECORD_SEP):
        if not raw.strip():
            continue
        sha, parents, subject, body = raw.lstrip("\n").split(FIELD_SEP, 3)
        commits.append(CommitRecord(sha, tuple(parents.split()), subject, body))
    return commits


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Generate a Keep-a-Changelog section from conventional commits."
    )
    p.add_argument("--from", dest="from_ref", required=True, help="exclusive start ref")
    p.add_argument("--to", dest="to_ref", default="HEAD", help="inclusive end ref")
    p.add_argument("--version", help="X.Y.Z or X.Y.Z-rc.N; sets the section heading")
    p.add_argument("--date", help="YYYY-MM-DD; defaults to today")
    p.add_argument("--include-maintenance", action="store_true")
    p.add_argument("--write", action="store_true", help="insert into the changelog file")
    p.add_argument("--repo", type=Path, default=ROOT, help="git repository to read")
    p.add_argument("--changelog", type=Path, default=None, help="default: <repo>/CHANGELOG.md")
    return p


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    args = build_parser().parse_args(argv)
    if args.version and not VERSION_RE.match(args.version):
        print(f"error: invalid version {args.version!r}", file=sys.stderr)
        return 2
    if args.date and not DATE_RE.match(args.date):
        print(f"error: invalid date {args.date!r}", file=sys.stderr)
        return 2
    if args.write and not args.version:
        print("error: --write requires --version", file=sys.stderr)
        return 2

    date = args.date or dt.date.today().isoformat()
    try:
        commits = read_commits(args.repo, args.from_ref, args.to_ref)
    except (RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    section = render_section(parse_commits(commits), args.version, date, args.include_maintenance)

    if not args.write:
        sys.stdout.write(section)
        return 0

    path = args.changelog or (args.repo / "CHANGELOG.md")
    with path.open("r", encoding="utf-8", newline="") as fh:
        original = fh.read()
    if has_version(original, args.version):
        print(f"error: {path.name} already has a section for {args.version}", file=sys.stderr)
        return 1
    try:
        updated = insert_section(original, section)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    with path.open("w", encoding="utf-8", newline="") as fh:
        fh.write(updated)
    print(f"wrote {args.version} section to {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
