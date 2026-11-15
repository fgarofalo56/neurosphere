"""Tests for scripts/changelog_assemble.py."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "changelog_assemble", ROOT / "scripts" / "changelog_assemble.py"
)
assert _SPEC is not None and _SPEC.loader is not None
asm = importlib.util.module_from_spec(_SPEC)
sys.modules["changelog_assemble"] = asm
_SPEC.loader.exec_module(asm)

CHANGELOG = (
    "# Changelog\n\n## [Unreleased]\n\n### Added\n- old entry\n\n### Fixed\n- old fix\n\n"
    "## [0.1.0] - 2026-01-01\n\n### Added\n- first\n"
)


def setup(tmp_path: Path, fragments: dict[str, str], changelog: str = CHANGELOG):
    frag_dir = tmp_path / "changelog.d"
    frag_dir.mkdir()
    (frag_dir / "README.md").write_text("# readme\n", encoding="utf-8")
    for name, body in fragments.items():
        (frag_dir / name).write_text(body, encoding="utf-8", newline="")
    log = tmp_path / "CHANGELOG.md"
    log.write_bytes(changelog.encode("utf-8"))
    return frag_dir, log


def run(frag_dir: Path, log: Path, mode: str) -> int:
    return asm.main([mode, "--fragments", str(frag_dir), "--changelog", str(log)])


GOOD = "### Added\n- new thing\n"


def test_good_fragment_passes_check(tmp_path: Path) -> None:
    frag_dir, log = setup(tmp_path, {"PRP-68-changelog-fragments.md": GOOD, "issue-12.md": GOOD})
    assert run(frag_dir, log, "--check") == 0


@pytest.mark.parametrize(
    ("name", "body", "rule"),
    [
        ("notes.md", GOOD, "file name"),
        ("PRP-68-x.md", "### Misc\n- a\n", "not a Keep a Changelog"),
        ("PRP-68-x.md", "### Added\nplain text\n", "no list item"),
        ("PRP-68-x.md", "## [1.0.0]\n### Added\n- a\n", "'## ' headings"),
        ("PRP-68-x.md", "- a\n", "before any"),
    ],
)
def test_bad_fragment_fails(tmp_path: Path, capsys, name: str, body: str, rule: str) -> None:
    frag_dir, log = setup(tmp_path, {name: body})
    assert run(frag_dir, log, "--check") == 1
    out = capsys.readouterr().out
    assert name in out and rule in out


def test_write_splices_in_order_and_deletes(tmp_path: Path) -> None:
    frag_dir, log = setup(
        tmp_path,
        {
            "PRP-70-b.md": "### Added\n- b item\n\n### Security\n- sec item\n",
            "PRP-69-a.md": "### Added\n- a item\n\n### Changed\n- changed item\n",
        },
    )
    assert run(frag_dir, log, "--write") == 0
    text = log.read_text(encoding="utf-8")
    assert text.index("- old entry") < text.index("- a item") < text.index("- b item")
    assert text.index("### Added") < text.index("### Changed") < text.index("### Fixed")
    assert text.index("### Fixed") < text.index("### Security") < text.index("## [0.1.0]")
    assert "- old fix" in text and "- first" in text
    assert [p.name for p in frag_dir.glob("*.md")] == ["README.md"]


def test_untouched_bytes_kept(tmp_path: Path) -> None:
    frag_dir, log = setup(tmp_path, {"issue-1.md": GOOD})
    assert run(frag_dir, log, "--write") == 0
    text = log.read_text(encoding="utf-8")
    assert text.replace("- new thing\n", "") == CHANGELOG
    assert text.startswith(
        "# Changelog\n\n## [Unreleased]\n\n### Added\n- old entry\n- new thing\n"
    )


def test_crlf_changelog_preserved(tmp_path: Path) -> None:
    crlf = CHANGELOG.replace("\n", "\r\n")
    frag_dir, log = setup(tmp_path, {"issue-1.md": GOOD}, crlf)
    assert run(frag_dir, log, "--write") == 0
    raw = log.read_bytes().decode("utf-8")
    assert "\n" not in raw.replace("\r\n", "")
    assert raw.replace("- new thing\r\n", "") == crlf


def test_preview_changes_nothing(tmp_path: Path, capsys) -> None:
    frag_dir, log = setup(tmp_path, {"issue-1.md": GOOD})
    assert run(frag_dir, log, "--preview") == 0
    assert "- new thing" in capsys.readouterr().out
    assert log.read_text(encoding="utf-8") == CHANGELOG
    assert (frag_dir / "issue-1.md").exists()


def test_no_fragments_is_noop(tmp_path: Path) -> None:
    frag_dir, log = setup(tmp_path, {})
    assert run(frag_dir, log, "--write") == 0
    assert log.read_text(encoding="utf-8") == CHANGELOG


def test_unreleased_without_sections_and_without_release(tmp_path: Path) -> None:
    frag_dir, log = setup(tmp_path, {"issue-1.md": GOOD}, "# Changelog\n\n## [Unreleased]\n")
    assert run(frag_dir, log, "--write") == 0
    text = log.read_text(encoding="utf-8")
    assert "## [Unreleased]\n" in text and "### Added\n- new thing\n" in text


def test_reuses_release_boundary_rule() -> None:
    release = asm._release
    assert asm.UNRELEASED_RE is release.UNRELEASED_RE
    assert asm.NEXT_HEADING_RE is release.NEXT_HEADING_RE
