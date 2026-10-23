"""Every Mermaid block in docs/compliance/plans/*.md has a committed, linked SVG or the doc
says "not rendered"."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PLANS = ROOT / "docs" / "compliance" / "plans"
BLOCK_RE = re.compile(r"^```mermaid[ \t]*\r?\n", re.MULTILINE)
SVG_LINK_RE = re.compile(r"\]\(([^)\s]+\.svg)\)")
NOT_RENDERED_RE = re.compile(r"\bnot rendered\b", re.IGNORECASE)


def diagram_problems(doc: Path) -> list[str]:
    """Return problems for one plan document (empty when fine)."""
    text = doc.read_text(encoding="utf-8")
    blocks = len(BLOCK_RE.findall(text))
    if blocks == 0 or NOT_RENDERED_RE.search(text):
        return []
    linked = {m for m in SVG_LINK_RE.findall(text) if "://" not in m}
    existing = {m for m in linked if (doc.parent / m).is_file()}
    problems = [f"{doc.name}: linked SVG not committed: {m}" for m in sorted(linked - existing)]
    if len(existing) < blocks:
        problems.append(
            f"{doc.name}: {blocks} mermaid block(s) but {len(existing)} committed SVG link(s) "
            "and no 'not rendered' statement"
        )
    return problems


def _doc(tmp_path: Path, body: str, svgs: tuple[str, ...] = ()) -> Path:
    doc = tmp_path / "plan.md"
    doc.write_text(body, encoding="utf-8")
    for name in svgs:
        (tmp_path / name).write_text("<svg/>", encoding="utf-8")
    return doc


BLOCK = "```mermaid\nflowchart TB\n  A-->B\n```\n"


def test_block_with_committed_linked_svg_passes(tmp_path: Path) -> None:
    doc = _doc(
        tmp_path, BLOCK + "\n![boundary](boundary.svg)\n[svg](boundary.svg)\n", ("boundary.svg",)
    )
    assert diagram_problems(doc) == []


def test_block_without_svg_or_statement_fails(tmp_path: Path) -> None:
    assert diagram_problems(_doc(tmp_path, BLOCK)) != []


def test_link_to_uncommitted_svg_fails(tmp_path: Path) -> None:
    doc = _doc(tmp_path, BLOCK + "\n[svg](missing.svg)\n")
    assert any("not committed" in p for p in diagram_problems(doc))


def test_explicit_not_rendered_passes(tmp_path: Path) -> None:
    assert diagram_problems(_doc(tmp_path, BLOCK + "\nDiagram status: not rendered.\n")) == []


def test_two_blocks_one_svg_fails(tmp_path: Path) -> None:
    doc = _doc(tmp_path, BLOCK + BLOCK + "\n[svg](a.svg)\n", ("a.svg",))
    assert diagram_problems(doc) != []


def test_doc_without_diagrams_passes(tmp_path: Path) -> None:
    assert diagram_problems(_doc(tmp_path, "# Plan\nText only.\n")) == []


def test_real_plans_have_rendered_diagrams() -> None:
    if not PLANS.is_dir():
        pytest.skip("docs/compliance/plans/ absent in this checkout (item 4 merges separately)")
    docs = sorted(PLANS.glob("*.md"))
    assert docs, "docs/compliance/plans/ exists but holds no markdown"
    problems = [p for d in docs for p in diagram_problems(d)]
    assert problems == []
