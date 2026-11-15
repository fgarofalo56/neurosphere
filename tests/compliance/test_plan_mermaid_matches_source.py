"""Each fenced mermaid block in docs/compliance/plans/*.md equals its diagrams/*.mmd source."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PLANS = ROOT / "docs" / "compliance" / "plans"
DIAGRAMS = PLANS / "diagrams"
FENCE_RE = re.compile(r"^```mermaid[ \t]*\r?\n(.*?)^```[ \t]*$", re.MULTILINE | re.DOTALL)


def _norm(text: str) -> str:
    lines = [ln.rstrip() for ln in text.replace("\r\n", "\n").strip().split("\n")]
    return "\n".join(lines)


def blocks(text: str) -> list[str]:
    return [_norm(m) for m in FENCE_RE.findall(text)]


def mismatches(doc_text: str, sources: list[str]) -> list[str]:
    """Return fenced blocks that match none of the sources."""
    normed = {_norm(s) for s in sources}
    return [b for b in blocks(doc_text) if b not in normed]


def test_every_plan_block_matches_a_mmd_source() -> None:
    sources = [p.read_text(encoding="utf-8") for p in sorted(DIAGRAMS.glob("*.mmd"))]
    assert sources, "no diagrams/*.mmd sources found"
    problems: list[str] = []
    for doc in sorted(PLANS.glob("*.md")):
        for block in mismatches(doc.read_text(encoding="utf-8"), sources):
            problems.append(f"{doc.name}: block starting {block.splitlines()[0]!r} has no source")
    assert problems == []


def test_every_mmd_source_is_used_by_a_plan() -> None:
    used: set[str] = set()
    docs = [d.read_text(encoding="utf-8") for d in sorted(PLANS.glob("*.md"))]
    for src in sorted(DIAGRAMS.glob("*.mmd")):
        body = _norm(src.read_text(encoding="utf-8"))
        if any(body in blocks(d) for d in docs):
            used.add(src.name)
    assert used == {p.name for p in DIAGRAMS.glob("*.mmd")}


def test_drift_is_detected() -> None:
    src = "flowchart TB\n  A-->B\n"
    assert mismatches("```mermaid\nflowchart TB\n  A-->B\n```\n", [src]) == []
    assert mismatches("```mermaid\nflowchart TB\n  A-->C\n```\n", [src]) != []
