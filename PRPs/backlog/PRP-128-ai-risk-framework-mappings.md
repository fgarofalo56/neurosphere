---
name: PRP-128-ai-risk-framework-mappings
status: backlog
priority: P2
order: 128
review: required
created: 2026-11-16
model: sonnet
orchestrator_model: sonnet
implementer_model: sonnet
phase: 9
ns: NS-08
depends_on: [PRP-81-compliance-mappings-soc2-iso27001-gdpr, PRP-70-contracts-revision-restored-scope]
wave: W30
branch: prp-128-ai-risk-mappings
allow_parallel: true
issues: []
---

# PRP-128: AI risk framework mappings (EU AI Act, ISO/IEC 42001, extended NIST AI RMF)

## Goal
Add two AI-governance frameworks to the control library as data, extend the existing NIST AI RMF file, and ship a small tier-to-controls table so the risk register (PRP-127) can show "controls a customer may review" for the tier the customer recorded. Each framework lists the controls NeuroSphere can say something about, with an identifier read from the authoritative source on the day of execution, a short label written for this product, a source link and retrieval date, a support status and evidence sources from the five that PRP-56 built. The existing bundle builder, API and `/compliance` page then show them with no code change. It follows the pattern of PRP-81 and runs after it in W30.

This is a mapping and an evidence aid, never a verdict: no file, label, API field or page string says that NeuroSphere or a customer meets, complies with, is certified against or is authorized under any of these frameworks, and nothing classifies a system's legal risk (design section 8, item 10; owner decision GD-15). Identifiers and short own-words labels are stored; the text of the standards is not. ISO text is licensed.

Out of scope: the register, questionnaire and assessments (PRP-127); a determination or legal classification of any kind; new evidence sources for the register or attestations (the source list is a closed enum in `compliance/v1/control-mapping.schema.json:47`, a contract change with no W30 owner; see NOT building); the CI gate (PRP-129); SOC 2, ISO 27001, GDPR and 800-53 (PRP-81); certification or attestation workflows (organisational, `docs/PRD.md:57`).

## Why
- The owner asked on 2026-11-16 for "the ultimate team AI governance and auditing tool"; the design finds "EU AI Act" and "42001" have no hits in the tree (G-f), and the library has four frameworks only (`packages/core/neurosphere_core/compliance/library/`: `hipaa_technical_safeguards`, `nist_ai_rmf`, `omb_m_25_21`, `sr_11_7`).
- `FrameworkId` is a closed four-value enum (`packages/contracts/python/neurosphere_contracts/compliance/v1/control.py:18-21`). PRP-70 backlog text adds `soc2_tsc`, `iso_27001_annex_a`, `gdpr`, `nist_800_53_r5` but the design fold F2 (`eu_ai_act`, `iso_42001`) is not in PRP-70 yet (`PRPs/backlog/PRP-70-contracts-revision-restored-scope.md:44,110`); item 1 verifies and, if needed, adds them.
- The loader reads every `*.yaml` in the library directory and rejects a repeated framework id (`compliance/loader.py:120-158`), so a new framework is one new file and "extended NIST AI RMF" can only mean editing `library/nist_ai_rmf.yaml` (19 controls today, category level).
- PRP-56 decision 5 and PRP-81 clarification 2 forbid control identifiers written from memory; the library's claim scanner (`compliance/claims.py:1-60`) refuses "compliant", "certified", percentages and affirmative authorization.
- The tier a customer records (PRP-110 `RiskTierDetermination.tier`, open-ended) has nowhere to point at library controls; without a table the register page could only show a tier, or invent obligations.

## Acceptance criteria
- [ ] Given PRP-70 merged, When the library loads, Then `eu_ai_act` and `iso_42001` are frameworks (ids exactly as in `FrameworkId`), every row validates against the contract models, control ids are unique across the whole library, and a framework whose identifiers could not be read lawfully is absent and reported OPEN (never written from memory).
- [ ] Every row carries an identifier read from the named official source on the `source_retrieved` date written in the file, a label of at most 100 characters in the product's own words, a `source_url` and a `framework_version`; ISO files hold identifiers and own labels only, no clause, note or attribute text, and the header says where a licensed copy is needed for anything more.
- [ ] `nist_ai_rmf.yaml` gains rows for the subcategories NeuroSphere touches, read from the official NIST publication on the retrieval date; the existing 19 control ids and statuses are unchanged; added rows follow the same id style (`nist-ai-rmf.<id>`).
- [ ] Support statuses use the six PRP-23 words; `designed` and `implemented_tested` rows cite repository paths that exist at execution and the test that proves them; rows that depend on PRP-127, PRP-129 or PRP-130 are `planned` unless those are already merged; organisation-level controls are `customer`.
- [ ] Every row's `evidence_sources` is a subset of the five existing sources and names only a source whose observation bears on the control; nothing here adds a source.
- [ ] The tier table `tier_obligations.yaml` maps a tier token to a list of library control ids; every id exists in the loaded library, labels are own words, the header says "controls a customer may review for a system it has recorded at this tier; not an obligation or a determination", and rows exist only for tier tokens that appear in the fetched source for that framework (a token the source does not name is reported, not written).
- [ ] The no-claim scan passes over all new and edited files, the rendered Markdown bundle of each new framework, the tier table and the runbook section; the PRP-23 disclaimer appears in each bundle.
- [ ] `GET /api/v1/compliance/frameworks` lists every framework; `/frameworks/{id}`, bundle and export work for each new id with `evidence.read`; a golden bundle exists per new framework, and the other goldens are regenerated deliberately because `LIBRARY_VERSION` is bumped.
- PRP exit: touched suites, ruff, pyright, `validate_planning.py` pass; PR open, CI green; completion note lists identifier counts per framework and every OPEN framework.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| 1 | Where identifiers come from | Memory; official sources | Fetched at execution, never from memory: the official EU AI Act text published by the EU (EUR-Lex), the ISO catalogue and Online Browsing Platform preview for ISO/IEC 42001, and NIST's AI RMF Core and its Generative AI profile on airc.nist.gov. The orchestrator fetches and pastes into the item brief because subagents have no web tool guarantee (PRP-81 rule). The current edition or consolidated version is confirmed then, not named here |
| 2 | Standard text | Quote; identifier plus own label | Identifier plus own label only; ISO text is licensed, EU and NIST public text still follows the same uniform rule |
| 3 | If a list cannot be read lawfully | Write from memory; stop and report | That framework is reported OPEN and not written (design U-18); expect ISO to give clause and Annex identifiers from the preview only, or OPEN. The others still ship |
| 4 | "Extended NIST AI RMF" | Second file; edit existing | Edit `nist_ai_rmf.yaml` (a second file with the same framework id fails the loader). Subcategory rows only for areas the register, gate, attestation and approval features touch; the count is reported, not fixed here. ASSUMPTION |
| 5 | Tier-to-controls table location | In the library directory; own directory | Own directory `packages/core/neurosphere_core/compliance/tier_map/`, because the library loader reads every YAML in `library/` and would reject a differently shaped file. ASSUMPTION |
| 6 | Library version | Keep; bump | Bump `LIBRARY_VERSION` to `1.2.0` (PRP-81 sets `1.1.0`); regenerate every golden bundle and say so. ASSUMPTION |
| 7 | New evidence sources for the register and attestations | Add now; later | Later: the enum is closed in the contract and no contracts owner exists in W30. Register and attestation features are cited through `repo_paths` and the existing `audit_chain` and `catalog_ownership` sources |
| 8 | Who may read | `evidence.read`; admin | Unchanged from PRP-56 (`evidence.read`; admin does not hold it) |

## Context manifest

### Files to read first
- `PRPs/backlog/PRP-81-compliance-mappings-soc2-iso27001-gdpr.md` - the pattern this PRP repeats (clarifications 2 to 5, gotchas on ids, `source_retrieved`, scanner words).
- `packages/core/neurosphere_core/compliance/loader.py` (`load_library`, `_load_file`), `models.py` (`LIBRARY_VERSION`, `EVIDENCE_SOURCE_IDS`, `PATH_REQUIRED_STATUSES`).
- `packages/core/neurosphere_core/compliance/library/nist_ai_rmf.yaml` - header and row shape; the file this PRP extends.
- `packages/core/neurosphere_core/compliance/claims.py`, `render.py` - scanner rules and Markdown disclaimer.
- `packages/contracts/schemas/compliance/v1/control.schema.json`, `control-mapping.schema.json` - `framework_id` and the closed evidence-source list.
- `packages/core/tests/compliance_lib/` (`test_library.py`, `test_claims.py`, `test_bundle.py`, `golden/`) - tests this PRP edits.
- `PRPs/backlog/PRP-127-ai-system-register-tiering-and-impact-assessments.md`, `PRP-110-governance-contracts-b.md` - tier tokens and `RiskTierDetermination`.
- `docs/runbooks/compliance-evidence.md`, `frontend/tests/mock-api/features/compliance.ts`.

### Interfaces consumed
- PRP-70 / design fold F2: `Control.framework_id` accepts `eu_ai_act` and `iso_42001` (UNVERIFIED: PRP-70's current text lists other values; item 1 checks).
- PRP-81: library loading of the SOC 2, ISO 27001, GDPR and 800-53 files, `LIBRARY_VERSION` `1.1.0`, and `scripts/compliance_library_sync.py`; this PRP must not break the 800-53 drift test.
- PRP-56 (shipped): `Control`, `ControlMapping`, `ControlFramework`, five evidence sources, bundle builder, routes `/api/v1/compliance/*`, `scan_for_claims`.
- PRP-110: documented `tier` tokens (`prohibited`, `high`, `limited`, `minimal`, `not_determined`; open-ended) used only to key the tier table after verification against the fetched source.

### Interfaces provided
- Library files `eu_ai_act.yaml` and `iso_42001.yaml` under `packages/core/neurosphere_core/compliance/library/`; control id prefixes `eu-ai-act.` and `iso42001.`; rows added to `nist_ai_rmf.yaml` under `nist-ai-rmf.`.
- `LIBRARY_VERSION` `1.2.0`.
- Core `neurosphere_core.compliance.tier_map`: `load_tier_map(library)` and `controls_for(framework_id, tier) -> tuple[str, ...]`; data `tier_map/tier_obligations.yaml`.
- Optional read route `GET /api/v1/risk/domains/{domain}/systems/{system_id}/related-controls` (item 6, `[serial-after: PRP-127]`), returning control ids and labels for the tier the customer recorded, with `risk.read`.
- Control ids are stable once shipped; later PRPs cite them.

### Patterns to match
- File header with source, retrieval date and no-claim note: `library/omb_m_25_21.yaml:1-9` and `library/nist_ai_rmf.yaml:1-9`.
- Loader failure tests with `tmp_path`: `packages/core/tests/compliance_lib/test_library.py:65-132`.
- Golden bundle test: `packages/core/tests/compliance_lib/test_bundle.py` and `golden/`.
- Doc-versus-data drift check: `tests/compliance/test_control_mapping.py`.

### Gotchas
- Control ids match `^[a-z0-9][a-z0-9._-]{0,95}$`; keep the official identifier recoverable from the id (for example an article or clause number after the prefix).
- Official titles can contain words the scanner refuses (`certified`, percentages); use the own-label rule and never paste a title.
- `source_retrieved` must not be in the future; use the real fetch date. Bumping `LIBRARY_VERSION` changes every golden bundle digest: regenerate deliberately and list it.
- Do not write a tier token the fetched source does not use. If the contract's tier values (written before this fetch) differ from the source's class names, report it for PRP-110 and key the table by the contract values only where the source supports them.
- The PRP-81 loader change for the two new framework ids with no file yet must already be in place; if not, item 1 adds it in `loader.py` (owned here after PRP-81 merged).
- Tests live in the existing `packages/core/tests/compliance_lib`; do not create a same-named directory elsewhere.
- Subagents have no guaranteed web tool: the orchestrator fetches and pastes the identifier lists into briefs; nothing is recalled.
Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - packages/core/neurosphere_core/compliance/library/eu_ai_act.yaml
  - packages/core/neurosphere_core/compliance/library/iso_42001.yaml
  - packages/core/neurosphere_core/compliance/library/nist_ai_rmf.yaml
  - packages/core/neurosphere_core/compliance/tier_map/**
  - packages/core/neurosphere_core/compliance/models.py
  - packages/core/neurosphere_core/compliance/loader.py
  - packages/core/tests/compliance_lib/**
  - frontend/tests/mock-api/features/compliance.ts
  - docs/runbooks/compliance-evidence.md
  - services/api/tests/compliance_api/**
tier1: []
tier2_appends:
  - mkdocs.yml
must_not_touch:
  - packages/contracts/**
  - packages/core/neurosphere_core/compliance/sources/**
  - packages/core/neurosphere_core/compliance/bundle.py
  - packages/core/neurosphere_core/compliance/claims.py
  - packages/core/neurosphere_core/compliance/library/soc2_tsc.yaml
  - packages/core/neurosphere_core/compliance/library/iso_27001_annex_a.yaml
  - packages/core/neurosphere_core/compliance/library/gdpr.yaml
  - packages/core/neurosphere_core/compliance/library/nist_800_53_r5.yaml
  - docs/compliance/**
  - services/api/neurosphere_api/compliance/**
  - frontend/src/**
```
Item 1 may edit `packages/contracts/schemas/compliance/v1/control.schema.json` and generated output, only if `eu_ai_act` and `iso_42001` are absent, and only after confirming no PRP-127 cut-line contract item is in flight. Item 6 adds files under `services/api/neurosphere_api/risk/` after PRP-127 merged.

## Implementation blueprint

Parallelization: item 1 first; items 2 and 3 [P] (different files, separate fetches); item 4 after 2 (needs ids); 5 after 2-4; 6 after 5 and PRP-127; 7 last.

### Item 1 - Contract check and source availability
- Deliverable: confirm `FrameworkId` contains `eu_ai_act` and `iso_42001` and the loader accepts a framework with no sibling file; if absent, add the two values (additive, documented open-ended) and regenerate. Then the orchestrator fetches, per framework, the official source and records URL, edition, retrieval date and whether identifiers are readable without a licence; unreadable means that framework is OPEN.
- Owned files: the schema file above (conditional), `compliance/loader.py` (conditional), `temp/` notes only (not committed).
- Depends on: PRP-81 and PRP-70 merged.
- Acceptance criteria: criterion 1 (first half); the OPEN list is written down before any file is authored.
- Tests: `python packages/contracts/scripts/generate.py --check`, `packages/core/tests/compliance_lib/test_library.py`.
- Pattern references: PRP-81 item 1.

### Item 2 - EU AI Act and ISO/IEC 42001 files  [P]
- Deliverable: `eu_ai_act.yaml` and `iso_42001.yaml` with a header (source, retrieval date, no-claim and licence note), rows with prefix ids, own labels, statuses per criterion 4 and evidence sources per criterion 5; whichever framework is OPEN is not written.
- Owned files: the two library files, `packages/core/tests/compliance_lib/test_ai_frameworks.py` (new; row counts, id style, label length, paths exist, no ISO text patterns).
- Depends on: item 1.
- Acceptance criteria: criteria 1, 2, 4, 5.
- Tests: `packages/core/tests/compliance_lib`.
- Pattern references: `library/omb_m_25_21.yaml`, `compliance_lib/test_library.py:65-132`.

### Item 3 - Extended NIST AI RMF rows  [P]
- Deliverable: subcategory rows appended to `nist_ai_rmf.yaml` read from the official NIST publication on the retrieval date; the original 19 rows byte-identical; `source_retrieved` updated.
- Owned files: `library/nist_ai_rmf.yaml`, `packages/core/tests/compliance_lib/test_nist_extension.py` (new; the original ids and statuses are pinned).
- Depends on: item 1.
- Acceptance criteria: criterion 3.
- Tests: `packages/core/tests/compliance_lib`.
- Pattern references: `library/nist_ai_rmf.yaml:10-40`.

### Item 4 - Tier-to-controls table
- Deliverable: `tier_map/` loader (`load_tier_map`, `controls_for`), `tier_obligations.yaml`, validation against the loaded library, scanner coverage of every note.
- Owned files: `packages/core/neurosphere_core/compliance/tier_map/**`, `packages/core/tests/compliance_lib/test_tier_map.py` (new).
- Depends on: item 2.
- Acceptance criteria: criterion 6; an unknown control id or unknown framework id fails the load; the wording never says a tier "requires" a control.
- Tests: `packages/core/tests/compliance_lib`.
- Pattern references: `compliance/loader.py:120-158`.

### Item 5 - Version bump, goldens and surfaces
- Deliverable: `LIBRARY_VERSION` `1.2.0`; regenerated goldens (new frameworks plus all existing ones); mock API frameworks; API tests listing every framework; runbook section; scanner over rendered bundles.
- Owned files: `compliance/models.py`, `compliance_lib/golden/**`, `services/api/tests/compliance_api/**`, `frontend/tests/mock-api/features/compliance.ts`, `docs/runbooks/compliance-evidence.md`.
- Depends on: items 2-4.
- Acceptance criteria: criteria 7, 8.
- Tests: `packages/core/tests/compliance_lib`, `services/api/tests/compliance_api`, `pnpm --filter @neurosphere/frontend test`.
- Pattern references: PRP-81 item 5.

### Item 6 - Related-controls read for the register  [serial-after: PRP-127]
- Deliverable: one read route for the register page that returns the library controls for the tier the customer recorded, with the table header sentence attached; `risk.read` on the domain; allowed-read audit; "no tier recorded" returns an empty list with that reason.
- Owned files: `services/api/neurosphere_api/risk/related_controls.py` (new, one line in PRP-127's router include), `services/api/tests/risk_api/test_related_controls.py` (new).
- Must NOT touch: other files in `risk/**`.
- Depends on: PRP-127 merged, item 4.
- Acceptance criteria: given a recorded tier, the response lists ids and labels and never the words "required" or "applies"; a foreign system id is 404.
- Tests: `services/api/tests/risk_api`, `tests/security/authz`.
- Pattern references: `services/api/neurosphere_api/compliance/router.py`.

### Item 7 - Integration and close-out
- Deliverable: Tier-3 regeneration (`openapi.json`, `docs/reference/**`, status table, `PRPs/INDEX.md`), changelog fragment `changelog.d/PRP-128-ai-risk-framework-mappings.md`, completion note with counts per framework and every OPEN framework.
- Owned files: this PRP file, Tier-3 files per reference section 2.
- Depends on: items 1-6.
- Acceptance criteria: gates pass; CI green.

## Cut line
If PRP-127 is not merged or item 6 overruns, items 1-5 and 7 still merge: the library, extension and table ship and the register page simply lacks the related-controls panel. Record criterion for item 6 as unmet.

## Validation gates
```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
python packages/contracts/scripts/generate.py --check
uv run pytest -q packages/core/tests/compliance_lib services/api/tests/compliance_api services/api/tests/risk_api tests/compliance tests/contracts services/api/tests/test_openapi_drift.py tests/docs/test_reference_coverage.py
pnpm --filter @neurosphere/frontend test
python scripts/prp_status.py --check
python scripts/validate_planning.py
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```

## Migration and rollback
Data only: new YAML, new rows and a library version bump; no store change. Bundles generated before carry the old version in their digest and stay valid as records. Roll back by reverting the PR; removing a file removes the framework from the API list. Control ids shipped are stable, so a revert after customers cite them breaks only their own links.

## Live and open gates
None run: fetching official documents is read-only and happens in the session. Any framework whose identifier list cannot be read lawfully is recorded OPEN in the completion note with the reason, and an operator-supplied licensed copy path is the only unblock. A reviewer (the customer's counsel or compliance lead) should check own-words labels; that is a human gate, not automated.

## NOT building
Any claim, score, percentage or determination that a system, NeuroSphere or a customer meets, complies with or is certified against the EU AI Act, ISO/IEC 42001 or NIST AI RMF; legal classification of any system (the tier is the customer's record, PRP-127); standard text beyond identifiers and own labels; certification, audit or attestation workflows; new evidence sources (a contract change with no owner in W30: a follow-up for a contracts wave); a tier-to-obligation engine that tells a customer what applies to it; automatic cross-framework crosswalks.

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [ ] All clarification questions are decided, not guessed (rows 4, 5 and 6 are ASSUMPTIONS for plan approval; identifier availability is UNVERIFIED until item 1)

## Execution state
| Item | Status | Branch/worktree | Notes |
|---|---|---|---|
| 1 | todo | | |
| 2 | todo | | |
| 3 | todo | | |
| 4 | todo | | |
| 5 | todo | | |
| 6 | todo | | serial-after PRP-127 |
| 7 | todo | | |

## Completion note (filled at ship)
- Date and PR:
- Identifier counts per framework and OPEN frameworks (with reason):
- Deviations:
- Descoped items:
- OPEN gates:
- Env vars for the operator: none expected.
- Follow-up issues:
- Product check (can an operator use it without editing files): an auditor picks EU AI Act or ISO/IEC 42001 in `/compliance` and sees mapped controls and evidence.
