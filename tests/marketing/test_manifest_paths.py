"""PRP-26 item 4: the marketing manifest is honest and covers every asset."""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
MARKETING = ROOT / "marketing"
MANIFEST = MARKETING / "MANIFEST.md"
RULES_PATH = ROOT / "tests" / "marketing" / "claims_rules.py"

ALLOWED_STATUS = {"draft", "rendered"}
COLUMNS = [
    "Asset",
    "Path",
    "Status",
    "Owner",
    "Review state",
    "Build/regenerate command",
    "Notes",
]


def _text() -> str:
    return MANIFEST.read_text(encoding="utf-8")


def _main_table() -> list[dict[str, str]]:
    """Rows of the table under the '## Assets' heading only."""
    match = re.search(r"^## Assets\n(.*?)(?=^## |\Z)", _text(), re.S | re.M)
    assert match, "missing '## Assets' section"
    rows: list[dict[str, str]] = []
    header: list[str] | None = None
    for line in match.group(1).splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if header is None:
            header = cells
            continue
        if set("".join(cells)) <= set("-: "):
            continue
        assert len(cells) == len(header), line
        rows.append(dict(zip(header, cells, strict=True)))
    assert header == COLUMNS, header
    return rows


def _row_path(row: dict[str, str]) -> Path:
    raw = row["Path"].strip("`")
    return ROOT / raw


def test_manifest_exists() -> None:
    assert MANIFEST.is_file()


def test_listed_paths_exist() -> None:
    rows = _main_table()
    assert rows
    for row in rows:
        assert _row_path(row).is_file(), row["Path"]


def test_statuses_only_draft_or_rendered() -> None:
    for row in _main_table():
        assert row["Status"] in ALLOWED_STATUS, row


def test_nothing_marked_rendered_without_review() -> None:
    for row in _main_table():
        if row["Status"] == "rendered":
            assert "UNREVIEWED" not in row["Review state"], row


def test_pptx_is_rendered_without_independent_review() -> None:
    rows = [r for r in _main_table() if r["Path"].endswith(".pptx`")]
    assert len(rows) == 1
    assert rows[0]["Status"] == "rendered"
    notes = rows[0]["Notes"]
    assert "PowerPoint" in notes
    assert "no independent brand or legal review was performed" in notes


def test_video_row_not_rendered() -> None:
    assert "not rendered, see PRP-27" in _text()


def test_g09_waiver_note() -> None:
    text = _text()
    assert re.search(r"G09 \([^)]*\) is waived by the owner \(Frank Garofalo\) on 2026-11-03", text)
    assert "no independent brand, legal or accessibility review was performed" in text


def test_every_marketing_file_is_listed() -> None:
    listed = {_row_path(r).resolve() for r in _main_table()}
    missing = []
    for path in MARKETING.rglob("*"):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        if path.name == "MANIFEST.md" or path.name == "README.md":
            continue
        # PRP-27 render output is gitignored local media; only captions.vtt is a listed asset.
        if (MARKETING / "video" / "render" / "out") in path.parents and path.name != "captions.vtt":
            continue
        if path.resolve() not in listed:
            missing.append(path.relative_to(ROOT).as_posix())
    assert not missing, missing


def _load_rules() -> ModuleType | None:
    if not RULES_PATH.exists():
        return None
    spec = importlib.util.spec_from_file_location("claims_rules", RULES_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolve annotations via sys.modules
    spec.loader.exec_module(module)
    return module


def test_manifest_passes_claims_rules() -> None:
    rules = _load_rules()
    if rules is None:
        pytest.skip("claims_rules.py not present")
    assert rules.find_violations(_text()) == []


def test_no_em_dashes() -> None:
    assert "—" not in _text()
