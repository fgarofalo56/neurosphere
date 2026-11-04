# Marketing asset manifest

Every marketing asset, its status and its review state. Status is exactly `draft` or `rendered`.
`draft` means a source or generated file that has not been rendered or run end to end as a deliverable.
`rendered` means a built deliverable that was opened and inspected by the owner for layout; it does not mean independently reviewed. Today the deck source and the PPTX are `rendered`; everything else is `draft`.

Gate G09 (theme, brand and media review) is waived by the owner (Frank Garofalo) on 2026-11-03 for demo scope; no independent brand, legal or accessibility review was performed.

## Assets

| Asset | Path | Status | Owner | Review state | Build/regenerate command | Notes |
|---|---|---|---|---|---|---|
| Deck source | `marketing/deck/deck.md` | rendered | Frank Garofalo | Claude reviewer agent, accepted by owner without independent review 2026-11-03 | none (hand-edited source) | Source of truth for the deck. 13 slides, speaker notes after `Notes:`. |
| Deck PPTX | `marketing/deck/neurosphere-walking-deck.pptx` | rendered | Frank Garofalo | Claude reviewer agent, accepted by owner without independent review 2026-11-03 | `uv run --with python-pptx==1.0.2 python marketing/deck/build_pptx.py` | Generated from deck.md. Opened in desktop PowerPoint and all 13 slides inspected on 2026-11-03 (layout check, no overflow); no independent brand or legal review was performed (waived by the owner for demo scope on 2026-11-03). |
| Deck build script | `marketing/deck/build_pptx.py` | draft | Frank Garofalo | UNREVIEWED (pending independent review) | `uv run --with python-pptx==1.0.2 python marketing/deck/build_pptx.py` | Reproducible generator; python-pptx is not a project dependency. |
| Deck claims checklist | `marketing/deck/claims-checklist.md` | draft | Frank Garofalo | UNREVIEWED (pending independent review) | none (hand-edited) | Every factual claim in the deck with its supporting doc. |
| Admin persona script | `marketing/scripts/admin.md` | draft | Frank Garofalo | UNREVIEWED (pending independent review) | none (hand-edited source) | Follows the admin walkthrough. |
| Analyst persona script | `marketing/scripts/analyst.md` | draft | Frank Garofalo | UNREVIEWED (pending independent review) | none (hand-edited source) | Follows the analyst walkthrough. |
| Auditor persona script | `marketing/scripts/auditor.md` | draft | Frank Garofalo | UNREVIEWED (pending independent review) | none (hand-edited source) | Follows the auditor walkthrough. |
| Steward persona script | `marketing/scripts/steward.md` | draft | Frank Garofalo | UNREVIEWED (pending independent review) | none (hand-edited source) | Follows the steward walkthrough. |
| Viewer persona script | `marketing/scripts/viewer.md` | draft | Frank Garofalo | UNREVIEWED (pending independent review) | none (hand-edited source) | Follows the viewer walkthrough. |
| Feature to persona map | `marketing/scripts/feature-persona-map.md` | draft | Frank Garofalo | UNREVIEWED (pending independent review) | none (hand-edited source) | Maps features to the five persona scripts. |
| Video storyboard | `marketing/video/storyboard/storyboard.md` | draft | Frank Garofalo | UNREVIEWED (pending independent review) | none (hand-edited source) | Scene source, no media. |
| Video script | `marketing/video/storyboard/script.md` | draft | Frank Garofalo | UNREVIEWED (pending independent review) | none (hand-edited source) | Narration source, no audio. |
| Video storyboard claims | `marketing/video/storyboard/claims.md` | draft | Frank Garofalo | UNREVIEWED (pending independent review) | none (hand-edited) | Claims listed for the storyboard and script. |
| Video render approval record | `marketing/video/APPROVAL.md` | draft | Frank Garofalo | UNSIGNED (operator has not recorded a budget) | none (operator fills in) | Template only; the render guard refuses it until every field is filled. |
| Video render entry point | `marketing/video/render/render_video.py` | draft | Frank Garofalo | UNREVIEWED (pending independent review) | `python marketing/video/render/render_video.py --backend stub` | Guarded script with a stub backend for tests; no MP4 exists. See render/README.md. |

## Not yet produced

These have no file on disk. They are listed here, outside the table above, so no path check applies.

- Explainer video. Planned location: `marketing/video/render/` (owned by PRP-27). Status: draft.
  Owner: Frank Garofalo. Review state: UNREVIEWED (pending independent review).
  Build state: not rendered, see PRP-27. Rendering is budget-gated and needs operator approval; the storyboard and script above are its
  source material.
