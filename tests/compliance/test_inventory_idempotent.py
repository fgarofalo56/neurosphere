"""Two collector runs on unchanged inputs give byte-identical inventory, manifest, archive."""

from __future__ import annotations

from pathlib import Path
from types import ModuleType


def _fixture_tree(root: Path) -> None:
    (root / "docs" / "evidence" / "G02").mkdir(parents=True)
    (root / "docs" / "evidence" / "G02" / "register.yaml").write_text(
        "retrieved: 2026-10-08\nrows: []\n", encoding="utf-8"
    )
    (root / "docs" / "evidence" / "G07" / "dr").mkdir(parents=True)
    (root / "docs" / "evidence" / "G07" / "dr" / "drill-2026-10-22.json").write_text(
        '{"ok": true}\n', encoding="utf-8"
    )
    (root / "docs" / "evidence" / "notes.md").write_bytes(b"line one\r\nline two\r\n")
    (root / "SECURITY.md").write_text("# Security\n", encoding="utf-8")


def _run(collector: ModuleType, root: Path, out_base: Path, tag: str) -> tuple[bytes, bytes, bytes]:
    out = out_base / f"out-{tag}"
    inv = out / "inventory.md"
    pkg = out / "pkg"
    rc = collector.main(["--root", str(root), "--inventory", str(inv), "--package-dir", str(pkg)])
    assert rc == 0
    return (
        inv.read_bytes(),
        (pkg / "manifest.json").read_bytes(),
        (pkg / "compliance-package.zip").read_bytes(),
    )


def test_fixture_tree_runs_are_byte_identical(collector: ModuleType, tmp_path: Path) -> None:
    root = tmp_path / "repo"
    _fixture_tree(root)
    first = _run(collector, root, tmp_path, "a")
    second = _run(collector, root, tmp_path, "b")
    assert first == second
    assert b"\r" not in first[0]


def test_real_repo_runs_are_byte_identical(
    collector: ModuleType, repo_root: Path, tmp_path: Path
) -> None:
    first = _run(collector, repo_root, tmp_path, "a")
    second = _run(collector, repo_root, tmp_path, "b")
    assert first == second


def test_absent_expected_path_is_listed_missing(collector: ModuleType, tmp_path: Path) -> None:
    root = tmp_path / "repo"
    _fixture_tree(root)
    text = _run(collector, root, tmp_path, "a")[0].decode("utf-8")
    assert "| `docs/security/threat-model.md` | - | - | missing |" in text
    assert "| `docs/evidence/G02/register.yaml` |" in text
    assert "register.yaml` | " in text and "| 2026-10-08 | collected |" in text


def test_source_date_comes_from_content_or_path_never_mtime(
    collector: ModuleType, tmp_path: Path
) -> None:
    root = tmp_path / "repo"
    _fixture_tree(root)
    text = _run(collector, root, tmp_path, "a")[0].decode("utf-8")
    assert "drill-2026-10-22.json` |" in text
    assert "| 2026-10-22 | collected |" in text
    notes_row = next(ln for ln in text.splitlines() if "docs/evidence/notes.md" in ln)
    assert notes_row.endswith("| undated | collected |")


def test_crlf_is_normalised_before_hashing(collector: ModuleType, tmp_path: Path) -> None:
    root = tmp_path / "repo"
    _fixture_tree(root)
    rows = {r.path: r for r in collector.collect(root)}
    import hashlib

    expected = hashlib.sha256(b"line one\nline two\n").hexdigest()
    assert rows["docs/evidence/notes.md"].sha256 == expected


def test_inventory_does_not_index_itself(collector: ModuleType, tmp_path: Path) -> None:
    root = tmp_path / "repo"
    _fixture_tree(root)
    inv = root / "docs" / "evidence" / "inventory.md"
    inv.write_text("stale\n", encoding="utf-8")
    paths = [r.path for r in collector.collect(root)]
    assert "docs/evidence/inventory.md" not in paths
