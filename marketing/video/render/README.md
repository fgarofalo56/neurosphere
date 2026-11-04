# Explainer video render (PRP-27)

Entry point: `python marketing/video/render/render_video.py [--backend stub|real]`
(function `main` in `render_video.py`).

No media has been rendered. The real render is operator-approved only.

## What the guard enforces

1. `marketing/video/APPROVAL.md` must exist, parse, and have every field filled (no empty
   value, no `TODO`). A chat message is not an approval. No credentials go in that file.
2. Any backend other than `stub` also requires `NS_LIVE_APPROVED=1`.
3. The storyboard narration must pass the shared claims lint
   (`tests/marketing/claims_rules.py`) before anything renders.
4. Spend is appended to `spend-log.md` (never overwritten). A charge that would pass the
   approved budget is refused and the run stops.

## Outputs

- `out/captions.vtt`: WebVTT, one cue per scene, text equal to the storyboard narration,
  timing from the storyboard duration estimates (estimates, not measured).

## Backends

`StubBackend` is for tests (no paid or network call). The `real` backend is a placeholder
that raises `NotImplementedError`: the tool is chosen at execution time with the operator.
Do not commit MP4s or other media; the storage decision is recorded in `APPROVAL.md`.
