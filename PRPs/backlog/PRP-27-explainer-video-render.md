---
name: prp-27-explainer-video-render
status: backlog
review: none
created: 2026-10-08
model: sonnet
phase: 5
ns: NS-10
depends_on: PRP-26, budget approval
wave: W10
absorbs: P5.3 video (budget-gated follow-up)
---

# PRP-27: Explainer video render

## Goal
Produce the captioned explainer video from the reviewed PRP-26 storyboard, only after the operator records a generation budget. It is for sellers and evaluators who need a short video, and for the G09 reviewers who need an actual rendered file with captions to review. It is a budget-gated follow-up (decision D10): nothing here starts, and no paid media call is made, until `marketing/video/APPROVAL.md` exists.

> Deliver sales walking deck source and PPTX, persona demo scripts, marketing storyboard/scripts and captioned explainer videos with reviewed factual claims. Treat media production as explicit deliverables, not pretend generated files.

## Acceptance criteria
- [ ] Item 1: `marketing/video/APPROVAL.md` exists with date, budget amount and currency, approver name and the approved pipeline scope, before any render step runs; a guard test proves the render entry point refuses without it.
- [ ] Item 2: Given the approval record, When the render pipeline runs, Then an MP4 and a captions file (WebVTT or SRT) exist under `marketing/video/render/`, the captions match the narration, and every on-screen claim traces to the reviewed storyboard.
- [ ] Item 2: Total spend is recorded against the approved budget; the pipeline stops at the budget cap.
- [ ] Item 3: `marketing/MANIFEST.md` marks the video `rendered` with its path only after the MP4 and captions exist and were played back by a human; the G09 row records the new evidence and is not marked CLOSED unless product and legal/accessibility reviewers approve.
- [ ] No claim of completion is made until the MP4 and captions files exist; absent them the PRP is OPEN, not shipped.
- [ ] PRP exit: items 1-3 complete with evidence; G09 narrowed or closed only by the named reviewers.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|---|---|---|
| 1 | Model and review | sonnet/none; sonnet/required; opus | sonnet, review none (D6) |
| 2 | Live gates | run in CI; operator-approved only | Anything live or paid is operator-approved with `NS_LIVE_APPROVED=1` (D7); CI makes no paid calls and no cloud deployments |
| 3 | Government | claim parity; gate | Gated, not banned. No FedRAMP, ATO or parity claim in any artifact this PRP produces |
| 4 | Is the render in scope of PRP-26 | yes; separate | Separate and budget-gated (D10). PRP-26 ships storyboard source only |
| 5 | Approval record | chat message; file | File: `marketing/video/APPROVAL.md` with date, budget, approver and scope. A chat message is not an approval record. The file must exist before any paid media generation |
| 6 | Render tool | fixed now; chosen at execution | Chosen at execution time with the operator from supported generation or production tools; the choice, version and terms are written into `APPROVAL.md`. This PRP does not name or assume a vendor, price or model |
| 7 | Captions | optional; required | Required. A captions file ships with the MP4; a video without captions is not complete (accessibility per NS-10) |
| 8 | Voice and likeness | any; synthetic and licensed | Only synthetic or properly licensed voice and imagery with terms recorded in `APPROVAL.md`. No real person's likeness or voice without written permission |
| 9 | Content source | new script; reviewed storyboard | Only the reviewed PRP-26 storyboard. New claims require a storyboard change reviewed under PRP-26 rules first |
| 10 | Budget overrun | continue; stop | Stop at the approved cap and report the shortfall; do not exceed it or seek silent extension |
| 11 | Binary storage | commit MP4; external | Decided at execution by file size and policy; the manifest records the path or storage location and a checksum either way. Large binaries are not committed without operator agreement |
| 12 | Demo data in video | production; sandbox | Sandbox only, isolation banner visible; no production data or real names |

## Context manifest

### Files that matter
- `PRP.md` - sections 1-3 (binding preamble).
- `docs/PRD.md` - NS-10 text (line 45 onward).
- `docs/ARCHITECTURE.md`, `docs/RESEARCH-AND-GATES.md` (G09 row), `docs/DECISIONS-LOG.md` (D6, D7, D10), `docs/adr/0002-stack-pins.md`.
- `pyproject.toml`, `docker-compose.yml`, `infra/compose/eventhubs.config.json`, `.claude/hooks/config.ps1`, `.env.example`, `scripts/validate_planning.py`.
- Created by PRP-26: `marketing/video/storyboard/` (source of truth for scenes, narration, caption text), `marketing/MANIFEST.md`, `marketing/deck/claims-checklist.md`, `tests/marketing/claims_rules.py`, `tests/marketing/test_manifest_paths.py`.
- Created by PRP-25: published docs used to re-verify claims.
- Created by PRP-24: sandbox mode and banner used for any screen capture.
- Created by this PRP: `marketing/video/APPROVAL.md`, `marketing/video/render/`.
- Operator inputs not in the repo: approved budget, approver, chosen pipeline account. These are never stored in files as credentials.

### Patterns to match
- Pydantic v2 models with `model_config = ConfigDict(extra="forbid")`; generated contract code is never hand-edited.
- FastAPI routers per module under `services/api/neurosphere_api/<module>/router.py`.
- Async Azure SDK clients come from `packages/core/neurosphere_core/clients`; errors are the exceptions in `neurosphere_core.errors`.
- Tests sit beside packages; cross-package suites live in `tests/`; markers `pytest.mark.live` and `pytest.mark.integration` are declared in root `pyproject.toml`.
- TypeScript strict with `@fluentui/react-components`; Vitest + Testing Library for unit tests; Playwright under `frontend/tests/e2e`.
- The render entry point is a small script under `marketing/video/render/` that reads `APPROVAL.md`, refuses if it is missing or malformed, and logs spend; tests use a stub backend and make no paid calls.
- Credentials for any generation service come from the environment or vault at run time, never from a file or the conversation.

### Conventions
- ruff line 100, py312, S rules on (root `pyproject.toml`); pyright standard; conventional commits; owned-file discipline (an item edits only its declared files).
- Evidence under `docs/evidence/<gate>/`; live scripts under `scripts/gates/` refuse without `NS_LIVE_APPROVED=1`.
- Forward slashes only in commands. No em-dashes in docs. Temp files go in `temp/` (gitignored).
- Approval and spend records are Markdown with dated rows; no credential values anywhere. CI never runs the render; tests cover the guard and caption/narration consistency only.

### Gotchas
- Event Hubs has no DLQ: quarantine is an explicit container + replay CLI; checkpoints advance only after durable accept or quarantine. Metadata geo-DR copies neither payloads nor RBAC.
- `IdentityScope` is derived server-side; caller- or model-supplied `domain_id`/`customer_id` is ignored. Same scope object on REST, search, cache keys, exports, WebSocket, copilot tools, MCP.
- No LLM-generated SQL/Cypher/KQL/JS. Charts are a Vega-Lite subset (no `expr`, signals, external `url` data) rendered with `vega-interpreter` in a sandboxed iframe.
- Government is gated, not banned: disabled-with-reason from the capability matrix; separate endpoints (`login.microsoftonline.us`, `*.documents.azure.us`, `*.servicebus.usgovcloudapi.net`, `*.search.azure.us`). Never route Government data to Commercial.
- Fail closed: policy store outage returns 503. Privileged roles are scoped; no bypass.
- One action executor for button/chat/REST/MCP; same intent hash; permission and target version rechecked at execution; read-only connectors are advisory; no catalog-only pretend swaps.
- Costs: null/unknown never 0; estimated vs invoiced always distinct; projections cite price version. Provider billing freshness is not sub-10s.
- Catalog: raw events outside the graph; locks affect presented lineage not observations; traversals budgeted; ETag mismatch returns `stale_version`. Outbox is the projection baseline, not emulator change feed.
- Emulators: Event Hubs emulator lacks Entra, so producer identity is enforced at the ingest edge; Cosmos vNext emulator has no RU accounting, no sprocs/triggers/UDF, no range/composite/spatial indexes, so G03 emulator evidence is "bounded feasibility" only.
- `scripts/gates/*` refuse without `NS_LIVE_APPROVED=1`; missing live evidence is an open gate, never a skipped green test. No paid model calls in CI.
- No FedRAMP/ATO/parity claims. Availability, GA and authorization are separate matrix columns.
- Secrets via vault references; dev issuer only when `NS_ENV=local`; never read `.env`. Pseudonymize people; prompt/response bodies off by default; redact before archive and before any external transmission (judges, connectors).
- Hidden navigation is not authorization; the API must deny.
- Versions: Python 3.12, Node 24, TypeScript 6.0.x (not 7), Helm 4, MkDocs Material 9.7 (EOL 2026-11-05, evaluate Zensical), sigma 4 + graphology (never @cosmograph, CC-BY-NC), MCP SDK 2.x (spec 2026-07-28). See docs/adr/0002-stack-pins.md.
- CI contains no `|| true`; `scripts/validate_planning.py` fails if it does. Python is `python`, not `python3`.
- PRP-specific: no paid generation call before `marketing/video/APPROVAL.md` exists. The guard is code, not a promise; test that the entry point exits non-zero without the file.
- PRP-specific: the pipeline is a supported generation or production tool chosen at execution with the operator. Do not invent an API, model name, SKU, price or duration limit; record what the chosen tool actually documents on the observed date.
- PRP-specific: captions are required. A rendered MP4 without a captions file is incomplete; also check caption timing against audio by playback.
- PRP-specific: media generators can add text, logos, watermarks or implied endorsements. Review frames for stray marks; no Microsoft logo or badge; remove or regenerate offending output.
- PRP-specific: generated narration or visuals may state things the storyboard does not. Re-run the claims lint on the final transcript, not only on the storyboard.
- PRP-specific: no claim of completion until the MP4 and captions exist and were played back. "Pipeline configured" is not "video produced".
- PRP-specific: G09 is closed only by Product and legal/accessibility reviewers. This PRP records evidence; it does not self-approve.

### External references
- Decision D10 (video descoped, budget-gated): docs/DECISIONS-LOG.md, 2026-10-08.
- WebVTT: https://www.w3.org/TR/webvtt1/ ; WCAG 2.2 captions (prerecorded) success criterion 1.2.2: https://www.w3.org/TR/WCAG22/ .
- Chosen generation or production tool documentation and terms: recorded in `marketing/video/APPROVAL.md` with the observed date at execution.
- Gate register row G09: docs/RESEARCH-AND-GATES.md.

## Implementation blueprint

### Item 1 - budget-approval-record
- Deliverable: `marketing/video/APPROVAL.md` recording operator approval, budget cap, approved pipeline and terms, and voice/likeness licensing; a guard test.
- Owned files (may edit): `marketing/video/APPROVAL.md`, `tests/marketing/test_render_guard.py`.
- Must NOT touch: `marketing/video/render/`, `marketing/video/storyboard/` (PRP-26), `marketing/MANIFEST.md`, `docs/RESEARCH-AND-GATES.md`, `.env.example`.
- Depends on: none (needs the operator).
- Acceptance criteria:
  - File contains date, budget amount and currency, approver, approved tool and scope, licensing terms; no credential values.
  - The guard test fails the render entry point when the file is absent or has an empty field.
  - Written by or confirmed by the operator; an agent does not fabricate an approval.
- Pattern references: `scripts/gates/` refusal style (`NS_LIVE_APPROVED=1` pattern) for the guard behavior.
- Tests to write: `tests/marketing/test_render_guard.py`.

### Item 2 - render-pipeline
- Deliverable: the render script and its outputs: captioned explainer video (MP4) and captions file, built from the reviewed storyboard through the approved tool, plus a spend log.
- Owned files (may edit): `marketing/video/render/`, `tests/marketing/test_caption_consistency.py`.
- Must NOT touch: `marketing/video/APPROVAL.md`, `marketing/video/storyboard/`, `marketing/MANIFEST.md`, `docs/RESEARCH-AND-GATES.md`, `.github/workflows/`, root `pyproject.toml`.
- Depends on: Item 1.
- Acceptance criteria:
  - MP4 and captions file exist under `marketing/video/render/` (or a recorded external location with checksum) and were played back by a human named in the spend log.
  - Captions text matches the storyboard narration within the tolerance documented in the test; claims lint passes on the final transcript.
  - Spend never exceeds the approved cap; the script stops at the cap and logs it.
  - The script refuses without `APPROVAL.md`.
- Pattern references: storyboard format from PRP-26; guard pattern from item 1.
- Tests to write: `tests/marketing/test_caption_consistency.py`.

### Item 3 - manifest-update
- Deliverable: manifest rows updated to reflect the rendered video and its captions; G09 row notes the new evidence.
- Owned files (may edit): `marketing/MANIFEST.md`, `docs/RESEARCH-AND-GATES.md` (G09 row only).
- Must NOT touch: any other row of `docs/RESEARCH-AND-GATES.md`, `marketing/video/render/`, `marketing/video/APPROVAL.md`, `marketing/deck/`.
- Depends on: Item 2.
- Acceptance criteria:
  - Video marked `rendered` with the real path (or storage location and checksum) and the captions path; the "not rendered, see PRP-27" text is removed only because the files exist.
  - G09 row cites the evidence and stays OPEN unless the named reviewers approve; never marked CLOSED by this PRP alone.
  - The manifest path-exists test from PRP-26 passes with the added rows.
- Pattern references: PRP-26 manifest format.
- Tests to write: none new; existing `tests/marketing/test_manifest_paths.py` (PRP-26) must pass.

## Validation gates
```
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode fast    # per item
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full    # before merge
python scripts/validate_planning.py
```
Feature-specific:
```
python -m pytest tests/marketing
```
The actual render is **operator-approved, requires a recorded budget in marketing/video/APPROVAL.md** and is run by the operator or under their explicit direction, never in CI. The render entry point name is chosen by the item 2 implementer and recorded in `marketing/video/render/README.md`; its refusal-without-approval behavior is covered by `tests/marketing/test_render_guard.py`.

## Live and open gates
- G09 (theme/brand/media review): the rendered, captioned video is the last media evidence G09 lists. This PRP narrows G09; closure needs Product and legal/accessibility sign-off.
- If budget approval never arrives, this PRP stays in backlog and G09 stays OPEN with "video not rendered".
- If a live item did not run, record it OPEN in the completion note and in docs/RESEARCH-AND-GATES.md; never report it as a skipped green test.

## NOT building
- Storyboard, scripts, deck, persona scripts (PRP-26).
- Docs site or assistant (PRP-25); themes and accessibility audit (PRP-24).
- Any media generation before the approval record exists.
- Localized or multiple-length cuts, social variants, or a video hosting platform.
- Brand or legal approval.

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [x] All clarification questions are decided, not guessed

## Completion note (filled at ship)
- Date:
- Merged commits:
- Deviations from blueprint and why:
- Descoped items:
- Approval record: date, approver, budget (or OPEN, in which case nothing was rendered):
- Spend vs cap:
- MP4 and captions paths, playback reviewer:
- G09 status after this PRP:
- Follow-ups:
