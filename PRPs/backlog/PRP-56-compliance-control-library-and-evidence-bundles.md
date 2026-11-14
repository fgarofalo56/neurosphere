---
name: PRP-56-compliance-control-library-and-evidence-bundles
status: backlog
priority: P2
order: 42
review: required
created: 2026-11-14
model: sonnet
orchestrator_model: sonnet
implementer_model: sonnet
phase: 6
ns: NS-08, NS-10
depends_on: []
wave: W17
branch: prp-56-compliance-evidence
allow_parallel: true
issues: []
---

# PRP-56: Compliance control library and evidence bundles

## Goal
Add a metadata-only compliance mapping to the product: a versioned control library for NIST AI RMF, SR 11-7, HIPAA (technical safeguards) and OMB M-25-21 held as data, a mapping from what NeuroSphere can observe about a customer's AI estate (catalog ownership and recertification, audit-chain integrity, HITL decisions, evaluation results, cost attribution) to those controls, an exportable evidence bundle per domain and framework, a read API and one page. It answers the owner's 2026-11-06 decision ("keep metadata-only and add compliance mapping", `docs/validation/PRODUCT-VALIDATION-2026-11-06.md:67-72`) for the auditor who must show a framework owner what evidence exists. It maps and collects; it never judges. No document, API field, page string or bundle says "compliant", "authorized", "certified", "FedRAMP" or "ATO" about NeuroSphere or the customer, and the PRP-23 neutral vocabulary (`designed / implemented_tested / inherited / customer / planned / not_applicable`) is reused. FINRA is optional and not built.

Out of scope: NeuroSphere's own 800-53 ATO documents, SSP narratives and POA&M (PRP-23 owns `docs/compliance/**` and `scripts/compliance/**`); prompt or response capture (excluded by design, PRP-33); configuration detections and shadow-AI discovery (PRP-61, which reuses the control ids); the AWS Bedrock connector (PRP-62); sign-off workflow, attestation storage and scheduled bundles; new evidence collection in other services (sources read existing stores read-only).

## Why
- The validation found "no compliance-framework mapping (NIST AI RMF, SR 11-7, FINRA, HIPAA, OMB M-25-21)" and chose metadata only (`docs/validation/PRODUCT-VALIDATION-2026-11-06.md:67-72`); a grep of packages, services, frontend, connectors, scripts, infra, tests and docs finds those names only in that document (lane-d step 7).
- PRP-23 maps NeuroSphere itself to 800-53, not the customer's AI estate: its mapping file `docs/compliance/ssp/control-mapping.yaml` has the status vocabulary and a no-claim rule enforced by `scripts/compliance/check_statements.py` and `tests/compliance/test_control_mapping.py`, but no in-product library, bundle or API (lane-d step 7 boundary paragraph).
- The evidence already exists as metadata: owner recertification (`services/api/neurosphere_api/catalog/router.py`, `GET /recertifications`), the per-domain audit hash chain (`packages/core/neurosphere_core/audit/chain.py:125`, `verify_chain`), HITL decisions (`packages/core/neurosphere_core/hitl/decisions.py`), evaluation results (`packages/core/neurosphere_core/evaluation/store.py:110`), and the ledger (`packages/core/neurosphere_core/ledger/store.py:34`).
- The `evidence.read` permission is held by the Security Auditor and has an existing consumer (`services/api/neurosphere_api/catalog/curation/router.py:61`), so a read-only evidence API fits the existing role matrix (`packages/core/neurosphere_core/auth/scope/permissions.py:100`).
- Contracts are JSON Schema under `packages/contracts/schemas/<area>/v1/` with generated bindings (`packages/contracts/scripts/generate.py`), the place a new `compliance` family belongs.

## Acceptance criteria
- [ ] Contracts: `packages/contracts/schemas/compliance/v1/` defines `ControlFramework`, `Control`, `ControlMapping`, `EvidenceObservation` and `EvidenceBundle` with examples; generated Python and TS bindings pass `python packages/contracts/scripts/generate.py --check`; unknown numeric values are `null`, never 0.
- [ ] Library: four frameworks ship as YAML under `packages/core/neurosphere_core/compliance/library/`; every control carries `control_id`, a short paraphrased title, `source_url`, `source_retrieved` (date) and `framework_version`; a loader rejects duplicates, unknown statuses and a mapping that names an unknown control or evidence source; a test fails when `designed`/`implemented_tested` support cites a repo path that does not exist.
- [ ] Vocabulary: support statuses are exactly the PRP-23 six; observation statuses are `observed | partial | unavailable | not_collected`; per-control summaries are `evidence_present | evidence_partial | no_evidence | customer_responsibility`. There is no pass, fail, score or percentage anywhere.
- [ ] No-claim scan: a test scans the library, the Markdown runbook, every rendered bundle and the frontend strings and fails on affirmative claims (a planted "NeuroSphere is HIPAA compliant" fails; "does not determine compliance" passes), modelled on `tests/compliance/test_control_mapping.py:89-220`; the disclaimer fragment `not FedRAMP authorized; the authorizing official decides` appears in the Markdown bundle and the runbook.
- [ ] Sources: five read-only `EvidenceSource` adapters (catalog ownership, audit-chain integrity, HITL decisions, evaluation results, cost attribution) return counts, timestamps and ids only (no entity bodies, no prompts, no principal names); a missing store yields `unavailable` with a reason code, a source that cannot count yields `not_collected`, never 0.
- [ ] Bundle: given a domain and framework, the builder returns an `EvidenceBundle` with per-control support, observations and summary, a collection window, a library version and a sha256 over the canonical JSON; the same inputs and clock give identical bytes (golden test); the Markdown rendering lists the same facts.
- [ ] API: `GET /api/v1/compliance/frameworks`, `/frameworks/{framework_id}`, `/domains/{domain}/bundle?framework_id=` and `/domains/{domain}/bundle/export?framework_id=&format=json|md` require `evidence.read` on the named domain (403 and a denial record otherwise, 503 when a dependency is down), derive the customer only from the server scope, and record an allowed-read audit entry (PRP-48 `audited_read`) naming domain, framework and digest.
- [ ] Page: `/compliance` lists frameworks, picks a readable domain, shows the control table with support status and evidence summary, and downloads the bundle; `/compliance/control` shows one control, its source link and observations; loading, empty, error and forbidden states exist; strings pass the no-claim scan; axe has zero serious or critical violations in light, dark and high-contrast; Docker-only visual baselines exist.
- [ ] Route inventories, manifest, nav, route samples and mock handlers are updated (Tier 2 lines only); `services/api/openapi.json` and `docs/reference/**` are regenerated at close-out.
- PRP exit: an auditor can pick a domain and a framework, see which controls have catalog, audit, HITL, evaluation and cost evidence and which are the customer's responsibility, and download a deterministic bundle, with no sentence that says the estate is compliant.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| 1 | Frameworks | Four named; add FINRA | NIST AI RMF, SR 11-7, HIPAA technical safeguards (45 CFR 164.312 and the 164.308 activity-review requirement), OMB M-25-21; FINRA optional and not built (validation doc) |
| 2 | Status vocabulary | New; reuse PRP-23 | Reuse PRP-23's six for NeuroSphere support; separate observation and summary words that carry no verdict |
| 3 | Where the library lives | Contracts data; core package data | Core package data (`neurosphere_core/compliance/library/*.yaml`), validated by the contract models; precedent `neurosphere_core/capabilities/data/*.yaml` |
| 4 | Who may read | `evidence.read`; `audit.read`; admin | `evidence.read` on the domain (Auditor today). Admin does not hold it and does not get the page (matches the role matrix); changing that is a PRP-37-style permission decision, not made here. ASSUMPTION |
| 5 | Control text | Quote; paraphrase | Short paraphrased titles plus a source link; no copied text. Control ids and titles are fetched from the official sources during item 2 (NIST AI 100-1, Federal Reserve SR 11-7, eCFR 45 CFR 164, OMB M-25-21); this PRP did not verify them and the library must not be written from memory |
| 6 | Persisting bundles | Store; stateless | Stateless, computed per request, digest returned; attestation and history are a later PRP |
| 7 | Cost attribution evidence | Wait for PRP-46; read the tag if present | Count ledger entries with and without a cost-center tag in the window; when PRP-37's `CostRecord.tags` is absent from the data the source reports `not_collected` |
| 8 | Evidence sources needing PRP-48 audited reads | Own audit write; PRP-48 dependency | Use PRP-48's `audited_read` dependency (`authz/read_audit.py`); item 5 checks it exists and, if not merged, uses the existing `AuditRepository` append and reports the deviation |

## Context manifest

### Files to read first
- `docs/validation/PRODUCT-VALIDATION-2026-11-06.md:67-72` and `temp/audit/lane-d-replan-gaps.md` step 7 and unit K1 - the decision and boundary.
- `docs/compliance/ssp/control-mapping.yaml:1-40`, `scripts/compliance/check_statements.py:1-60`, `tests/compliance/test_control_mapping.py:80-230` - vocabulary, claim rules and the planted-claim test to imitate (read only; PRP-23 owns them).
- `packages/contracts/scripts/generate.py` and `packages/contracts/schemas/audit/v1/audit-record.schema.json` - how a family and its examples are generated and drift-checked; `tests/contracts/test_drift.py`.
- `packages/core/neurosphere_core/capabilities/loader.py:21-125` - YAML package data loader and error style.
- `services/api/neurosphere_api/finops/{router.py,dependencies.py}` - a read route family with domain-path authorization and `app.state` store providers that fail closed.
- `services/api/neurosphere_api/catalog/curation/router.py:55-65` - the `evidence.read` dependency.
- `packages/core/neurosphere_core/audit/{chain.py,repository.py}`, `hitl/decisions.py`, `evaluation/store.py`, `ledger/store.py`, `catalog/protocol.py` - the stores the sources read; confirm which bounded read methods exist before writing each source.
- `frontend/src/features/finops/{routes.tsx,ForecastPage.tsx,data.ts}` and `frontend/tests/mock-api/features/finops.ts` - a page, hooks and mock for a domain-scoped read.
- `PRPs/backlog/PRP-23-ato-evidence-and-data-lifecycle.md` - vocabulary and the claim rules this PRP must stay consistent with.

### Interfaces consumed
- PRP-23 (docs only): the six-word status vocabulary and the no-claim rule; no code import from `scripts/`.
- PRP-37: `Permission.EVIDENCE_READ` exists today (`permissions.py:77`); `CostRecord.tags`; generated TS types pipeline.
- PRP-48: `audited_read(permission)` in `services/api/neurosphere_api/authz/read_audit.py` for allowed-read audit; `is_reserved_chain_name` not needed.
- PRP-46 (optional): cost-center tag populated on `CostRecord`; absent data yields `not_collected`.
- Existing providers: `app.state.catalog_repository`, `app.state.audit_repository`, `app.state.ledger_store`, `app.state.evaluation_store` (set in `runtime/builders/data.py:219,245,304,349`); the HITL service (`data.py:353`).
- Frontend: `PageTemplate`, `Panel`, `StatusPill`, domain list via `/me/domains`.

### Interfaces provided
- Contracts `neurosphere_contracts.compliance.v1` (`ControlFramework`, `Control`, `ControlMapping`, `EvidenceObservation`, `EvidenceBundle`) and TS twins.
- Core `neurosphere_core.compliance`: `load_library()`, `EvidenceSource` protocol, `build_bundle(...)`, `render_markdown(bundle)`, `scan_for_claims(text)`; control ids are stable and PRP-61 cites them in findings.
- API prefix `/api/v1/compliance` with the four routes above; mounted via a `_register_compliance` hook in `routers.py`.
- Frontend routes `/compliance`, `/compliance/control`; mock module `frontend/tests/mock-api/features/compliance.ts`.
- Runbook `docs/runbooks/compliance-evidence.md` (new): how to read a bundle and what it does not say.

### Patterns to match
- `services/api/neurosphere_api/finops/router.py:36-80` (path-domain `require`, no `customer_id` from the request) and `finops/dependencies.py:19-30` (fail-closed provider).
- `packages/core/neurosphere_core/capabilities/loader.py:99-125` (load, validate, typed error).
- `tests/compliance/test_control_mapping.py:89-220` (find_claims plus planted-claim parametrized test).
- `frontend/src/features/finops/routes.tsx` and `frontend/tests/mock-api/features/audit.ts` for the page and mock.

### Gotchas
- Using a contract model as `response_model` renames `openapi.json` components; regenerate at merge only and keep tests off `next(iter(set))`.
- New route family: update the Tier-2 inventories (`services/api/tests/authz/test_route_inventory.py`, `test_startup_route_check.py`, `services/api/tests/runtime_routes/manifest_calls.py`, `tests/integration/real_stack/test_manifest_routes.py`); no new builder is needed because stores are read from `app.state`, so the readiness component set is unchanged.
- Never read a store with an unbounded scan: every source takes a window and a cap and reports `truncated`.
- Do not name a framework "supported" or "covered" in strings; use "mapped controls" and "evidence observed".
- CSV or Markdown output must escape cell content; the bundle holds ids and counts only.
- Same-named test dirs shadow each other: use the unique directory names below and run the suites together.

Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - packages/contracts/schemas/compliance/**
  - packages/core/neurosphere_core/compliance/**
  - packages/core/tests/compliance_lib/**
  - tests/contracts/test_compliance_schemas.py
  - services/api/neurosphere_api/compliance/**
  - services/api/tests/compliance_api/**
  - frontend/src/features/compliance/**
  - frontend/tests/mock-api/features/compliance.ts
  - frontend/tests/e2e/compliance/**
  - docs/runbooks/compliance-evidence.md
tier1:
  - packages/contracts/**
tier2_appends:
  - services/api/neurosphere_api/routers.py
  - services/api/tests/authz/test_route_inventory.py
  - services/api/tests/authz/test_startup_route_check.py
  - services/api/tests/runtime_routes/manifest_calls.py
  - tests/integration/real_stack/test_manifest_routes.py
  - frontend/src/app/appRoutes.ts
  - frontend/src/app/route-manifest.json
  - frontend/src/app/workspaceNav.ts
  - frontend/tests/mock-api/features/index.ts
  - frontend/tests/e2e/a11y/route-samples.ts
  - frontend/tests/real-stack/routes.spec.ts
  - frontend/tests/e2e/visual/visual.spec.ts
  - mkdocs.yml
must_not_touch:
  - docs/compliance/**
  - scripts/compliance/**
  - tests/compliance/**
  - packages/core/neurosphere_core/catalog/**
  - packages/core/neurosphere_core/audit/**
  - services/api/neurosphere_api/authz/**
```

## Implementation blueprint

Parallelization map: item 1 first (contracts are Tier 1 and everything types against them). Items 2 and 3 are independent [P] (different files in the core package). Item 4 needs 2 and 3. Item 5 needs 4; item 6 needs only item 1 and can run beside 5 [P]. Item 7 registers and tests end to end; item 8 closes out.

### Item 1 - Contracts
- Deliverable: five schemas under `schemas/compliance/v1/` with examples, `tests/contracts/test_compliance_schemas.py` (valid and invalid examples, additive-only rule, null discipline), regenerated Python and TS bindings.
- Owned files: `packages/contracts/schemas/compliance/**`, generated `packages/contracts/python/neurosphere_contracts/compliance/**` and `packages/contracts/ts/src/compliance/**`, `tests/contracts/test_compliance_schemas.py`.
- Must NOT touch: existing schema families.
- Depends on: none.
- Acceptance criteria: `generate.py --check` clean; examples validate; a summary value outside the four words is rejected.
- Tests: `tests/contracts`.
- Pattern references: `schemas/audit/v1/audit-record.schema.json`, `tests/contracts/test_drift.py`.

### Item 2 - Control library and loader  [P]
- Deliverable: four YAML frameworks (controls fetched from the official sources and recorded with URL and retrieval date), the mapping to evidence-source ids and support statuses, `load_library()` with validation, repo-path existence check for `designed`/`implemented_tested` support.
- Owned files: `packages/core/neurosphere_core/compliance/library/**`, `compliance/loader.py`, `compliance/models.py`, `packages/core/tests/compliance_lib/test_library.py`.
- Must NOT touch: `docs/compliance/**`.
- Depends on: item 1.
- Acceptance criteria: library criteria above; control count and sources are reported in the completion note with any control that could not be verified left out, not guessed.
- Tests: `packages/core/tests/compliance_lib`.
- Pattern references: `capabilities/loader.py`.

### Item 3 - Evidence sources and claim scanner  [P]
- Deliverable: `EvidenceSource` protocol; adapters for catalog ownership and recertification, audit-chain integrity (via `verify_chain` over the domain chain, window and cap), HITL decisions, evaluation results and cost attribution; in-memory fakes; `scan_for_claims`.
- Owned files: `packages/core/neurosphere_core/compliance/sources/**`, `compliance/claims.py`, `packages/core/tests/compliance_lib/test_sources.py`, `test_claims.py`.
- Must NOT touch: the stores themselves.
- Depends on: item 1.
- Acceptance criteria: sources and no-claim criteria above; a source never returns an entity body or principal name; truncation flagged.
- Tests: `packages/core/tests/compliance_lib`.
- Pattern references: `tests/compliance/test_control_mapping.py:89-220`.

### Item 4 - Bundle builder and renderers
- Deliverable: `build_bundle`, canonical JSON and sha256, Markdown renderer with the disclaimer fragment, golden test fixtures.
- Owned files: `packages/core/neurosphere_core/compliance/bundle.py`, `compliance/render.py`, `compliance/__init__.py`, `packages/core/tests/compliance_lib/test_bundle.py`.
- Must NOT touch: items 2 and 3 files except to fix defects (record the deviation).
- Depends on: items 2, 3.
- Acceptance criteria: bundle criterion; summary words derive only from observations and support; a rendered bundle passes the claim scan.
- Tests: `packages/core/tests/compliance_lib`.
- Pattern references: `finops/service.py` determinism notes.

### Item 5 - API  [P]
- Deliverable: `compliance/router.py`, `dependencies.py` (adapters over `app.state` stores, fail closed), `models.py` if wrapping is needed, `register`, `_register_compliance` hook line, allowed-read audit, export with `Content-Disposition` and digest header.
- Owned files: `services/api/neurosphere_api/compliance/**`, `services/api/tests/compliance_api/**`.
- Must NOT touch: `authz/**`, other routers.
- Depends on: item 4.
- Acceptance criteria: API criterion; 403 for a viewer, a cross-domain request and a missing `framework_id` is 422; no `customer_id` is read from the request.
- Tests: `services/api/tests/compliance_api` (new), `services/api/tests/authz`.
- Pattern references: `finops/router.py`, `finops/dependencies.py`.

### Item 6 - Frontend page, mock and unit tests  [P]
- Deliverable: `CompliancePage`, `ControlDetailPage`, hooks, strings (scanned), routes module, mock handler `compliance.ts` with an `evidence_partial` and a `customer_responsibility` control, a forbidden persona and an empty domain.
- Owned files: `frontend/src/features/compliance/**`, `frontend/tests/mock-api/features/compliance.ts`.
- Must NOT touch: shell files (item 7).
- Depends on: item 1.
- Acceptance criteria: page criterion; a vitest scans every string export for claim words; download uses the API client, not a token in the URL.
- Tests: `frontend/src/features/compliance/compliance.test.tsx` (new).
- Pattern references: `features/finops/*`, `tests/mock-api/features/audit.ts`.

### Item 7 - Registration, e2e, a11y and visual
- Deliverable: Tier-2 lines (routes, manifest, nav, mock index, route samples, real-stack rows, route inventories, `manifest_calls.py`), Playwright spec, visual rows and Docker baselines.
- Owned files: `frontend/tests/e2e/compliance/**` plus the Tier-2 appends.
- Depends on: items 5, 6.
- Acceptance criteria: manifest, axe and keyboard suites pass; e2e picks a domain, opens a control and downloads a bundle on the mock API; Python inventories pass.
- Tests: `frontend/tests/e2e/compliance/compliance.spec.ts` (new); `uv run pytest -q services/api/tests/authz services/api/tests/runtime_routes`.
- Pattern references: `frontend/tests/e2e/finops/finops.spec.ts`.

### Item 8 - Integration and close-out
- Deliverable: runbook, `mkdocs.yml` nav line, Tier-3 regeneration (`openapi_export`, `docs/reference/generate.py`, contracts), `python scripts/prp_status.py --write`, `PRPs/INDEX.md`, CHANGELOG, completion note listing controls fetched per framework and anything unverified.
- Owned files: `docs/runbooks/compliance-evidence.md`, this PRP file, `CHANGELOG.md`.
- Depends on: item 7.

## Validation gates
```bash
python packages/contracts/scripts/generate.py --check
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q tests/contracts packages/core/tests/compliance_lib services/api/tests/compliance_api services/api/tests/authz services/api/tests/runtime_routes services/api/tests/test_openapi_drift.py tests/docs tests/compliance
pnpm --filter @neurosphere/frontend lint
pnpm --filter @neurosphere/frontend typecheck
pnpm --filter @neurosphere/frontend test
pnpm --filter @neurosphere/frontend format
NS_E2E_APP_PORT=5291 NS_MOCK_API_PORT=5292 pnpm --filter @neurosphere/frontend test:e2e
python scripts/validate_planning.py
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```
Visual baselines: Docker only (`pnpm --filter @neurosphere/frontend visual:update`).

## Migration and rollback
No data migration: the library ships in the package and bundles are computed on request. The contract family is additive. Rollback is a revert; the route family, page and nav entry disappear together. If a source's store is absent the bundle degrades to `unavailable` for that source instead of failing.

## Live and open gates
None needed: all tests use in-memory stores. A live read of a hosted deployment's bundle is part of the PRP-64 hosted operator checks and is OPEN until the hosted data path (PRP-58) runs. Mapping to a framework is not an assessment, and no authorization or compliance gate (G02) is changed by this PRP.

## NOT building
FINRA mapping; attestations, sign-off, history or scheduled bundles; auto-remediation; new collection in other services; any prompt, response or payload capture; any compliance score or percentage; edits to PRP-23 documents; a legal opinion on any framework.

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [x] All clarification questions are decided, not guessed (row 4 is an ASSUMPTION; control text is fetched, not assumed)

## Execution state

| Item | Status | Branch/worktree | Notes |
|---|---|---|---|
| 1 | todo | | |
| 2 | todo | | |
| 3 | todo | | |
| 4 | todo | | |
| 5 | todo | | |
| 6 | todo | | |
| 7 | todo | | |
| 8 | todo | | |

## Completion note (filled at ship)
- Date, PR number, merge commit:
- Deviations:
- Descoped items:
- OPEN gates:
- Env vars for the operator:
- Follow-up issues filed:
- Operator product check (can an operator use this without editing files or calling raw APIs?):
