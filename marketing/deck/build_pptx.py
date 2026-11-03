"""Build the walking deck PPTX from deck.md (PRP-26 item 1).

Run (python-pptx is not a project dependency; it is pinned here on purpose)::

    uv run --with python-pptx==1.0.2 python marketing/deck/build_pptx.py

Output: marketing/deck/neurosphere-walking-deck.pptx. One slide per slide section of
deck.md, speaker notes on every slide. The sha256 of deck.md is stored in the PPTX core
properties (``subject``) so a test can detect a stale PPTX. Timestamps are fixed so the
build is reproducible.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import re
import sys
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "deck.md"
OUTPUT = HERE / "neurosphere-walking-deck.pptx"
FIXED_TIME = dt.datetime(2026, 11, 2, 0, 0, 0)
FOOTER = "DRAFT, claims unreviewed. Synthetic sandbox data only."


@dataclass(frozen=True)
class Slide:
    title: str
    bullets: list[str]
    notes: str
    claims: list[str]


def split_deck(text: str) -> tuple[str, list[str]]:
    """Return (front matter text, slide section texts)."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("deck.md must start with a front matter block")
    end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    front = "\n".join(lines[1:end])
    sections: list[list[str]] = [[]]
    for line in lines[end + 1 :]:
        if line.strip() == "---":
            sections.append([])
        else:
            sections[-1].append(line)
    return front, ["\n".join(s).strip() for s in sections if "\n".join(s).strip()]


def parse_slide(section: str) -> Slide:
    title = ""
    bullets: list[str] = []
    notes: list[str] = []
    claims: list[str] = []
    in_notes = False
    for line in section.splitlines():
        if in_notes:
            notes.append(line)
        elif line.startswith("# "):
            title = line[2:].strip()
        elif line.startswith("Claims:"):
            claims = [c.strip() for c in line[len("Claims:") :].split(",") if c.strip()]
        elif line.strip() == "Notes:":
            in_notes = True
        elif line.startswith("- "):
            bullets.append(line[2:].strip())
    note_text = re.sub(r"\n{2,}", "\n", "\n".join(notes).strip())
    if not title or not note_text:
        raise ValueError(f"slide without title or notes: {section[:40]!r}")
    return Slide(title, bullets, note_text, claims)


def parse_deck(text: str) -> list[Slide]:
    _, sections = split_deck(text)
    return [parse_slide(s) for s in sections]


def build(text: str, output: Path) -> int:
    from pptx import Presentation  # pyright: ignore[reportMissingImports]
    from pptx.dml.color import RGBColor  # pyright: ignore[reportMissingImports]
    from pptx.enum.shapes import MSO_SHAPE  # pyright: ignore[reportMissingImports]
    from pptx.util import Emu, Inches, Pt  # pyright: ignore[reportMissingImports]

    slides = parse_deck(text)
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    ink = RGBColor(0x1F, 0x2A, 0x37)
    accent = RGBColor(0x0F, 0x76, 0x6E)
    muted = RGBColor(0x4B, 0x55, 0x63)

    for index, item in enumerate(slides, start=1):
        slide = prs.slides.add_slide(prs.slide_layouts[1])
        title = slide.shapes.title
        body = slide.placeholders[1]
        assert title is not None
        title.left, title.top = Inches(0.7), Inches(0.5)
        title.width, title.height = Inches(11.9), Inches(1.2)
        title.text_frame.text = item.title
        title.text_frame.word_wrap = True
        for run in title.text_frame.paragraphs[0].runs:
            run.font.size = Pt(36 if index > 1 else 48)
            run.font.bold = True
            run.font.color.rgb = ink
        title.text_frame.paragraphs[0].alignment = 1  # left

        bar = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE, Inches(0.7), Inches(1.75), Inches(1.6), Emu(54000)
        )
        bar.fill.solid()
        bar.fill.fore_color.rgb = accent
        bar.line.fill.background()
        bar.name = "Accent bar (decorative)"

        body.left, body.top = Inches(0.7), Inches(2.05)
        body.width, body.height = Inches(11.9), Inches(4.5)
        frame = body.text_frame
        frame.word_wrap = True
        for n, bullet in enumerate(item.bullets):
            para = frame.paragraphs[0] if n == 0 else frame.add_paragraph()
            para.text = bullet
            para.space_after = Pt(10)
            for run in para.runs:
                run.font.size = Pt(22)
                run.font.color.rgb = ink

        footer = slide.shapes.add_textbox(Inches(0.7), Inches(6.9), Inches(11.9), Inches(0.4))
        footer.name = "Draft footer"
        footer.text_frame.text = f"{FOOTER}  {index}/{len(slides)}"
        for run in footer.text_frame.paragraphs[0].runs:
            run.font.size = Pt(12)
            run.font.color.rgb = muted

        slide.notes_slide.notes_text_frame.text = item.notes  # type: ignore[union-attr]

    props = prs.core_properties
    props.title = "NeuroSphere walking deck (DRAFT)"
    props.author = "NeuroSphere marketing sources"
    props.subject = "deck.md sha256=" + hashlib.sha256(text.encode("utf-8")).hexdigest()
    props.created = props.modified = props.last_printed = FIXED_TIME
    props.revision = 1
    output.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(output))
    return len(slides)


def main() -> int:
    text = SOURCE.read_text(encoding="utf-8")
    count = build(text, OUTPUT)
    print(f"wrote {OUTPUT.name}: {count} slides")
    return 0


if __name__ == "__main__":
    sys.exit(main())
