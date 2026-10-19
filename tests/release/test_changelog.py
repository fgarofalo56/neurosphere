"""Tests for scripts/release/changelog.py: pure parser fixtures plus a throwaway git repo."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "release_changelog", ROOT / "scripts" / "release" / "changelog.py"
)
assert _SPEC is not None and _SPEC.loader is not None
changelog = importlib.util.module_from_spec(_SPEC)
sys.modules["release_changelog"] = changelog
_SPEC.loader.exec_module(changelog)

CommitRecord = changelog.CommitRecord
DATE = "2026-10-18"


def rec(subject: str, body: str = "", parents: tuple[str, ...] = ("p",)) -> object:
    return CommitRecord("abc", parents, subject, body)


def render(commits: list[object], include_maintenance: bool = False) -> str:
    parsed = changelog.parse_commits(commits)
    return changelog.render_section(parsed, "0.2.0", DATE, include_maintenance)


def test_type_mappings_and_order() -> None:
    out = render(
        [
            rec("fix(api): handle empty body"),
            rec("feat(catalog): add versions"),
            rec("perf(core): faster hash"),
            rec("refactor: split module"),
            rec("revert: drop legacy route"),
            rec("deprecate(api): v1 query route"),
            rec("fix(security): reject bad token"),
            rec("sec: pin dependency"),
        ]
    )
    assert out == (
        "## [0.2.0] - 2026-10-18\n"
        "\n"
        "### Added\n"
        "- **catalog:** add versions\n"
        "\n"
        "### Changed\n"
        "- **core:** faster hash\n"
        "- split module\n"
        "\n"
        "### Deprecated\n"
        "- **api:** v1 query route\n"
        "\n"
        "### Removed\n"
        "- drop legacy route\n"
        "\n"
        "### Fixed\n"
        "- **api:** handle empty body\n"
        "\n"
        "### Security\n"
        "- **security:** reject bad token\n"
        "- pin dependency\n"
    )


def test_footers_for_deprecated_and_security() -> None:
    out = render(
        [
            rec("feat(api): new route", "Deprecated: the old route is replaced"),
            rec("chore: bump", "Security: rotates a signing secret reference"),
        ]
    )
    assert "### Added\n- **api:** new route" in out
    assert "### Deprecated\n- the old route is replaced" in out
    assert "### Security\n- rotates a signing secret reference" in out
    assert "maintenance" not in out


def test_breaking_bang_and_footer() -> None:
    out = render(
        [
            rec("feat(api)!: drop field"),
            rec("fix: tweak", "Details.\n\nBREAKING CHANGE: clients must resend the token"),
            rec("chore!: remove script"),
        ]
    )
    assert "- **BREAKING** **api:** drop field" in out
    assert "- **BREAKING** tweak" in out
    assert "### Changed\n- **BREAKING** remove script" in out
    assert (
        "### Breaking changes\n- drop field\n- clients must resend the token\n- remove script"
        in out
    )


def test_maintenance_counted_and_listed_on_request() -> None:
    commits = [rec("feat: one"), rec("chore: a"), rec("ci: b"), rec("docs(x): c"), rec("test: d")]
    commits += [rec("build: e"), rec("style: f")]
    out = render(commits)
    assert "_6 maintenance commits omitted._" in out
    assert "chore: a" not in out
    listed = render(commits, include_maintenance=True)
    assert "omitted" not in listed
    assert "### Maintenance\n- chore: a\n- ci: b\n- **x:** docs: c\n" in listed
    assert "- style: f" in listed
    single = render([rec("chore: only")])
    assert "_1 maintenance commit omitted._" in single


def test_unclassified_listed_verbatim() -> None:
    out = render(
        [
            rec("Update readme"),
            rec("wip: experiment (dirty)"),
            rec("feat:missing space"),
            rec("feat: ok"),
        ]
    )
    assert (
        "### Unclassified\n- Update readme\n- wip: experiment (dirty)\n- feat:missing space\n"
        in out
    )
    assert "### Added\n- ok" in out


def test_merge_commits_skipped() -> None:
    out = render(
        [
            rec("Merge pull request #1 from x/y", parents=("a", "b")),
            rec("feat: real"),
        ]
    )
    assert "Merge" not in out
    assert "### Added\n- real" in out
    assert "Unclassified" not in out


def test_no_version_heading() -> None:
    parsed = changelog.parse_commits([rec("fix: x")])
    assert changelog.render_section(parsed).startswith("## [Unreleased]\n")


# ---------------------------------------------------------------- throwaway git repo

GIT_ENV = {
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "test@example.invalid",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "test@example.invalid",
    "GIT_AUTHOR_DATE": "2026-01-01T00:00:00+00:00",
    "GIT_COMMITTER_DATE": "2026-01-01T00:00:00+00:00",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
}


def git(repo: Path, *args: str) -> str:
    env = {**os.environ, **GIT_ENV}
    result = subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "-c", "core.hooksPath=" + os.devnull, *args],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return result.stdout.strip()


def commit(repo: Path, message: str) -> None:
    git(repo, "commit", "--allow-empty", "-m", message)


def make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    commit(repo, "chore: initial")
    git(repo, "tag", "base")
    commit(repo, "feat(catalog): add versions")
    commit(repo, "fix(security): reject bad token")
    commit(repo, "docs: describe")
    commit(repo, "Random message")
    commit(repo, "feat(api)!: drop field\n\nBREAKING CHANGE: field removed")
    git(repo, "checkout", "-q", "-b", "side")
    commit(repo, "fix: side fix")
    git(repo, "checkout", "-q", "main")
    git(repo, "merge", "--no-ff", "-m", "Merge branch 'side'", "side")
    return repo


def run_cli(repo: Path, *args: str, changelog_path: Path | None = None) -> int:
    argv = ["--repo", str(repo), *args]
    if changelog_path is not None:
        argv += ["--changelog", str(changelog_path)]
    return int(changelog.main(argv))


def test_end_to_end_against_git_repo(tmp_path: Path, capsys) -> None:
    repo = make_repo(tmp_path)
    code = run_cli(repo, "--from", "base", "--to", "HEAD", "--version", "0.2.0", "--date", DATE)
    assert code == 0
    out = capsys.readouterr().out
    assert out.startswith("## [0.2.0] - 2026-10-18\n")
    assert "### Added\n- **BREAKING** **api:** drop field\n- **catalog:** add versions" in out
    assert "### Fixed\n- side fix" in out
    assert "### Security\n- **security:** reject bad token" in out
    assert "### Breaking changes\n- field removed" in out
    assert "### Unclassified\n- Random message" in out
    assert "_1 maintenance commit omitted._" in out
    assert "Merge branch" not in out


def test_cli_rejects_bad_input(tmp_path: Path, capsys) -> None:
    repo = make_repo(tmp_path)
    assert run_cli(repo, "--from", "base", "--version", "1.0") == 2
    assert run_cli(repo, "--from", "base", "--write") == 2
    assert run_cli(repo, "--from", "no-such-ref") == 2
    assert run_cli(repo, "--from=--output=x") == 2
    capsys.readouterr()


# ---------------------------------------------------------------- --write


def test_write_preserves_existing_bytes(tmp_path: Path) -> None:
    original = (ROOT / "CHANGELOG.md").read_bytes()
    target = tmp_path / "CHANGELOG.md"
    target.write_bytes(original)
    repo = make_repo(tmp_path)

    code = run_cli(
        repo,
        "--from",
        "base",
        "--version",
        "0.2.0",
        "--date",
        DATE,
        "--write",
        changelog_path=target,
    )
    assert code == 0
    updated = target.read_bytes()
    heading = b"## [Unreleased]"
    split = original.index(heading)
    # The Unreleased block of the real file is the whole file (no released versions yet), so
    # the new section lands at end of file; every original byte is a prefix of the result.
    assert updated.startswith(original)
    assert b"\n## [0.2.0] - 2026-10-18\n" in updated[len(original) :]
    assert updated[:split] == original[:split]


def test_insert_before_older_release_keeps_both_sides() -> None:
    text = "# Changelog\n\n## [Unreleased]\n\n### Added\n- x\n\n## [0.1.0] - 2026-01-01\n\n- old\n"
    section = "## [0.2.0] - 2026-10-18\n\n### Fixed\n- y\n"
    result = changelog.insert_section(text, section)
    cut = text.index("## [0.1.0]")
    assert result.startswith(text[:cut])
    assert result.endswith(text[cut:])
    assert result == text[:cut] + section + "\n" + text[cut:]


def test_insert_pads_missing_blank_line_and_requires_unreleased() -> None:
    result = changelog.insert_section("## [Unreleased]\n- x", "## [0.2.0] - d\n")
    assert result == "## [Unreleased]\n- x\n\n## [0.2.0] - d\n"
    try:
        changelog.insert_section("# Changelog\n", "## [0.2.0] - d\n")
    except ValueError as exc:
        assert "Unreleased" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_duplicate_version_refused_and_noop(tmp_path: Path, capsys) -> None:
    target = tmp_path / "CHANGELOG.md"
    target.write_bytes((ROOT / "CHANGELOG.md").read_bytes())
    repo = make_repo(tmp_path)
    args = ("--from", "base", "--version", "0.2.0", "--date", DATE, "--write")
    assert run_cli(repo, *args, changelog_path=target) == 0
    after_first = target.read_bytes()
    capsys.readouterr()

    assert run_cli(repo, *args, changelog_path=target) == 1
    assert target.read_bytes() == after_first
    assert "already has a section" in capsys.readouterr().err
