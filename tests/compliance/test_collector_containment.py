"""The collector never reads a file whose resolved path leaves the repository root (#120)."""

from __future__ import annotations

from pathlib import Path
from types import ModuleType

import pytest


def test_symlinked_parent_directory_is_not_followed(collector: ModuleType, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret-notes.md").write_text("outside the repo\n", encoding="utf-8")
    root = tmp_path / "repo"
    (root / "docs").mkdir(parents=True)
    try:
        (root / "docs" / "evidence").symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not permitted on this machine")

    rows = collector.collect(root)
    hit = [r for r in rows if r.path == "docs/evidence/secret-notes.md"]
    assert hit, "the symlinked path should be listed, not silently skipped"
    assert all(r.status.startswith("failed") for r in hit)
    assert all(r.payload is None for r in hit)


def test_regular_file_inside_root_is_collected(collector: ModuleType, tmp_path: Path) -> None:
    (tmp_path / "docs" / "evidence").mkdir(parents=True)
    (tmp_path / "docs" / "evidence" / "ok.md").write_text("fine\n", encoding="utf-8")
    rows = collector.collect(tmp_path)
    assert [r.status for r in rows if r.path == "docs/evidence/ok.md"] == ["collected"]
