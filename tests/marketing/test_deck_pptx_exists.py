"""The walking deck PPTX exists, is a valid package and matches deck.md (PRP-26 item 1).

python-pptx is not a project dependency, so this test reads the OOXML package directly with
zipfile and the standard XML parser; it needs nothing beyond the standard library.
"""

from __future__ import annotations

import hashlib
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

REPO = Path(__file__).resolve().parents[2]
DECK_DIR = REPO / "marketing" / "deck"
PPTX = DECK_DIR / "neurosphere-walking-deck.pptx"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
MAX_BYTES = 500_000


def _source_slide_count() -> int:
    text = (DECK_DIR / "deck.md").read_text(encoding="utf-8")
    lines = text.splitlines()
    end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    body = "\n".join(lines[end + 1 :])
    return len([s for s in re.split(r"^---$", body, flags=re.MULTILINE) if s.strip()])


def _slide_files(zf: zipfile.ZipFile, folder: str, prefix: str) -> list[str]:
    pattern = re.compile(rf"^ppt/{folder}/{prefix}\d+\.xml$")
    return sorted(n for n in zf.namelist() if pattern.match(n))


def test_pptx_exists_and_is_small() -> None:
    assert PPTX.is_file(), (
        "run: uv run --with python-pptx==1.0.2 python marketing/deck/build_pptx.py"
    )
    assert PPTX.stat().st_size < MAX_BYTES


def test_pptx_is_a_valid_package() -> None:
    with zipfile.ZipFile(PPTX) as zf:
        assert zf.testzip() is None
        assert "[Content_Types].xml" in zf.namelist()
        assert "ppt/presentation.xml" in zf.namelist()


def test_slide_count_matches_source() -> None:
    with zipfile.ZipFile(PPTX) as zf:
        assert len(_slide_files(zf, "slides", "slide")) == _source_slide_count()


def test_every_slide_has_speaker_notes() -> None:
    with zipfile.ZipFile(PPTX) as zf:
        slides = _slide_files(zf, "slides", "slide")
        notes = _slide_files(zf, "notesSlides", "notesSlide")
        assert len(notes) == len(slides)
        for name in notes:
            root = ET.fromstring(zf.read(name))
            text = " ".join(t.text or "" for t in root.iter(f"{A}t"))
            assert len(text.strip()) > 40, name


def test_pptx_is_not_stale_against_deck_md() -> None:
    # read_text normalises newlines, exactly as the build does
    source = (DECK_DIR / "deck.md").read_text(encoding="utf-8")
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
    with zipfile.ZipFile(PPTX) as zf:
        core = zf.read("docProps/core.xml").decode("utf-8")
    assert f"sha256={digest}" in core, "deck.md changed; rebuild the PPTX"
