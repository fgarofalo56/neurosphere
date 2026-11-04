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
| Video captions | `marketing/video/render/out/captions.vtt` | rendered | Frank Garofalo | Owner played back the video and captions and approved 2026-11-03; no independent brand, legal or accessibility review | `python marketing/video/render/render_video.py --backend local` | Generated, awaiting human playback. Cue timing is measured from the narration audio. |
| Video render spend log | `marketing/video/render/spend-log.md` | draft | Frank Garofalo | UNREVIEWED (generated, awaiting human playback) | `python marketing/video/render/render_video.py --backend local` | Generated spend rows (0.00 USD) and the MP4 checksum; the MP4 itself is not committed. |
| Video capture script | `marketing/video/render/capture.mjs` | draft | Frank Garofalo | UNREVIEWED (pending independent review) | none (hand-edited source) | Playwright capture of the local sandbox UI; helper for the local render backend. |
| Video capture shot list | `marketing/video/render/shots.json` | draft | Frank Garofalo | UNREVIEWED (pending independent review) | none (hand-edited source) | Routes and on-screen text per scene for the capture script. |
| Video narration script | `marketing/video/render/speak.ps1` | draft | Frank Garofalo | UNREVIEWED (pending independent review) | none (hand-edited source) | Offline Windows System.Speech text to WAV helper; no network. |
| Video render entry point | `marketing/video/render/render_video.py` | draft | Frank Garofalo | UNREVIEWED (pending independent review) | `python marketing/video/render/render_video.py --backend stub` | Guarded script with a stub backend for tests; no MP4 exists. See render/README.md. |

## Produced outside git

These files are not committed, so the path check does not apply to them. Each entry records its path and checksum.

- Explainer video (rendered, stored outside git). Path: `marketing/video/render/out/neurosphere-explainer.mp4` (gitignored, not committed).
  sha256: 5571a8fd6a1345ea2ef28ddff1d1a4c7730b712160e12f43ee402556f2d05e13.
  Captions: `marketing/video/render/out/captions.vtt` (listed in the table above).
  Build: local zero-cost render (PRP-27); owner played it back and approved it on 2026-11-03.
  Review state: owner approval, with no independent brand, legal or accessibility review.
  Known gaps against the storyboard: the sandbox UI does not draw the cost spike (S03),
  the awaiting-confirmation intents (S05) or the bad-event manifest comparison (S06), and
  every frame shows the Viewer account. The narration describes those states; the frames
  do not show them. The storyboard S01 text still says it is not a rendered video.
