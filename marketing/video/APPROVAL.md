# Explainer video render approval

A chat message is not an approval. This file is the approval record the render entry
point accepts. Do not put credentials, API keys, tokens or account identifiers in this
file.

Provenance: on 2026-11-03 the owner (Frank Garofalo) directed in the Claude Code session
for PRP-27 to skip budget concerns and complete the work, and clarified that spending in
Azure is acceptable. No cap was stated. The approved pipeline below happens to cost
nothing, so planned spend is zero; the recorded cap of 25 USD is a ceiling chosen by the agent for headroom, not a stated owner figure. Adding an Azure service (for example a neural
voice) needs a new entry here naming the service, a cap and a spend row first.

| Field | Value |
|---|---|
| Date | 2026-11-03 |
| Budget amount | 25 |
| Currency | USD |
| Approver | Frank Garofalo (owner), by session instruction on 2026-11-03 |
| Approved tool | Local pipeline with no paid or network media service: Playwright screen capture of the local sandbox UI (emulators only), Windows built-in System.Speech synthetic voice (Microsoft Zira Desktop), ffmpeg for assembly |
| Tool version | ffmpeg 9.0.2 (gyan.dev full build); Playwright and Chromium as pinned by the frontend lockfile at render time; Windows System.Speech on Windows 11 |
| Tool terms URL | https://ffmpeg.org/legal.html ; https://github.com/microsoft/playwright/blob/main/LICENSE ; Microsoft Windows license terms for the bundled voice (redistribution terms not independently verified) |
| Terms observed date | 2026-11-03 |
| Approved scope | One captioned MP4 of about 2 to 3 minutes built from the reviewed PRP-26 storyboard, with a WebVTT captions file. Sandbox data only with the isolation banner visible. Planned spend is zero: no paid generation, no cloud call, no production data. Output stays local and is not published |
| Voice and likeness licensing terms | Synthetic voice only (Microsoft Zira Desktop, no real person). No real person's likeness or voice. No third-party imagery, music or logos; no Microsoft logo or badge |
| Storage decision (commit or external) | external: MP4 stays under the gitignored render output directory and is not committed; captions file and manifest rows are committed |
| Storage checksum | recorded in marketing/video/render/spend-log.md after render |
