---
name: PRP-36-tracker-and-docs-truth-up
status: backlog
priority: P0
order: 19
review: none
created: 2026-11-14
model: sonnet
orchestrator_model: sonnet
implementer_model: sonnet
phase: 6
ns: NS-08, NS-10
depends_on: []
wave: W11
branch: prp-36-docs-truth-up
allow_parallel: true
issues: [225, 41, 148]
---

# PRP-36: Tracker and docs truth-up

## Goal
Make the documents a fresh session reads first say what is true, so the ten parallel PRP sessions of waves W11 to W21 are not misled. Today the README says every workspace member is a stub and the repository is private, the master index says "PRP-00 to PRP-32" and "Repo is private", three rows in `docs/RESEARCH-AND-GATES.md` describe work that has since shipped, and the threat model lists tests as "Planned" that exist. This PRP is docs, tracker and one hook line only. It runs alone as wave W11 (no other PRP edits these files), so it may edit the gate register rows directly.

Out of scope: any code under `packages/`, `services/`, `frontend/` or `infra/`; shipped PRP files (completion notes stay as history, including PRP-02's stale note); the wave plan itself (`PRPs/EXECUTION-PLAN.md`, owned by the orchestrator); the `.env.example` edit itself (agents cannot write it, see item 5); threat-model rows whose gap is still real (allowed-read audit goes to PRP-48, the APIM rate limit to PRP-52); live-gate evidence (PRP-64).

## Why
- `README.md:10-17` still says "Each member is a stub with a smoke test; no product features ... exist yet" and "This repository is private". 31 PRPs are shipped and the repository is PUBLIC (PRP-13 follow-up (b) already noted this).
- `docs/DECISIONS-LOG.md:17` records D1 as "Repository is private"; `PRPs/PRP-MASTER-neurosphere.md:84` (prerequisite 4, "Repo is private (decision D1)") and `:205` (D1 row) repeat it. Operator intent is public, and `CLAUDE.md` still says a push is publication.
- `PRPs/PRP-MASTER-neurosphere.md:11` says it "sequences PRP-00 to PRP-32"; the wave table (`:99-112`) ends at W10 and the Mermaid graph (`:115-146`) ends at PRP-32. Waves W11 to W21 cover PRP-11, 15, 18, 21, 23 (round 2) and PRP-36 to PRP-64.
- `docs/RESEARCH-AND-GATES.md:38` (G16) lists "Cosmos evaluation store, hosting `EvaluationService`, an Azure blob reader, production bootstrap of `app.state.evaluation_store`" as OPEN although those shipped in PRP-16 round 2; `:31` (G06) says durable hold and queue stores "are follow-ups"; `:46-47` says "No live evidence exists" for PRP-32 although `docs/evidence/PRP-32/` holds 2026-10-27 and 2026-10-28 deploy, smoke and seed-access evidence. (Re-read each row against `PRPs/shipped/PRP-16-*.md`, `PRP-23-*.md` and `docs/evidence/PRP-32/README.md` before editing; lane-g flagged them, the exact wording is the implementer's to verify.)
- `docs/RESEARCH-AND-GATES.md` has no mention of AI Search `InsufficientResourcesAvailable` (hit in the PRP-08 live run, see `PRPs/shipped/PRP-08-deployment-intelligence-and-iac.md` Execution state item 7) or the Key Vault 90-day name reservation (`docs/deploy/hosted-demo.md:509`); issue #41 asks for both.
- `docs/security/threat-model.md:340` lists `services/workers/tests/actions/test_recheck.py` as "Planned" but the test is `services/workers/tests/action_executor/test_recheck.py`; `:358` lists `packages/core/tests/mcp/test_ssrf.py` but the file is `packages/core/tests/mcp_core/test_mcp_ssrf.py`; `:388-395` still says no `DenialRecorder` is installed and `ConsentAuditSink` has no adapter, but the recorder is composed (`services/api/neurosphere_api/runtime/builders/authz.py:116,204,345`) and the consent adapter exists (`services/api/neurosphere_api/deploy/scan/audit.py:134`).
- `.githooks/pre-commit:66-73` regenerates the master status table but not `PRPs/INDEX.md`; `python scripts/prp_status.py --check` passes while `prp_index check` can fail on a stale index (lane-g point 5).

## Acceptance criteria
- [ ] README: the Status section describes the real state (what ships, that the repository is public, no FedRAMP/ATO/parity claim kept); no line says the members are stubs or that the repository is private. `git grep -n "is private\|stub with a smoke" README.md` is empty.
- [ ] Decisions: `docs/DECISIONS-LOG.md` D1 and master D1 (`:205`) and prerequisite 4 (`:84`) say the repository is public by operator decision with the date, keep "a push is publication; secrets are rotated, never just removed", and point to `SECURITY.md`. The master text no longer instructs agents to check "Repo is private".
- [ ] Master index: intro says it sequences PRP-00 to PRP-64; the wave table gains rows W11 to W21 listing PRP ids per wave and linking to `PRPs/EXECUTION-PLAN.md` for the full plan (no duplicated per-PRP detail); the Mermaid graph gains nodes and edges for every PRP-36 to PRP-64 `depends_on` edge and the round-2 PRPs; `python scripts/validate_planning.py` passes and `python scripts/prp_status.py --check` passes.
- [ ] Gate register: G16, G06 and the PRP-32 note no longer list shipped work as OPEN or "no live evidence"; each edited row cites the shipped PRP or evidence file that justifies the change; no gate changes status to CLOSED or NARROWED unless the cited evidence already says so. Issue #41: the AI Search capacity failure and the Key Vault 90-day name reservation are recorded under the G01 or G12 rows with the evidence file.
- [ ] Threat model: the two wrong test paths are corrected and marked "In repo"; the denial recorder and consent-audit rows say "In repo" with the file paths; the allowed-read-audit and APIM rate-limit rows stay "Gap" and name PRP-48 and PRP-52 as owners.
- [ ] `docs/dev/env-example-process.md` (new) documents how `.env.example` additions are made (agents list names in the completion note; the operator applies them with one batched script `temp/add-env-example.sh`, whose template is in the doc and never contains a value that looks like a secret).
- [ ] `.githooks/pre-commit` regenerates `PRPs/INDEX.md` next to the status table when a `PRPs/` file is staged, stages it, and degrades to a printed warning (not a block) when the kit script is absent. A hook test or a recorded manual run proves both paths.
- [ ] No file outside the Ownership block changed (`git diff --name-only` shown).

PRP exit: every box above ticked, `python scripts/validate_planning.py`, `python scripts/prp_status.py --check` and the `verify-gates.ps1` full run green, PR open, CI green.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| 1 | Repository visibility in docs | Say public; say private and flip the repo; say "visibility is an operator choice" | Public, as the repo is today; the secrets rule is unchanged. ASSUMPTION: the owner has no plan to flip it back (the memory note "repo is PUBLIC (D1 stale)" and the GHCR-public observation in `release.yml:15-16` support this). |
| 2 | Wave table detail | Duplicate the plan; link to it | Link: one row per wave with PRP ids, detail lives in `PRPs/EXECUTION-PLAN.md`. ASSUMPTION: that file exists when this PRP runs (the orchestrator creates it before W11). If it does not, stop and report instead of inventing it. |
| 3 | PRP-02 and other shipped completion notes | Edit; leave | Leave (shipped files are history). |
| 4 | `.env.example` | Edit directly; document a process | Document a process: `.env.example` is agent-blocked by a hook. Names are not re-listed here (the earlier #148 item 3 name list is UNVERIFIED). |
| 5 | INDEX regeneration in the hook | Hook; CI only | Hook, with graceful degradation, because CI already checks it and local fast-fail is the point. |

## Context manifest

### Files to read first
- `PRPs/PRP-MASTER-neurosphere.md` (`:11`, `:84`, `:94-146`, `:198-215`): the prose to correct; the status table between the `prp-status` markers is generated, never hand-edited.
- `README.md` (`:5-20`) and `docs/DECISIONS-LOG.md` (`:11-27`, D1 at `:17`).
- `docs/RESEARCH-AND-GATES.md` (rows G01, G06, G16 at `:26,:31,:38`; PRP-32 notes at `:46-52`).
- `docs/security/threat-model.md` (`:106-115`, `:330-365`, `:380-400`).
- `.githooks/pre-commit` (`:61-73` step 4, the PRPs block).
- `PRPs/shipped/PRP-16-*.md`, `PRPs/shipped/PRP-23-*.md`, `docs/evidence/PRP-32/README.md`: evidence for the stale rows.
- `PRPs/EXECUTION-PLAN.md`: the wave plan to link (orchestrator-owned).
- `scripts/prp_status.py`, `scripts/validate_planning.py`: what the validators accept (every PRP id in the master needs a file).

### Interfaces consumed
- The PRP files PRP-36 to PRP-64 as they exist in `PRPs/backlog/` (frontmatter `wave`, `depends_on`).
- `scripts/prp_status.py --write` and `--check`; the kit's `prp_index.py build|check` at `~/.claude/kits/orchestrated-prp/prp_index.py`.

### Interfaces provided
- `docs/dev/env-example-process.md` (new): the process every later PRP's completion note refers to under "Env vars for the operator".
- A pre-commit hook that keeps `PRPs/INDEX.md` current.

### Patterns to match
- The existing hook step style and `note()` helper at `.githooks/pre-commit:11-12,66-73`.
- Decision-row phrasing at `docs/DECISIONS-LOG.md:11` (D12: date, owner, what is not claimed).
- Gate-row phrasing: dated, cites evidence, says what stays OPEN (`docs/RESEARCH-AND-GATES.md:31`).

### Gotchas
- `scripts/prp_status.py` and the master file already carry uncommitted changes in the working tree at the time of writing (a `parse_depends` fix and a regenerated table). Start from a clean branch off `main` and confirm they have landed; do not re-do them.
- `validate_planning.py` scans the whole master text for `PRP-NN` and fails on an id with no file: mention only PRPs that exist in `PRPs/backlog/`, `active/` or `shipped/`.
- The master file is CRLF in some working copies; keep the existing line endings and do not reformat the generated table.
- Do not read `.env*`. Do not claim any gate closed without evidence already in the repo.
- Never name a secret value in the env-example doc; use `<value>` placeholders only.

Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership

```ownership
owns:
  - README.md
  - docs/DECISIONS-LOG.md
  - docs/RESEARCH-AND-GATES.md
  - docs/security/threat-model.md
  - PRPs/PRP-MASTER-neurosphere.md
  - .githooks/pre-commit
  - docs/dev/env-example-process.md
tier1: []
tier2_appends: []
must_not_touch:
  - packages/**
  - services/**
  - frontend/**
  - infra/**
  - PRPs/shipped/**
```

## Implementation blueprint

Parallelization: items 1 to 4 touch different files and are independent [P]; item 5 and 6 are independent of them; item 7 closes out.

### Item 1 - README status and decision D1  [P]
- Deliverable: rewrite the README Status paragraph from the shipped state (read `PRPs/PRP-MASTER-neurosphere.md` status table and `CHANGELOG.md` for what exists); remove the stub and private claims; update D1 in `docs/DECISIONS-LOG.md` (append a dated superseding row or reword, matching how that file treats later changes) and the two master spots.
- Owned files: `README.md`, `docs/DECISIONS-LOG.md`, `PRPs/PRP-MASTER-neurosphere.md` (lines `:84`, `:205` only).
- Must NOT touch: `SECURITY.md`, `CLAUDE.md`, `AGENTS.md`.
- Depends on: none.
- Acceptance criteria: the first two Acceptance boxes; `git grep -n "private" README.md PRPs/PRP-MASTER-neurosphere.md docs/DECISIONS-LOG.md` shows no remaining claim that the repository is private.
- Tests: `python scripts/validate_planning.py`; `uv run pytest -q tests/test_planning_alignment.py`.
- Pattern references: `docs/DECISIONS-LOG.md:11`.

### Item 2 - Master index waves, intro and graph  [P]
- Deliverable: intro says PRP-00 to PRP-64; wave table rows W11 to W21 (ids only, link to `PRPs/EXECUTION-PLAN.md`); Mermaid nodes and edges for PRP-36 to PRP-64 from each file's `depends_on`; render the diagram locally (`python scripts/render_mermaid.py` reads only `docs/ARCHITECTURE.md`, so render the master block by hand with the same mermaid-cli and keep the output under `temp/`, not committed) before claiming it renders.
- Owned files: `PRPs/PRP-MASTER-neurosphere.md` (prose and the graph only).
- Must NOT touch: the generated block between `<!-- prp-status:begin -->` and `end`.
- Depends on: none (item 1 edits other lines of the same file: do items 1 and 2 in one commit order, item 1 first).
- Acceptance criteria: third Acceptance box; the graph has no node without a file.
- Tests: `python scripts/validate_planning.py`; `python scripts/prp_status.py --check`.
- Pattern references: master `:115-146`.

### Item 3 - Gate register rows (#41)  [P]
- Deliverable: correct G16 (`:38`), G06 (`:31`) and the PRP-32 note (`:46-47`) against the shipped PRPs and evidence; add the AI Search `InsufficientResourcesAvailable` and Key Vault 90-day reservation findings (#41) with their evidence references, no live claim beyond what the evidence files say.
- Owned files: `docs/RESEARCH-AND-GATES.md`.
- Must NOT touch: evidence files under `docs/evidence/**`, other rows' status values.
- Depends on: none.
- Acceptance criteria: fourth Acceptance box; every changed sentence is traceable to a named file.
- Tests: `python scripts/validate_planning.py`; `uv run pytest -q tests/docs`.
- Pattern references: `docs/RESEARCH-AND-GATES.md:31,49`.

### Item 4 - Threat-model rows  [P]
- Deliverable: fix `:340` and `:358` paths and states, update `:388-395` for the denial recorder and consent adapter, leave the two real gaps with PRP-48 and PRP-52 named. Re-verify every other "Planned" test path in the file with a path-exists check (the lane audit found the two above; run the check again and fix any more).
- Owned files: `docs/security/threat-model.md`.
- Must NOT touch: `docs/security/dfd/**`.
- Depends on: none.
- Acceptance criteria: fifth Acceptance box; a one-off script run shows every `tests/...` or `*/tests/*` path in the file exists (paste output).
- Tests: `uv run pytest -q tests/docs`; `python scripts/validate_planning.py`.
- Pattern references: `docs/security/threat-model.md:333-338`.

### Item 5 - Env-example process doc  [P]
- Deliverable: `docs/dev/env-example-process.md`: why agents cannot edit `.env.example`, the batched operator script template for `temp/add-env-example.sh` (append-if-missing lines, idempotent, no values), and the rule that each PRP lists new `NS_*` names under "Env vars for the operator". Link it from `docs/dev/local-setup.md` is NOT done here (PRP-38 owns that file); mention the doc in the completion note instead.
- Owned files: `docs/dev/env-example-process.md` (new).
- Must NOT touch: `.env.example`, `docs/dev/local-setup.md`.
- Depends on: none.
- Acceptance criteria: sixth Acceptance box; `mkdocs` nav is unchanged (this is a dev note; if `mkdocs.yml` strict build complains about an unlisted page, list it as `not_in_nav` in a follow-up, do not edit `mkdocs.yml` here).
- Tests: `uv run pytest -q tests/docs`.
- Pattern references: `docs/dev/local-setup.md` headings.

### Item 6 - Pre-commit INDEX regeneration
- Deliverable: in step 4 of `.githooks/pre-commit`, after the status table, run `python -S -E ~/.claude/kits/orchestrated-prp/prp_index.py build`, stage `PRPs/INDEX.md`, and print a warning (no block) when the script is missing.
- Owned files: `.githooks/pre-commit`.
- Must NOT touch: `.githooks/pre-push`, `.github/workflows/secret-scan.yml`, scanner pattern lists.
- Depends on: none.
- Acceptance criteria: seventh Acceptance box; stage a one-line change to a PRP file in a scratch clone or temp index and show INDEX updates; rename the kit path temporarily (env override or a copy of the hook run with a bad path) and show the warning and exit 0. State plainly which of the two was run.
- Tests: manual run output pasted; `bash -n .githooks/pre-commit`.
- Pattern references: `.githooks/pre-commit:66-73`.

### Item 7 - Integration and close-out
- Deliverable: run `python scripts/prp_status.py --write` and the kit index build; CHANGELOG `[Unreleased]` one line (the close-out commit may touch `CHANGELOG.md`, per the reference); fill the completion note; list follow-ups (issue #148 items 1, 2, 4 are other PRPs).
- Owned files: the Ownership block plus `CHANGELOG.md` (one `[Unreleased]` line, close-out commit only) and the generated `PRPs/INDEX.md`.
- Depends on: items 1 to 6.
- Acceptance criteria: Validation gates pass; `git diff --name-only` lists only owned files.
- Tests: the gates below.

## Validation gates
```bash
python scripts/validate_planning.py
python scripts/prp_status.py --check
python -S -E ~/.claude/kits/orchestrated-prp/prp_index.py check
uv run pytest -q tests/test_planning_alignment.py tests/docs
git grep -n "is private\|stub with a smoke" -- README.md PRPs/PRP-MASTER-neurosphere.md docs/DECISIONS-LOG.md
bash -n .githooks/pre-commit
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```
The `git grep` must print nothing. Owned files only: confirm with `git diff --name-only origin/main`.

## Migration and rollback
None for data or schema (documents and one hook line). Revert is a plain `git revert` of the PR; the hook change degrades safely when the kit script is absent, so no developer machine is blocked.

## Live and open gates
No live run, no `NS_LIVE_APPROVED=1`, no paid call. Nothing here changes a gate status; every OPEN gate stays OPEN and is handled by PRP-64 where the plan says so.

## NOT building
- Code changes of any kind, or edits to shipped PRP files.
- A new wave plan (the orchestrator owns `PRPs/EXECUTION-PLAN.md`).
- The `.env.example` edit itself.
- Re-opening decision D1 (the repository stays public; this PRP only makes the text true).

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [x] All clarification questions are decided, not guessed (row 1 and row 2 carry ASSUMPTION flags to confirm at plan approval)

## Execution state

| Item | Status | Branch/worktree | Notes |
|---|---|---|---|
| 1 | merged | prp-36-docs-truth-up | see commit |
| 2 | merged | prp-36-docs-truth-up | see commit |
| 3 | merged | prp-36-docs-truth-up | see commit |
| 4 | merged | prp-36-docs-truth-up | see commit |
| 5 | merged | prp-36-docs-truth-up | see commit |
| 6 | merged | prp-36-docs-truth-up | see commit |
| 7 | verifying | prp-36-docs-truth-up | gates run locally; CHANGELOG, INDEX, status table, close-out are merge-step Tier 3 |

## Completion note (filled at ship)
- Date and PR:
- Deviations:
- Descoped items:
- OPEN gates:
- Env vars for the operator:
- Follow-up issues:
- Product check:
