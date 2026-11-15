"""Tests for scripts/prp_index_check.py."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
_SPEC = importlib.util.spec_from_file_location(
    "prp_index_check", ROOT / "scripts" / "prp_index_check.py"
)
assert _SPEC is not None and _SPEC.loader is not None
chk = importlib.util.module_from_spec(_SPEC)
sys.modules["prp_index_check"] = chk
_SPEC.loader.exec_module(chk)

HEAD = (
    "| PRP | Priority | Order | Depends on | Blockers | Models | Review |\n"
    "|---|---|---|---|---|---|---|\n"
)


def prp(root: Path, directory: str, stem: str, priority="P1", order=5, review="none") -> None:
    d = root / "PRPs" / directory
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{stem}.md").write_text(
        f"---\nname: {stem}\nstatus: backlog\npriority: {priority}\norder: {order}\n"
        f"review: {review}\n---\n# x\n",
        encoding="utf-8",
    )


def backlog_row(stem: str, priority="P1", order=5, review="none", directory="backlog") -> str:
    link = f"[{stem}]({directory}/{stem}.md)"
    return f"| {link} | {priority} | {order} | - | - | sonnet / sonnet | {review} |\n"


def index(root: Path, backlog: str = "", shipped: str = "", extra: str = "") -> None:
    (root / "PRPs").mkdir(exist_ok=True)
    (root / "PRPs" / "INDEX.md").write_text(
        "# PRP index\n\n## Active\n\n_none_\n\n## Backlog\n\n"
        + HEAD
        + backlog
        + "\n## Shipped\n\n| PRP | Shipped | PR |\n|---|---|---|\n"
        + shipped
        + extra,
        encoding="utf-8",
    )


def test_clean_tree_passes(tmp_path: Path) -> None:
    prp(tmp_path, "backlog", "PRP-01-a")
    prp(tmp_path, "shipped", "PRP-02-b")
    index(
        tmp_path, backlog_row("PRP-01-a"), "| [PRP-02-b](shipped/PRP-02-b.md) | 2026-01-01 | #1 |\n"
    )
    assert chk.check_index(tmp_path) == []


def test_missing_row(tmp_path: Path) -> None:
    prp(tmp_path, "backlog", "PRP-01-a")
    index(tmp_path)
    assert any("PRP-01-a: missing" in p for p in chk.check_index(tmp_path))


def test_wrong_section(tmp_path: Path) -> None:
    prp(tmp_path, "shipped", "PRP-02-b")
    index(tmp_path, backlog_row("PRP-02-b", directory="shipped"))
    assert any("PRP-02-b" in p and "listed under" in p for p in chk.check_index(tmp_path))


def test_duplicate(tmp_path: Path) -> None:
    prp(tmp_path, "backlog", "PRP-01-a")
    index(tmp_path, backlog_row("PRP-01-a") * 2)
    assert any("listed 2 times" in p for p in chk.check_index(tmp_path))


def test_field_mismatch(tmp_path: Path) -> None:
    prp(tmp_path, "backlog", "PRP-01-a", priority="P1", order=5, review="none")
    index(tmp_path, backlog_row("PRP-01-a", priority="P2", order=6, review="required"))
    problems = "\n".join(chk.check_index(tmp_path))
    assert "priority" in problems and "order" in problems and "review" in problems


def test_link_to_missing_file(tmp_path: Path) -> None:
    index(tmp_path, backlog_row("PRP-09-gone"))
    problems = chk.check_index(tmp_path)
    assert any("missing file" in p for p in problems)
    assert any("PRP-09-gone: in PRPs/INDEX.md but no file" in p for p in problems)


def test_real_repo_passes() -> None:
    assert chk.check_index(ROOT) == []
