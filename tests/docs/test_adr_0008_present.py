"""ADR-0008 records the docs tool choice before any config exists (PRP-25 item 1)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ADR = ROOT / "docs/adr/0008-docs-site-tool.md"

REQUIRED_SECTIONS = ("## Context", "## Options", "## Criteria", "## Evidence", "## Decision")
CRITERIA = ("EOL", "migration cost", "search", "SVG", "licence")


def test_adr_has_required_sections() -> None:
    text = ADR.read_text(encoding="utf-8")
    for section in REQUIRED_SECTIONS:
        assert section in text, f"missing {section}"
    assert "- Date: 2026-10-30" in text
    assert "MkDocs Material" in text and "Zensical" in text


def test_adr_covers_every_criterion() -> None:
    text = ADR.read_text(encoding="utf-8").lower()
    for criterion in CRITERIA:
        assert criterion.lower() in text, f"criterion not covered: {criterion}"


def test_adr_names_build_command_and_has_no_em_dash() -> None:
    text = ADR.read_text(encoding="utf-8")
    assert "mkdocs build --strict" in text
    assert "—" not in text


def test_exactly_one_tool_config() -> None:
    present = [n for n in ("mkdocs.yml", "zensical.toml") if (ROOT / n).is_file()]
    assert len(present) == 1, f"expected exactly one docs config, found {present}"
    # The decision text must match the config that exists.
    text = ADR.read_text(encoding="utf-8")
    assert ("mkdocs.yml" in text) == (present == ["mkdocs.yml"])
