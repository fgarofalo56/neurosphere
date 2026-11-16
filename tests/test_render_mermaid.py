"""Block extraction and count for the Mermaid render gate. Needs no Chromium."""

from __future__ import annotations

import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NS = runpy.run_path(str(ROOT / "scripts" / "render_mermaid.py"))


def test_architecture_has_five_blocks() -> None:
    text = (ROOT / "docs" / "ARCHITECTURE.md").read_text(encoding="utf-8")
    assert len(NS["extract_blocks"](text)) == 5


def test_extract_blocks_keeps_order_and_bodies() -> None:
    text = "a\n```mermaid\nflowchart TB\n  A-->B\n```\ntext\n```mermaid\nsequenceDiagram\n```\n"
    blocks = NS["extract_blocks"](text)
    assert blocks == ["flowchart TB\n  A-->B\n", "sequenceDiagram\n"]


def test_svg_names_are_numbered_in_section_order() -> None:
    names = [NS["svg_name"](i) for i in range(1, 6)]
    assert names[0] == "01-component-trust-boundaries.svg"
    assert names[-1] == "05-federation-and-dr.svg"
    assert names == sorted(names)


def test_committed_svgs_match_script_names() -> None:
    for i in range(1, 6):
        assert (ROOT / "docs" / "diagrams" / NS["svg_name"](i)).is_file()


def test_wrong_block_count_exits_nonzero(tmp_path: Path, capsys) -> None:
    src = tmp_path / "doc.md"
    src.write_text("```mermaid\nflowchart TB\n  A-->B\n```\n", encoding="utf-8")
    rc = NS["main"](["--source", str(src), "--out", str(tmp_path / "out")])
    assert rc == 1
    assert "found 1 mermaid blocks, expected 5" in capsys.readouterr().out


def test_round_coordinates_trims_long_floats() -> None:
    assert NS["round_coordinates"]("M705.4289321,543L7.5") == "M705.42,543L7.5"


def test_dfd_directory_has_blocks_in_every_file() -> None:
    """#68: the DFD sources are covered by directory mode and each carries a block."""
    files = sorted((ROOT / "docs" / "security" / "dfd").glob("*.md"))
    assert len(files) >= 3
    for md in files:
        assert NS["extract_blocks"](md.read_text(encoding="utf-8")), md.name


def test_directory_mode_fails_on_empty_directory(tmp_path: Path, capsys) -> None:
    rc = NS["main"](["--source-dir", str(tmp_path)])
    assert rc == 1
    assert "no markdown files found" in capsys.readouterr().out


def test_directory_mode_fails_on_file_without_block(tmp_path: Path, capsys) -> None:
    (tmp_path / "plain.md").write_text("no diagram here\n", encoding="utf-8")
    rc = NS["main"](["--source-dir", str(tmp_path)])
    assert rc == 1
    assert "plain.md: no mermaid blocks" in capsys.readouterr().out


def test_directory_mode_does_not_enforce_five_blocks(tmp_path: Path, monkeypatch) -> None:
    """The ARCHITECTURE five-block rule is unchanged and not applied to directories."""
    (tmp_path / "one.md").write_text("```mermaid\nflowchart TB\n  A-->B\n```\n", encoding="utf-8")
    calls: list[str | None] = []

    def fake_render(index, body, out_dir, workdir, no_sandbox, target_name=None, label=None):
        calls.append(target_name)
        return True

    monkeypatch.setitem(NS["render_directory"].__globals__, "render_block", fake_render)
    rc = NS["main"](["--source-dir", str(tmp_path)])
    assert rc == 0
    assert calls == ["one-01.svg"]
