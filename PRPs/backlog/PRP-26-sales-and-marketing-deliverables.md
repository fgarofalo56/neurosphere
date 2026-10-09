---
name: prp-26-sales-and-marketing-deliverables
status: backlog
review: required
created: 2026-10-08
model: sonnet
phase: 5
ns: NS-10
depends_on: PRP-24, PRP-25
wave: W9
absorbs: P5.3 deck + scripts
---

# PRP-26: Sales and marketing deliverables

## Goal
Ship a walking sales deck (Markdown source plus an actual PPTX), persona demo scripts tied to sandbox walkthroughs, a video storyboard and script source, and an honest asset manifest. It is for sellers and evaluators who need factual, reviewable collateral. It lands in W9 because every claim must be checked against the finished product docs (PRP-25) and the sandbox and accessibility work (PRP-24). The explainer video render is deliberately not here: it is the budget-gated follow-up PRP-27 (decision D10).

> Deliver sales walking deck source and PPTX, persona demo scripts, marketing storyboard/scripts and captioned explainer videos with reviewed factual claims. Treat media production as explicit deliverables, not pretend generated files.

## Acceptance criteria
- [ ] Item 1: `marketing/deck/` holds the Markdown source and a rendered `.pptx` that opens; a claims-reviewed checklist lists every factual claim in the deck with its supporting doc path and reviewer.
- [ ] Item 2: Each persona script (Viewer, Analyst, Steward, Admin, Auditor) maps to an existing sandbox walkthrough in `docs/walkthroughs/` and lists the sandbox scenario and expected on-screen result.
- [ ] Item 3: The storyboard and narration script exist as source only, with a claims list reviewed against docs; no rendered media is checked in or referenced as complete.
- [ ] Item 4: `marketing/MANIFEST.md` lists every asset with status (draft or rendered), path, owner and review state; no placeholder is reported complete; the video row reads "not rendered, see PRP-27".
- [ ] No artifact claims FedRAMP authorization, ATO, compliance parity, uniqueness, savings or completeness without cited evidence (checked by a claims lint test).
- [ ] PRP exit: items 1-4 green under `verify-gates -Mode full`; independent review (review: required) approves; G09 stays OPEN until brand and legal review.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|---|---|---|
| 1 | Model and review | sonnet/none; sonnet/required; opus | sonnet, review required (D6) |
| 2 | Live gates | run in CI; operator-approved only | Anything live or paid is operator-approved with `NS_LIVE_APPROVED=1` (D7); CI makes no paid calls and no cloud deployments |
| 3 | Government | claim parity; gate | Gated, not banned. No FedRAMP, ATO or parity claim in any artifact this PRP produces |
| 4 | Video in this PRP | include render; storyboard only | Storyboard and script source only. The render is PRP-27 and budget-gated (D10) |
| 5 | PPTX production | hand-built; generated from Markdown | Generated from the Markdown source by a script or tool chosen at execution and recorded in the deck README, so the PPTX is reproducible. The PPTX must exist and open before item 1 is complete |
| 6 | Brand and logos | bundle Microsoft marks; neutral | Neutral visual identity. No Microsoft logo, badge or partner implication; third-party names appear only as plain text where factually needed |
| 7 | What counts as a claim | only numbers; any assertion | Any assertion about capability, availability, performance, savings, compliance or competition. Each needs a doc citation or is removed |
| 8 | Performance numbers | quote targets as facts; quote as targets | Quote only PRD planning targets, labelled as targets, or measured numbers with an evidence path. Never unlabelled |
| 9 | Government messaging | imply availability; state gating | State that Government support is gated by the capability matrix and that availability, GA and authorization are separate; no FedRAMP, ATO or parity statement |
| 10 | Demo data | production; sandbox | Synthetic sandbox only, with the isolation banner visible. Never production data (project rule) |
| 11 | Draft vs rendered | both called done; honest status | The manifest distinguishes `draft` and `rendered`. A script or storyboard is draft; only an opened, reviewed deliverable file is rendered |
| 12 | Reviewer | author; independent | `review: required`: one independent pass for claim accuracy, security and PII; max one rework round |

## Context manifest

### Files that matter
- `PRP.md` - sections 1-3 (binding preamble).
- `docs/PRD.md` - NS-10 text (line 45 onward) and objectives (line 6).
- `docs/ARCHITECTURE.md`, `docs/RESEARCH-AND-GATES.md` (G09 row: OPEN, approved brand claims, 508/WCAG tests, rendered deck and video), `docs/DECISIONS-LOG.md` (D6, D7, D10), `docs/adr/0002-stack-pins.md`.
- `pyproject.toml`, `docker-compose.yml`, `infra/compose/eventhubs.config.json`, `.claude/hooks/config.ps1`, `.env.example`, `scripts/validate_planning.py`.
- Created by PRP-24: `docs/accessibility/` results (cite, do not overstate), sandbox mode and banner.
- Created by PRP-25: `docs/walkthroughs/` persona walkthroughs, `docs/runbooks/`, `docs/reference/`, published site.
- Created by PRP-03: `sandbox/` generator and seeded anomalies the scripts demonstrate.
- Feature docs to cite if merged (PRP-14 to PRP-19): dashboards, recommendations, quality, actions, map and replay, copilot. Claims about unmerged features are not allowed.
- Created by this PRP: `marketing/deck/`, `marketing/scripts/`, `marketing/video/storyboard/`, `marketing/MANIFEST.md`, `tests/marketing/`.

### Patterns to match
- Pydantic v2 models with `model_config = ConfigDict(extra="forbid")`; generated contract code is never hand-edited.
- FastAPI routers per module under `services/api/neurosphere_api/<module>/router.py`.
- Async Azure SDK clients come from `packages/core/neurosphere_core/clients`; errors are the exceptions in `neurosphere_core.errors`.
- Tests sit beside packages; cross-package suites live in `tests/`; markers `pytest.mark.live` and `pytest.mark.integration` are declared in root `pyproject.toml`.
- TypeScript strict with `@fluentui/react-components`; Vitest + Testing Library for unit tests; Playwright under `frontend/tests/e2e`.
- Marketing sources are Markdown with a front matter block (`status: draft|reviewed`, `claims:` list) so a lint test can parse them.
- One script per persona; each script cites the walkthrough file it follows and the sandbox scenario id.

### Conventions
- ruff line 100, py312, S rules on (root `pyproject.toml`); pyright standard; conventional commits; owned-file discipline (an item edits only its declared files).
- Evidence under `docs/evidence/<gate>/`; live scripts under `scripts/gates/` refuse without `NS_LIVE_APPROVED=1`.
- Forward slashes only in commands. No em-dashes in docs. Temp files go in `temp/` (gitignored).
- Claims lint lives in `tests/marketing/`; manifest paths must exist on disk (test). PPTX binaries are committed only if small and reviewed; otherwise the manifest records the build command and artifact location.

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
- PRP-specific: documents are not deliverables. A deck described but not built, or a PPTX that fails to open, is not complete; open the file and record that you did.
- PRP-specific: do not say "first", "only", "unique", "best", "saves X percent" or "compliant" without cited evidence. PRD objectives forbid authorization, savings, uniqueness and completeness claims without it.
- PRP-specific: persona scripts must be runnable against the sandbox as written; a script that references a screen that does not exist is a defect.
- PRP-specific: the storyboard is not the video. Do not write "explainer video delivered" anywhere; the manifest states "not rendered, see PRP-27".
- PRP-specific: no real customer names, people, or production screenshots; screenshots come from the synthetic sandbox only and must show the isolation banner.
- PRP-specific: third-party product names (Azure, Fabric, Foundry) are used factually and never as implied endorsement; no unapproved badges (NS-10).
- PRP-specific: G09 needs product and legal/accessibility review that this PRP cannot perform; leave it OPEN.

### External references
- PRD NS-10 and objectives: docs/PRD.md lines 6 and 45-48.
- Gate register row G09: docs/RESEARCH-AND-GATES.md.
- Decisions D6 and D10: docs/DECISIONS-LOG.md (2026-10-08).
- PPTX generation tool: chosen and version-pinned at execution; record the choice and observed date in `marketing/deck/README.md`.
- Microsoft brand and logo usage rules: confirm at execution before any third-party mark is considered; default is no marks.

## Implementation blueprint

### Item 1 - walking-deck  [P]
- Deliverable: Markdown source of the walking deck and a rendered PPTX built from it, with a claims-reviewed checklist, a build note, and the shared claims lint rules.
- Owned files (may edit): `marketing/deck/`, `tests/marketing/claims_rules.py`, `tests/marketing/test_deck_claims.py`, `tests/marketing/test_deck_pptx_exists.py`.
- Must NOT touch: `marketing/scripts/`, `marketing/video/`, `marketing/MANIFEST.md`, `docs/` (all), other files in `tests/marketing/`, root `pyproject.toml`, `docs/RESEARCH-AND-GATES.md`.
- Depends on: none.
- Acceptance criteria:
  - PPTX exists, opens, slide count matches the source, speaker notes present; the open check is recorded in `marketing/deck/README.md`.
  - `marketing/deck/claims-checklist.md` maps every factual claim to a doc path and a reviewer; unreviewed claims are marked and block `reviewed` status.
  - Claims lint finds no banned phrase (authorized, ATO, FedRAMP compliant, parity, unique, guaranteed) outside a negation or a "not" statement.
- Pattern references: sandbox screenshots from PRP-24 banner; NS-10 text.
- Tests to write: `tests/marketing/test_deck_claims.py`, `tests/marketing/test_deck_pptx_exists.py`.

### Item 2 - persona-scripts  [P]
- Deliverable: demo scripts for Viewer, Analyst, Steward, Admin and Auditor, plus a feature-to-persona map.
- Owned files (may edit): `marketing/scripts/`, `tests/marketing/test_scripts_map_to_walkthroughs.py`.
- Must NOT touch: `marketing/deck/`, `marketing/video/`, `marketing/MANIFEST.md`, `docs/walkthroughs/` (PRP-25), `sandbox/` (PRP-03), `tests/marketing/claims_rules.py`.
- Depends on: none.
- Acceptance criteria:
  - Every script cites an existing `docs/walkthroughs/` file and a sandbox scenario id (test resolves both paths).
  - Each script lists exact steps, expected on-screen result, and the permission the persona needs.
  - Scripts demonstrate only merged features; anything pending is labelled "planned" and excluded from the demo path.
- Pattern references: PRP-25 walkthrough format.
- Tests to write: `tests/marketing/test_scripts_map_to_walkthroughs.py`.

### Item 3 - video-storyboard  [P]
- Deliverable: storyboard (scenes, visuals, narration, on-screen text, caption text) and script source for the explainer video; claims list. No rendered media.
- Owned files (may edit): `marketing/video/storyboard/`, `tests/marketing/test_storyboard_claims.py`.
- Must NOT touch: `marketing/video/APPROVAL.md` and `marketing/video/render/` (PRP-27), `marketing/deck/`, `marketing/scripts/`, `marketing/MANIFEST.md`, `tests/marketing/claims_rules.py` (read-only import).
- Depends on: none (imports the lint rules file owned by item 1 at test time).
- Acceptance criteria:
  - Each scene lists narration, on-screen text, source docs for every claim, and caption text so captions can be produced without rewriting.
  - Claims lint passes; the storyboard states it is source only and not a rendered video.
  - Total narration length and scene timing are stated as estimates.
- Pattern references: claims lint rules from item 1.
- Tests to write: `tests/marketing/test_storyboard_claims.py`.

### Item 4 - asset-manifest
- Deliverable: manifest of every marketing asset with status, path, owner, review state and build command.
- Owned files (may edit): `marketing/MANIFEST.md`, `tests/marketing/test_manifest_paths.py`.
- Must NOT touch: `marketing/deck/`, `marketing/scripts/`, `marketing/video/`, `docs/RESEARCH-AND-GATES.md`.
- Depends on: Items 1, 2, 3.
- Acceptance criteria:
  - Every listed path exists on disk (test); statuses are `draft` or `rendered` only.
  - Deck row is `rendered` only if the PPTX opened and was reviewed; scripts and storyboard are `draft` until independently reviewed.
  - Video row reads "not rendered, see PRP-27"; the G09 note says OPEN pending brand and legal review.
- Pattern references: plain Markdown table.
- Tests to write: `tests/marketing/test_manifest_paths.py`.

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
There is no live script and no paid call in this PRP. Opening the PPTX and recording that you did is a manual step captured in `marketing/deck/README.md`.

## Live and open gates
- G09 (theme/brand/media review): stays OPEN. This PRP supplies the actual rendered deck and the claims checklist; brand approval, legal review and the rendered, captioned video (PRP-27) are still required.
- Any claim without evidence is removed, not left as a TODO.
- If a live item did not run, record it OPEN in the completion note and in docs/RESEARCH-AND-GATES.md; never report it as a skipped green test.

## NOT building
- The explainer video render, narration audio or captions files (PRP-27).
- Paid media generation of any kind.
- Brand identity, logo design, legal review or approval of brand claims (G09 reviewers).
- Product screenshots from non-sandbox data; customer case studies; pricing.
- Changes to docs, walkthroughs, sandbox or product code.

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
- PPTX opened and reviewed (who, when):
- Claims removed during review:
- G09 status after this PRP (expected OPEN):
- Follow-ups:
