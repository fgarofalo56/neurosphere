---
name: PRP-81-compliance-mappings-soc2-iso27001-gdpr
status: backlog
priority: P2
order: 71
review: required
created: 2026-11-16
model: sonnet
orchestrator_model: sonnet
implementer_model: sonnet
phase: 7
ns: NS-08
depends_on: [PRP-70-contracts-revision-restored-scope]
wave: W25
branch: prp-81-compliance-mappings
allow_parallel: true
issues: []
---

# PRP-81: Compliance mappings for SOC 2, ISO 27001, GDPR and NIST 800-53

## Goal
Add four frameworks to the control library that PRP-56 shipped, as data: the AICPA SOC 2 Trust Services Criteria, ISO/IEC 27001 Annex A, the GDPR (Regulation (EU) 2016/679) and NIST SP 800-53 Rev 5. Each framework lists the controls NeuroSphere can say something about, each with a control identifier, a short label written for this product, a source link and retrieval date, and a support status plus evidence sources drawn from the five read-only sources PRP-56 already built. The existing bundle builder, API and `/compliance` page then show these frameworks with no code change beyond tests. The 800-53 framework is the existing SSP mapping (`docs/compliance/ssp/control-mapping.yaml`) made available inside the product, with a drift test so the two cannot diverge. It is for the auditor who must show a framework owner what evidence exists, and for PRP-83, which maps the data-subject and residency controls it builds to GDPR articles. It runs in W25 on PRP-70, which extends the `FrameworkId` enumeration.

This is a mapping and an evidence collector, never a verdict: no file, label, API field, page string or bundle says that NeuroSphere or a customer is compliant, certified, attested or authorized, and nothing here claims a SOC 2 report, an ISO certificate, GDPR adequacy, FedRAMP authorization or an ATO. Control identifiers and short labels are stored; the text of the standards is not.

Out of scope: any SOC 2 report, ISO certification or attestation workflow (organisational, outside the baseline per `docs/PRD.md:57`); the lifecycle, data-subject and residency features themselves (PRP-83); new evidence sources (PRP-56 owns the five; a new source is a separate PRP); NeuroSphere's own SSP, POA&M and plans (PRP-23 owns `docs/compliance/**`); FINRA and other frameworks; scoring, percentages and pass or fail of any kind.

## Why
Original PRD (2026-10-02, `git show 9fbf5f4c:docs/PRD.md`), section 5g, restored in mapping form:
- Criterion: "Documented mapping of platform controls to SOC 2 Trust Services Criteria and ISO 27001 Annex A controls."
- Description: "Platform architecture and operating procedures designed to support SOC 2 Type II attestation, ISO 27001 certification, FedRAMP-aligned controls for government customers, and GDPR data-subject rights."
- Success metric "SOC 2 Type II report issued; ISO 27001 cert in progress" is an organisation's attestation and is NOT restored (see Out of scope).

What v1.2 removed or demoted: `docs/PRD.md:39` narrows compliance to "Map to applicable NIST 800-53 Rev 5 and agency requirements"; `docs/PRD.md:57` puts "formal certifications" outside the baseline; the words SOC 2, ISO 27001 and GDPR appear nowhere in v1.2 (grep of `docs/PRD.md`, `PRP.md`, `packages`, `services`, `frontend` finds none outside PRP-56's own notes).

Evidence from the current tree (re-verified in this worktree):
- `FrameworkId` is a closed four-value enum (`packages/contracts/python/neurosphere_contracts/compliance/v1/control.py:18-21`); PRP-70 extends it with the four new ids (tokens per PRP-70 "Interfaces provided"; the planned values are `soc2_tsc`, `iso_27001_annex_a`, `gdpr`, `nist_800_53_r5`); PRP-70 fold F2 adds `eu_ai_act` and `iso_42001` too, which have no library file until PRP-128.
- The library holds four YAML files with 19, 8, 13 and 8 controls (`packages/core/neurosphere_core/compliance/library/*.yaml`); the loader reads every `*.yaml` in the directory and validates each row against the contract models (`compliance/loader.py:120-158`), so a new framework is a new file plus a contract enum value.
- The 800-53 mapping exists only as documentation: 64 control rows with status, narrative and evidence paths (`docs/compliance/ssp/control-mapping.yaml`), checked by `tests/compliance/test_control_mapping.py`.
- The no-claim scanner already refuses "compliant", "certified", affirmative "authorized", ATO claims, percentages and dates in certification sentences (`packages/core/neurosphere_core/compliance/claims.py:1-60`) and runs over the library in `packages/core/tests/compliance_lib/test_claims.py`.
- PRP-56 decision 5 forbids writing control ids or titles from memory: "Control ids and titles are fetched from the official sources". This PRP keeps that rule and adds licence limits.

## Acceptance criteria
- [ ] Given PRP-70 merged, When the library loads, Then `soc2_tsc`, `iso_27001_annex_a`, `gdpr` and `nist_800_53_r5` are frameworks (ids exactly as PRP-70 defines them), every control validates against the contract models, ids are unique across the whole library, and `LIBRARY_VERSION` is bumped so bundles show the new version.
- [ ] Every control row carries an identifier read from the named authoritative source on the retrieval date written in the file, a label of at most 100 characters written for this product (not the standard's wording), a `source_url`, and `framework_version`; a test fails on any row whose label exceeds the limit or on a file without a licence header comment.
- [ ] Licence handling: ISO/IEC 27001 and AICPA files store identifiers and NeuroSphere-authored short labels only; no sentence, clause, point of focus, attribute or note text of either standard is stored; the file header states where a licensed copy is bought or the criteria are published and that the labels are paraphrases; if an authoritative identifier list cannot be read in the session without circumventing a licence, the framework is left unwritten and reported OPEN.
- [ ] The `nist_800_53_r5` framework is generated from `docs/compliance/ssp/control-mapping.yaml` (same ids, titles, statuses and evidence paths, ids written as `nist-800-53.<id lowercase>`), and a drift test fails when the YAML and the SSP file disagree on an id, a title or a status.
- [ ] Support statuses use the PRP-23 six; `designed` and `implemented_tested` rows cite repository paths that exist and, where a test exists, that test; organisation-level controls are `customer`; physical and platform controls are `inherited` and point at `docs/compliance/responsibility-matrix.md` with the caveat that inherited controls do not authorize this application; no row says more than the repository supports.
- [ ] Every row's `evidence_sources` is a subset of the five existing sources and names only sources whose observation actually bears on the control; a control no source touches has an empty list, and its summary reads `customer_responsibility` or `no_evidence`, never a verdict.
- [ ] The no-claim scan passes over all four new files, the rendered Markdown bundle of each new framework, the runbook section and the frontend mock data; the disclaimer `not FedRAMP authorized; the authorizing official decides` appears in each Markdown bundle; a planted "NeuroSphere is SOC 2 compliant" in a test fixture is refused.
- [ ] The loader and the framework list tolerate the two further `FrameworkId` members PRP-70 adds (`eu_ai_act`, `iso_42001`) while no library file exists for them: no error, not listed, and a later file for either loads with no code change (a test with a temporary file); PRP-128 adds the two files.
- [ ] `GET /api/v1/compliance/frameworks` lists all eight frameworks; `/frameworks/{id}` and the bundle and export routes work for each new id with `evidence.read` on the domain; a golden bundle exists per new framework and the same inputs and clock produce identical bytes.
- [ ] `/compliance` shows the new frameworks in its picker with no component change; the mock API serves them; axe and the existing e2e specs still pass.
- PRP exit: an auditor picks SOC 2, ISO 27001, GDPR or NIST 800-53 in `/compliance`, sees the mapped controls with source links and which evidence exists, downloads a deterministic bundle, and finds no sentence claiming compliance, certification or authorization.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| 1 | All controls or a mapped subset | Full catalogues (SOC 2 about 60 criteria, Annex A 93 controls, 800-53 about 1000); subset NeuroSphere can speak to | Subset, as PRP-56 did (19 of the NIST AI RMF subcategories). 800-53 is exactly the 64 rows already in the SSP mapping. Each other file lists the controls the item can justify; the final counts are reported in the completion note, not fixed here |
| 2 | Where identifiers come from | Memory; official sources | Fetched in the item that writes the file. SOC 2: the AICPA Trust Services Criteria publication; ISO: the ISO catalogue and Online Browsing Platform preview of ISO/IEC 27001:2022 and its Annex A table of contents; GDPR: EUR-Lex (CELEX 32016R0679); 800-53: NIST CSRC and the NIST OSCAL catalog. The orchestrator fetches and pastes into the item brief because subagents have no Microsoft Learn or web tool guarantee; nothing is written from memory |
| 3 | Standard text | Quote; identifier plus own label | Identifier plus own label only (ISO text is copyrighted; AICPA criteria carry terms of use). GDPR and NIST are public but the same short-label rule keeps the files uniform |
| 4 | If an identifier list cannot be read | Write from memory; stop and report | Stop and report OPEN for that framework; ask the operator to supply a licensed copy path or exclude the framework. The other frameworks still ship |
| 5 | Crosswalks | Assume SOC 2 or ISO map to 800-53 one to one; author per row | Author per row from NeuroSphere facts; cite a published crosswalk only where one is fetched and its URL kept. No assumed one-to-one equivalence |
| 6 | Bumping the library version | Keep `1.0.0`; bump | Bump to `1.1.0` (the version is part of the bundle digest), regenerate the golden bundle for the existing framework, and say so in the completion note. ASSUMPTION |
| 7 | New evidence source for lifecycle or residency | Add now; later | Later. PRP-83 builds those features; mapping rows for them are `planned` with the PRP id until they ship, then PRP-83 flips them |
| 8 | Who may read | `evidence.read`; admin | Unchanged from PRP-56 (`evidence.read`; Admin does not hold it) |

## Context manifest

### Files to read first
- `packages/core/neurosphere_core/compliance/loader.py` - row validation, duplicate and path rules, `source_retrieved` checks.
- `packages/core/neurosphere_core/compliance/library/omb_m_25_21.yaml` - file header and row shape to imitate (including how sources are noted).
- `packages/core/neurosphere_core/compliance/models.py` - `LIBRARY_VERSION`, `PATH_REQUIRED_STATUSES`, `EVIDENCE_SOURCE_IDS`.
- `packages/core/neurosphere_core/compliance/claims.py` and `render.py` - what the scanner refuses and how bundles render.
- `docs/compliance/ssp/control-mapping.yaml` and `docs/compliance/responsibility-matrix.md` - the 800-53 rows and the inheritance caveat.
- `tests/compliance/test_control_mapping.py:89-220` - the PRP-23 claim detector and the vocabulary check.
- `packages/core/tests/compliance_lib/test_library.py`, `test_claims.py`, `test_bundle.py` and `golden/` - tests this PRP edits.
- `services/api/tests/compliance_api/test_compliance_api.py` - framework list assertions.
- `frontend/tests/mock-api/features/compliance.ts` - mock frameworks.
- `PRPs/shipped/PRP-56-compliance-control-library-and-evidence-bundles.md` - decisions 1, 3, 5 and the completion note.
- `docs/runbooks/compliance-evidence.md` - the runbook this PRP extends.

### Interfaces consumed
- PRP-70: `Control.framework_id` (`$defs/framework_id`, Python and TypeScript `FrameworkId`) extended with `soc2_tsc`, `iso_27001_annex_a`, `gdpr`, `nist_800_53_r5`; the four existing ids unchanged.
- PRP-56 (shipped): `Control`, `ControlMapping`, `ControlFramework` contracts; `load_library`; the five evidence sources `catalog_ownership`, `audit_chain`, `hitl_decisions`, `evaluation_results`, `cost_attribution`; bundle builder; routes `/api/v1/compliance/*`; `scan_for_claims`.
- PRP-23 (shipped): the 800-53 mapping file and the six-status vocabulary.

### Interfaces provided
- Library files `soc2_tsc.yaml`, `iso_27001_annex_a.yaml`, `gdpr.yaml`, `nist_800_53_r5.yaml` under `packages/core/neurosphere_core/compliance/library/`; control id prefixes `soc2.`, `iso27001.`, `gdpr.`, `nist-800-53.`.
- `LIBRARY_VERSION` `1.1.0`.
- A sync check script `scripts/compliance_library_sync.py` (new) with `--check` and `--write` for the 800-53 file; PRP-83 relies on the GDPR control ids `gdpr.art-5`, `gdpr.art-17`, `gdpr.art-25`, `gdpr.art-30`, `gdpr.art-32` and `gdpr.art-44` to `gdpr.art-49` where item 3 includes those articles (item 3 records any it leaves out, and PRP-83 then skips that row). PRP-83 edits only the `status` and evidence-path fields of those rows, never ids.
- Control ids are stable once shipped; later PRPs cite them.

### Patterns to match
- File header with source, retrieval date and no-claim note: `library/omb_m_25_21.yaml:1-9`.
- Loader failure tests with `tmp_path`: `compliance_lib/test_library.py:65-132`.
- Golden bundle test: `compliance_lib/test_bundle.py`, `golden/nist_ai_rmf.bundle.json`.
- Doc-versus-data drift check: `tests/compliance/test_control_mapping.py`.

### Gotchas
- Control ids must match `^[a-z0-9][a-z0-9._-]{0,95}$`: write `soc2.cc6.1`, `iso27001.a.8.15`, `gdpr.art-32`, `nist-800-53.ac-2`; keep the official identifier recoverable from the id.
- The bundle includes the library version and sorted controls; adding frameworks changes only new bundles, but the `LIBRARY_VERSION` bump changes the existing golden bundle: regenerate it deliberately.
- The claims scanner bans `%` and `compliant`/`certified`: several official titles contain words such as "compliance" (allowed) or "certified" (refused); use the own-label rule, never paste a title that trips the scanner.
- `source_retrieved` must not be in the future and the loader checks it per file; use the real fetch date.
- The 800-53 rows say `customer` or `inherited` for many controls; keep their statuses exactly (the drift test enforces it); do not upgrade a status to make a framework look better.
- Test directory `packages/core/tests/compliance_lib` already exists; add files to it, do not create a same-named directory elsewhere.
Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - packages/core/neurosphere_core/compliance/library/soc2_tsc.yaml
  - packages/core/neurosphere_core/compliance/library/iso_27001_annex_a.yaml
  - packages/core/neurosphere_core/compliance/library/gdpr.yaml
  - packages/core/neurosphere_core/compliance/library/nist_800_53_r5.yaml
  - packages/core/neurosphere_core/compliance/models.py
  - packages/core/neurosphere_core/compliance/loader.py
  - packages/core/tests/compliance_lib/**
  - scripts/compliance_library_sync.py
  - services/api/tests/compliance_api/**
  - frontend/tests/mock-api/features/compliance.ts
  - docs/runbooks/compliance-evidence.md
tier1: []
tier2_appends:
  - mkdocs.yml
must_not_touch:
  - packages/contracts/**
  - packages/core/neurosphere_core/compliance/sources/**
  - packages/core/neurosphere_core/compliance/bundle.py
  - packages/core/neurosphere_core/compliance/claims.py
  - packages/core/neurosphere_core/compliance/library/nist_ai_rmf.yaml
  - packages/core/neurosphere_core/compliance/library/sr_11_7.yaml
  - packages/core/neurosphere_core/compliance/library/hipaa_technical_safeguards.yaml
  - packages/core/neurosphere_core/compliance/library/omb_m_25_21.yaml
  - docs/compliance/**
  - services/api/neurosphere_api/**
  - frontend/src/**
```

## Implementation blueprint

Parallelization: item 1 first (sync script, version bump, test scaffolding). Items 2, 3 and 4 are [P] after item 1 (one new file each, plus one new test file each). Item 5 after 2 to 4. Item 6 last.

### Item 1 - Loader guards, version bump and the 800-53 file
- Deliverable: loader tolerance for `FrameworkId` members that have no library file; `LIBRARY_VERSION` `1.1.0`; a loader guard for a maximum label length of 100 characters and a required licence header comment in the four new files (test-side if the loader cannot see comments); `scripts/compliance_library_sync.py` generating `nist_800_53_r5.yaml` from `docs/compliance/ssp/control-mapping.yaml` (retrieval date and NIST source URL fetched and recorded; ids lowercased with the `nist-800-53.` prefix; `evidence_sources` set only by a reviewed table in the script, empty otherwise) with `--check` used by a drift test; the generated file; golden regeneration for `nist_ai_rmf`.
- Owned files: `compliance/{models,loader}.py`, `library/nist_800_53_r5.yaml`, `scripts/compliance_library_sync.py`, `packages/core/tests/compliance_lib/test_library_800_53.py`, `test_library_guards.py`, `golden/**`.
- Must NOT touch: the other library files, `claims.py`, `bundle.py`.
- Depends on: PRP-70 merged.
- Acceptance criteria: the 800-53 and drift criteria; titles verified against NIST (sample of at least 10 ids plus every id family) with the source URL recorded; the label and licence guards fail on a planted violation.
- Tests: `packages/core/tests/compliance_lib/test_library_800_53.py`, `test_library_guards.py`, existing `test_library.py` (framework set assertion updated in item 5).
- Pattern references: `compliance_lib/test_library.py:65-132`, `tests/compliance/test_control_mapping.py`.

### Item 2 - GDPR  [P]
- Deliverable: fetch the article list from EUR-Lex (record URL and date), choose the articles NeuroSphere can speak to (expected to include principles and records of processing, security of processing, data protection by design, breach notification, data-subject rights, and the transfer chapter; the item decides from the fetched list and the PRP-83 scope), and write `gdpr.yaml` with identifiers, own labels and mapping rows. Rows PRP-83 will satisfy are `planned` with `PRP-83` named in the header comment.
- Owned files: `library/gdpr.yaml`, `packages/core/tests/compliance_lib/test_library_gdpr.py`.
- Must NOT touch: other library files.
- Depends on: item 1.
- Acceptance criteria: identifiers match the fetched list exactly; statuses honest; no row asserts adequacy or compliance; the claim scan passes.
- Tests: `test_library_gdpr.py` (ids unique, shape, path existence, scan).
- Pattern references: `library/hipaa_technical_safeguards.yaml`.

### Item 3 - SOC 2 Trust Services Criteria  [P]
- Deliverable: obtain the criteria identifiers from the AICPA publication (record URL and date and the terms-of-use note), select the criteria the product can speak to (expected: logical access, monitoring, change management, risk mitigation and the availability and confidentiality categories), write `soc2_tsc.yaml` with identifiers and own short labels only, no points of focus or criteria text. If the identifier list cannot be read lawfully in the session, write nothing and report OPEN.
- Owned files: `library/soc2_tsc.yaml`, `packages/core/tests/compliance_lib/test_library_soc2.py`.
- Must NOT touch: other library files.
- Depends on: item 1.
- Acceptance criteria: licence criterion; identifiers match the fetched list; the header names the publisher and that labels are paraphrases; organisation-level criteria are `customer`.
- Tests: `test_library_soc2.py`.
- Pattern references: `library/sr_11_7.yaml`.

### Item 4 - ISO/IEC 27001 Annex A  [P]
- Deliverable: obtain Annex A identifiers from an authoritative source that can be read without circumventing the licence (ISO catalogue or Online Browsing Platform preview, or a licensed copy the operator names), select the controls the product can speak to (access control, logging and monitoring, secure development, supplier relationships, backup, cryptography, incident management; physical controls are `inherited`), write `iso_27001_annex_a.yaml` with identifiers and own short labels. The same stop-and-report rule applies.
- Owned files: `library/iso_27001_annex_a.yaml`, `packages/core/tests/compliance_lib/test_library_iso.py`.
- Must NOT touch: other library files.
- Depends on: item 1.
- Acceptance criteria: licence criterion; no verbatim ISO title (labels differ from the standard's wording and a test asserts none exceeds the limit); `inherited` rows cite the responsibility matrix.
- Tests: `test_library_iso.py`.
- Pattern references: `library/hipaa_technical_safeguards.yaml`.

### Item 5 - Bundles, API and mock coverage
- Deliverable: update the framework-set assertions (`test_library.py`, `test_compliance_api.py`), add a golden bundle per new framework and a Markdown rendering check with the disclaimer, extend the mock frameworks and bundles in `compliance.ts` (synthetic evidence), run the no-claim scan over bundles, mock data and the runbook; extend `docs/runbooks/compliance-evidence.md` with the four frameworks, the licence rule (identifiers and short labels only), how to add a control, and the statement that a mapping is not an assessment.
- Owned files: `packages/core/tests/compliance_lib/test_library.py`, `test_bundle.py`, `golden/**`, `services/api/tests/compliance_api/**`, `frontend/tests/mock-api/features/compliance.ts`, `docs/runbooks/compliance-evidence.md`.
- Must NOT touch: frontend source, API source, `bundle.py`.
- Depends on: items 1 to 4 (those written).
- Acceptance criteria: criteria for bundles, API, page and scan; the existing compliance e2e and a11y specs pass unchanged.
- Tests: `uv run pytest -q packages/core/tests/compliance_lib services/api/tests/compliance_api tests/compliance`; `pnpm --filter @neurosphere/frontend test`.
- Pattern references: `compliance_lib/test_bundle.py`, `frontend/tests/mock-api/features/compliance.ts:178`.

### Item 6 - Integration and close-out
- Deliverable: rebase, Tier-3 regeneration (`openapi.json` only if schemas moved, `docs/reference/**`, status table, `PRPs/INDEX.md`, `PRPs/EXECUTION-PLAN.md`), changelog fragment `changelog.d/PRP-81-compliance-mappings-soc2-iso27001-gdpr.md`, completion note with final control counts per framework, the retrieval dates and sources actually used, any framework left OPEN and why, and the product check.
- Owned files: this PRP file, the fragment, Tier-3 files.
- Depends on: items 1 to 5.
- Acceptance criteria: validation gates pass; CI green.

## Validation gates
```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q packages/core/tests/compliance_lib services/api/tests/compliance_api tests/compliance tests/security/authz services/api/tests/test_openapi_drift.py tests/docs/test_reference_coverage.py
python scripts/compliance_library_sync.py --check
pnpm --filter @neurosphere/frontend test
pnpm --filter @neurosphere/frontend typecheck
python packages/contracts/scripts/generate.py --check
python scripts/prp_status.py --check
python scripts/validate_planning.py
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```

## Migration and rollback
None for data: the library is package data and bundles are computed per request. The library version moves from `1.0.0` to `1.1.0`, so bundles generated before and after carry different versions and digests (expected). Rollback: revert the PR, or delete a framework file (the loader treats each file independently and the page is data-driven); the enum values added by PRP-70 stay and are inert.

## Live and open gates
No live call. Reading the AICPA, ISO, EUR-Lex and NIST sources is a read of public pages or previews during the session; if an authoritative identifier list is not readable lawfully, that framework is reported OPEN, not guessed. Whether a licensed copy of ISO/IEC 27001 or the AICPA criteria is available to the operator is an operator input. Nothing here claims or evidences a SOC 2 report, an ISO certificate, GDPR adequacy, FedRAMP authorization or an ATO; those are organisational decisions outside the baseline.

## NOT building
A SOC 2 or ISO audit workflow, readiness score, gap percentage or attestation store; copies of standard text; a crosswalk between frameworks; new evidence sources; a second no-claim scanner; a change to the compliance API or page code; GDPR lawful-basis assessments or any legal determination; FINRA.

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [ ] All clarification questions are decided, not guessed (row 6 is an ASSUMPTION for plan approval; the licensed-source question in row 4 depends on the operator)

## Execution state
| Item | Status | Branch/worktree | Notes |
|---|---|---|---|
| 1 | todo | | |
| 2 | todo | | |
| 3 | todo | | |
| 4 | todo | | |
| 5 | todo | | |
| 6 | todo | | |

## Completion note (filled at ship)
- Date, PR, merge commit:
- Deviations from the blueprint and why:
- Descoped items:
- OPEN gates:
- Env vars for the operator:
- Follow-up issue numbers:
- Product check (can an operator use it without editing files or calling raw APIs?):
