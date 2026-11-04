# Explainer video render (PRP-27)

Entry point: `python marketing/video/render/render_video.py [--backend stub|real|local]`
(function `main` in `render_video.py`).

A local render has been produced (MP4 not committed, see `APPROVAL.md` storage decision).
It is generated and awaiting human playback; no human has watched it.

## Run the local render (zero cost)

```
NS_LIVE_APPROVED=1 python marketing/video/render/render_video.py --backend local
```

Pipeline: Playwright (Chromium) screenshots of the local sandbox UI served by the e2e mock
API, Windows built-in System.Speech voice "Microsoft Zira Desktop" (offline, `speak.ps1`),
ffmpeg for assembly. No paid service, no cloud call, no production data.

Prerequisites: `pnpm install` in the repo (frontend deps and a Playwright Chromium),
`ffmpeg` and `ffprobe` on PATH, Windows PowerShell 5.1 (`powershell` on PATH).

Ports: the backend starts the mock API on 5218 and the Vite e2e server on 5217 (both
127.0.0.1, unique so they do not collide with other worktrees; override with `--app-port` and
`--api-port`) and stops them when capture finishes. A server left running on those ports
makes the start fail, so stop it first.

Files: `capture.mjs` (capture), `shots.json` (route and on-screen text per scene),
`speak.ps1` (TTS), `render_video.py` (guard, captions, assembly).

## What the guard enforces

1. `marketing/video/APPROVAL.md` must exist, parse, and have every field filled (no empty
   value, no `TODO`). A chat message is not an approval. No credentials go in that file.
2. Any backend other than `stub` also requires `NS_LIVE_APPROVED=1`.
3. The storyboard narration must pass the shared claims lint
   (`tests/marketing/claims_rules.py`) before anything renders.
4. Spend is appended to `spend-log.md` (never overwritten). A charge that would pass the
   approved budget is refused and the run stops. The final row records the MP4 sha256.

## Outputs (`out/`, media gitignored)

- `neurosphere-explainer.mp4`: 1280x720 H.264 + AAC, `captions.vtt` muxed as soft mov_text.
- `captions.vtt`: one cue per scene, text equal to the storyboard narration, timing from the
  MEASURED narration audio length (ffprobe) plus a one second pause per scene.
- `frames/`, `audio/`, `clips/`: intermediates, not committed.

## Backends

`StubBackend` is for tests and the default CLI: it writes to a temp directory and temp spend
log, never to `out/` or `spend-log.md`. The `real` backend is a placeholder that raises
`NotImplementedError`. CI never runs the render; tests mock the subprocess calls.

## Known limits

The stub sign-in is Viewer-only, so the header reads "Account: Viewer" in every frame; the
persona only changes the fake token the mock API reads. The workspace landing pages are
placeholders and are not shown. Seeded states that the UI does not draw (cost spike, bad-event
manifest comparison, awaiting-confirmation intents) are not shown.
