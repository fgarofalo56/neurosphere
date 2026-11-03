# Walking deck

Status: DRAFT. Source of truth is `deck.md`; the PPTX is generated from it. Every claim is
listed in `claims-checklist.md`; none had an independent review, so the deck front matter stays
`draft`. G09 waived by the owner (Frank Garofalo) on 2026-11-03 for demo scope; no independent brand, legal or accessibility review was performed.

| File | Purpose |
|---|---|
| `deck.md` | Markdown source: front matter (`status`, `claims:`), 13 slides separated by `---`, speaker notes after `Notes:` |
| `build_pptx.py` | Generates the PPTX from `deck.md` |
| `neurosphere-walking-deck.pptx` | Generated output (about 65 KB, committed) |
| `claims-checklist.md` | Every factual claim, its slides, supporting doc and reviewer |

## Build

```bash
uv run --with python-pptx==1.0.2 python marketing/deck/build_pptx.py
```

Tool: python-pptx, pinned at **1.0.2**, observed **2026-11-02** (confirmed through `uv run --with`;
`pptx.__version__` printed `1.0.2`). It is not a project dependency: the root `pyproject.toml`
and `uv.lock` are unchanged on purpose. The build is reproducible: timestamps are fixed and
the sha256 of `deck.md` is stored in the PPTX `subject` property, which
`tests/marketing/test_deck_pptx_exists.py` checks, so editing `deck.md` without rebuilding fails
the test.

Visual identity is neutral: plain text, one accent bar, no logos or badges. Third-party names
(Azure, Foundry) appear as plain text only where factual.

## Tests

```bash
uv run pytest tests/marketing -q
```

The claims lint is `tests/marketing/claims_rules.py` (shared with the storyboard test).

## Open check

What was actually done on 2026-11-02:

- Rebuilt the PPTX and reloaded it with python-pptx 1.0.2: 13 source slides, 13 PPTX slides,
  13 notes pages; slide titles and speaker notes equal the parsed source.
- `tests/marketing/test_deck_pptx_exists.py` reads the OOXML package with `zipfile` (no
  python-pptx needed): valid zip, slide count equals source, notes on every slide, not stale.

What was done on 2026-11-03, on the original build and again after the claims-review fixes
(the second pass is on the current PPTX, rebuilt from the current `deck.md`): Claude opened the file read-only in desktop PowerPoint through COM
automation (windowless), exported all 13 slides to 1600x900 PNG and inspected every image.
PowerPoint reported 13 slides at 960x540 with speaker notes on every slide. No text overflow,
clipping or unreadable slide was seen; every slide carries the DRAFT footer. The file has no
images or diagrams, so there is nothing else to fit. The renders were scratch output and are
not committed.

What is still NOT done: no human has reviewed the deck. This was a layout and open check by the
tool that wrote it, not a content, brand or legal review, so the manifest keeps the row at
`draft`. Someone must review it and record who and when in the PRP-26 completion note before
the manifest may call it `rendered`.
