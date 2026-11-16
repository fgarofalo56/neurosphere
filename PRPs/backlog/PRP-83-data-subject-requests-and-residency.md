---
name: PRP-83-data-subject-requests-and-residency
status: backlog
priority: P2
order: 74
review: required
created: 2026-11-16
model: sonnet
orchestrator_model: sonnet
implementer_model: sonnet
phase: 7
ns: NS-08, NS-10
depends_on: [PRP-81-compliance-mappings-soc2-iso27001-gdpr]
wave: W23
branch: prp-83-dsr-and-residency
allow_parallel: true
issues: []
---

# PRP-83: Data-subject requests, legal holds and residency

## Goal
Finish the data-protection half of the original compliance scope on top of what PRP-23 and PRP-44 already built. An admin gets a page for legal holds and data-subject requests on the lifecycle API (place and release holds, request erasure, pseudonymization or deletion with a mandatory dry-run first, watch requests move to their outcome) and an execute-mode runbook; the residency label on a domain stops being decoration, because domain creation is refused when the region is not in the deployment's approved set and an admin can see which existing domains fall outside it; the allowed-read audit that PRP-48 started on five routes extends to the remaining read routes, with a test that makes every new read route decide; and the Bicep modules gain optional customer-managed-key parameters (platform-managed keys stay the default). It is for the records officer or privacy lead who today needs raw API calls to place a hold, for the auditor who asks "who read this", and for the operator who must show where data lives and who holds the keys. It runs in W23 on PRP-81, whose GDPR control ids this PRP's features back.

Lifecycle deletes data and deletion cannot be undone: nothing here changes the worker's default (`NS_LIFECYCLE_MODE=dry_run`), nothing here sets execute mode, and the page can only submit requests; the worker mode stays an operator setting.

Out of scope: control mappings (PRP-81 owns the library files; this PRP only flips the GDPR rows it makes true); a data-subject export route (the engine's `export` returns record bodies and has no API; it needs its own privacy review, see NOT building); copilot conversation targets in the lifecycle engine (shim descoped by PRP-23); scheduled expiry sweeps; the hosted deploy of CMK parameters through `infra/demo` and `infra/appservice` (PRP-82); a live execute-mode run in a hosted environment (PRP-64 and PRP-66, operator-gated); any claim of GDPR adequacy, FIPS validation or compliance.

## Why
Original PRD (2026-10-02, `git show 9fbf5f4c:docs/PRD.md`) section 5g and the original `PRP.md` Phase 4:
- "Data residency controls configurable per tenant/region (GDPR Art. 44-49 support)."
- "Encryption at rest and in transit (FIPS 140-validated modules where required) for all stores."
- Story: "As a compliance officer, I want an audit trail of every data access and agent-to-data-asset relationship."
- Description: "...and GDPR data-subject rights." Phase 4 exit criterion (`PRP.md:126` at `9fbf5f4c`): "GDPR data-subject-request workflow functional."

What v1.2 removed or demoted: `docs/PRD.md:53` keeps "Configurable retention, pseudonymization, deletion/export, legal holds and immutable audit retention with documented conflict rules" and "encryption-key retention" as a requirement, and `docs/PRD.md:56` asks for an "approved service/feature/region/SKU matrix", but no requirement says the residency label is enforced, that a data-subject workflow has a user surface, that CMK is available, or that every data read is audited. PRP-23 shipped the engine and an API only; its own product check says "No. There is API only (holds, requests, status) and no UI or CLI".

Evidence from the current tree (re-verified in this worktree):
- Lifecycle routes exist (`services/api/neurosphere_api/lifecycle/router.py:111-293`: holds, requests, status, all `lifecycle.manage` at customer level) and the frontend has no lifecycle feature (`frontend/src/features/` has no `lifecycle` directory; `grep` finds the word only in catalog files).
- A real delete can silently run as a dry run: the dedupe key ignores `dry_run` (`packages/core/neurosphere_core/lifecycle/models.py` `dedupe_key`, used at `lifecycle/jobs.py:116-118,192-203`), the PRP-23 reviewer follow-up 1. A page that submits both would hit it.
- `residency_region` on a domain is validated only by pattern (`packages/contracts/python/neurosphere_contracts/admin/v1/domain_definition.py:31`), copied and echoed (`packages/core/neurosphere_core/admin/platform/domains.py:149`) and never checked against anything; `DomainAdmin._check` checks id, customer and cloud only.
- Allowed reads are audited on five operations (`catalog.search`, `catalog.domain_search`, `dashboard.read`, `compliance.bundle`, `compliance.export`): `grep audited_read` finds only `catalog/router.py`, `ui_adapters/catalog.py`, `dashboards/router.py` and `compliance/router.py`. Entity get, lineage, map viewport, replay and reports use plain `require` (`services/api/neurosphere_api/map/router.py:48`, `replay/router.py:39`, `reports/router.py:54`).
- No Bicep module has a key parameter: `cosmos.bicep`, `storage.bicep`, `eventhubs.bicep` and `search.bicep` take name, location, reuse, tags, network access and SKU only; the platform-managed default is implicit.

## Acceptance criteria
- [ ] Given an admin with customer-level `lifecycle.manage`, When they open `/admin/lifecycle`, Then they see the worker mode (a persistent banner reads that nothing is deleted while the mode is `dry_run`), the policy state, queue depth and active holds, a holds table and a requests table; a caller without the permission sees the forbidden state and the API returns 403 with a denial record.
- [ ] Given the page, When an admin places a hold, Then the confirm dialog shows the exact selectors and the effect ("blocks deletion and expiry of matching records"), the hold appears after a verified read-back, and releasing it needs a second confirmation; a hold with no selector is refused client-side and by the API.
- [ ] Given the page, When an admin requests erasure, pseudonymization or deletion, Then `dry_run` is on by default, turning it off needs a typed confirmation of the action and a target summary, the response `deduplicated` flag is shown, and the list shows the outcome fields the API returns (`status`, `reason`, `governing_rule`, `blocked_by`, `effect`, `verified`, `dry_run`) in plain words; pseudonymization is never labelled as deletion.
- [ ] Given a real request submitted while an identical dry-run request is pending (and the reverse), Then they are separate jobs (the dedupe key includes `dry_run`); two identical real requests still deduplicate; existing queued jobs are not corrupted (migration section).
- [ ] The requests list never contains a subject id or record body: it shows the action, target kind and container, and a short digest of the subject id; audit records for these routes already hold ids by digest and that is asserted by a test that reads the stored records.
- [ ] Given `NS_RESIDENCY_APPROVED_REGIONS` set, When a domain is created with a `residency_region` outside the set, or a Government domain with a non-`usgov*`/`usdod*` region, or a Commercial domain with one, Then creation is 422 with reason `residency_region_not_approved` or `residency_region_wrong_cloud`, nothing is stored and a denial-style audit record names the domain id, not the region list; given the setting unset, behaviour is exactly as today and `GET /api/v1/admin/platform/residency` reports `policy: unset`.
- [ ] `GET /api/v1/admin/platform/residency` (customer-level `config.manage`) returns the approved regions, and each registered domain with `within_policy` true, false or `unknown`; it changes nothing; the admin console shows it on the lifecycle page as a read-only card.
- [ ] Every read route that returns catalog, graph, map, replay, report or export data uses `audited_read` or is on an explicit exemption list with a reason; a test enumerates all routes and fails on an undeclared read route (including routes added by PRP-72, PRP-73, PRP-74 and PRP-76); each newly audited route records domains and result count only, never terms, ids requested or bodies; an audit-store failure never blocks a read.
- [ ] Each of `cosmos.bicep`, `storage.bicep`, `eventhubs.bicep` and `search.bicep` accepts optional customer-managed-key parameters; with the defaults the compiled ARM is byte-for-byte unchanged in the encryption properties (platform-managed); with a key uri the compiled ARM carries the documented property for that service; a key without an identity is refused at compile time by an assertion or an `@allowed` guard; Government modules do not enable a CMK property for a service whose Government support is unverified.
- [ ] `docs/runbooks/data-protection.md` states: what the lifecycle page does and does not do, how an operator sets execute mode and rolls it back, the audit retention statement (audit records are retained indefinitely by design; immutability is lifecycle rule 1; not WORM), where residency is enforced and where it is only a label, how to turn on CMK, and that FIPS posture is inherited from Azure services and is not claimed in-app; the no-claim scan passes.
- [ ] The GDPR control rows in `library/gdpr.yaml` that this PRP makes true move from `planned` to `designed` or `implemented_tested` with existing repository paths; no row moves on assertion alone.
- PRP exit: an admin places a hold and submits a dry-run erasure from the console, sees the outcome and the audit record; creating a domain in a non-approved region is refused; every read route is audited or consciously exempt; CMK parameters compile. A hosted execute-mode erasure with evidence is reported OPEN.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| 1 | Where the approved regions come from | Hard-coded lists; a setting | Setting `NS_RESIDENCY_APPROVED_REGIONS` (comma-separated ARM region names), customer input. Unset means no enforcement (today's behaviour), reported as `policy: unset`. The region-versus-cloud rule is the contract's own statement (Government domains use `usgov*` or `usdod*` regions; data is never bridged across clouds) |
| 2 | What residency enforces | Every write path; domain definitions | Domain creation (and the report). ASSUMPTION: ingest events carry no region and connector configs bind domains, not regions, so write-time checks on ingest and connector paths are a follow-up; a domain's region is the single declared place data for that domain lives |
| 3 | Existing domains outside the set | Block; report | Report only (`within_policy`); nothing is migrated or retired automatically |
| 4 | Data-subject export | Add a route; leave to the engine | Leave. The engine's export returns record bodies and has no API route; adding one is a privacy decision (who may receive bodies, size, redaction) for a separate PRP. The page covers erasure, pseudonymization, deletion and holds |
| 5 | Dedupe fix | Leave and document; fix | Fix: the job-level dedupe key includes `dry_run`. Existing queued jobs keep their old key and simply do not deduplicate against new ones |
| 6 | Subject ids on the page | Show; hide; digest | Digest prefix only (first 12 hex characters of SHA-256). ASSUMPTION: an admin who needs the subject re-enters it |
| 7 | Execute-mode switch | A UI toggle; operator setting | Operator setting only (`NS_LIFECYCLE_MODE`, restart, worker and API). The page never changes it |
| 8 | Read-audit coverage mechanism | Edit every route now; edit known routes plus a test | Edit the known routes now and add the enumerating test so later routes must decide |
| 9 | Audit retention | New setting; documented statement | Documented statement (indefinite by design, `default_ttl: null`; archive tier is a customer option). No new setting. ASSUMPTION |
| 10 | CMK scope | All services; the four data services | Cosmos, Storage, Event Hubs, Search. Key Vault holds the keys and already has purge protection. The exact ARM property names per service come from the Microsoft Learn ARM reference for the API versions in each module; the orchestrator fetches them (subagents have no Learn tool) and pastes them into the brief. Government availability per service is checked the same way and disabled with a reason where unverified |

## Context manifest

### Files to read first
- `services/api/neurosphere_api/lifecycle/router.py` and `models.py` - routes, `RequestView`, `Manager` guard, audited mutations.
- `packages/core/neurosphere_core/lifecycle/{models,jobs,memory,cosmos}.py` - `dedupe_key`, job submit, hold registry, outcome fields.
- `docs/runbooks/lifecycle.md` - the existing mechanics runbook this PRP extends.
- `packages/core/neurosphere_core/admin/platform/domains.py` and `services/api/neurosphere_api/admin/platform/{__init__,domains,deps}.py` - `DomainAdmin._check`, router registration, `Platform` dependency.
- `packages/contracts/python/neurosphere_contracts/admin/v1/domain_definition.py` - `residency_region` text.
- `services/api/neurosphere_api/authz/read_audit.py` and `PRPs/shipped/PRP-48-authorization-and-audit-chain-hardening.md` (decision 3, item 4) - the audited-read contract.
- `services/api/neurosphere_api/{map,replay,reports}/router.py`, `catalog/router.py:256-298` - routes to cover.
- `infra/bicep/modules/{cosmos,storage,eventhubs,search,keyvault,main}.bicep` and `tests/security/network/test_bicep_network.py` - modules and the `az bicep build` test pattern.
- `frontend/src/features/admin/shared/areas.ts`, `frontend/src/features/admin/audit/AdminAuditPage.tsx`, `frontend/src/features/governed-change` - console area registry and confirm dialog.
- `PRPs/shipped/PRP-23-ato-evidence-and-data-lifecycle.md` - completion note (reviewer follow-ups, product check).

### Interfaces consumed
- PRP-23 (shipped): `/api/v1/lifecycle/holds`, `/requests`, `/status`; `LifecycleJob`, `LegalHold`, `LifecycleOutcome`; `Permission.LIFECYCLE_MANAGE` via `require_customer_control`; env `NS_LIFECYCLE_MODE`, `NS_LIFECYCLE_POLICY_FILE`, `NS_LIFECYCLE_MAX_ATTEMPTS`.
- PRP-44 (shipped): domain registry, `DomainAdmin`, `PlatformAdmin` plane, `Platform` dependency, `config.manage` at customer level.
- PRP-48 (shipped): `audited_read`, `ReadAudit.allowed`, `read_audit_stats`.
- PRP-53 and PRP-57 (shipped): admin console areas and shared admin components.
- PRP-81 (W20, merged): `packages/core/neurosphere_core/compliance/library/gdpr.yaml` with ids `gdpr.art-5`, `gdpr.art-17`, `gdpr.art-25`, `gdpr.art-30`, `gdpr.art-32`, `gdpr.art-44` to `gdpr.art-49` (those PRP-81 item 3 included). This PRP edits that existing file's `status` and evidence-path fields only; it does not create it or change ids.
- PRP-72, PRP-73, PRP-74, PRP-76 (earlier waves, assumed merged): new read routes that the coverage test must find already audited or exempt.

### Interfaces provided
- Core: `neurosphere_core.residency` - `ResidencySettings` (`NS_RESIDENCY_APPROVED_REGIONS`), `ApprovedRegions.check(cloud, region)` with typed refusal reasons; `DomainAdmin` accepts an optional `residency` policy (default read from settings).
- Route: `GET /api/v1/admin/platform/residency`.
- Lifecycle API additions: `RequestView.subject_ref` (digest prefix) and `target_summary`; job-level dedupe key including `dry_run`.
- Audit operations for the newly covered routes (`catalog.entity_read`, `catalog.lineage`, `map.viewport`, `replay.trace`, `report.read`, `catalog.export`; final names listed in the completion note).
- Test `tests/security/authz/test_read_audit_coverage.py` with an exemption list `READ_AUDIT_EXEMPT` (path, reason).
- Bicep parameters per module (`cmkKeyUri`, `cmkIdentityId`, names confirmed from the ARM reference), documented in `docs/runbooks/data-protection.md`.
- Frontend route `admin/lifecycle` and area id `lifecycle` in `ADMIN_AREAS`.

### Patterns to match
- Audited mutation with read-back and `on_error`: `lifecycle/router.py:111-160`.
- Admin sub-router registration: `admin/platform/__init__.py:register`.
- Allowed-read dependency use: `catalog/router.py:117,263-273`, `compliance/router.py:61-67`.
- Bicep compile assertions: `tests/security/network/test_bicep_network.py`.
- Console page with governed confirm: `frontend/src/features/admin/audit/AdminAuditPage.tsx`, `StaleAgentsPage.tsx` (dry-run then confirm).
- Env-clearing conftest names: `services/api/tests/runtime_planes/conftest.py:8-36` (add `NS_RESIDENCY_`).

### Gotchas
- The lifecycle API never deletes: it persists a job and the worker acts; the page must say so and never imply deletion happened when `mode` is `dry_run`.
- `dedupe_key` is part of Cosmos document ids (digest of the key, `lifecycle/cosmos.py:264`) and of a queryable field (`jobs.py:192-203`); change it in one place (a job-level property) and keep `LifecycleRequest.dedupe_key` for the engine's own use.
- Audit and subject data: never log or audit a subject id, region list or record body; digests and reason codes only (CodeQL secret-name and PII rules).
- `DomainAdmin` is constructed in `runtime/builders/admin_platform.py` (Tier 1, not edited here): the policy must default from settings inside `DomainAdmin` so no builder change is needed.
- Adding `audited_read` to a route changes its dependency signature: the path-alias, route-inventory and `verify_route_permissions` tests must still pass; list the updates in the PR.
- Existing routes edited here belong to earlier waves' PRPs (PRP-74 map); rebase on `main` before editing and re-run their suites; do not reformat or move code.
- `az` and `az bicep build` may be unavailable locally: the compile tests skip as the network test does and CI is the proof. No `az deployment` and no what-if run here.
- Same-named test directories shadow each other: new tests use the unique names below.
Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - packages/core/neurosphere_core/residency/**
  - packages/core/neurosphere_core/admin/platform/domains.py
  - packages/core/neurosphere_core/lifecycle/jobs.py
  - packages/core/neurosphere_core/lifecycle/memory.py
  - packages/core/tests/residency/**
  - packages/core/tests/lifecycle_dedupe/**
  - services/api/neurosphere_api/admin/platform/residency.py
  - services/api/neurosphere_api/admin/platform/__init__.py
  - services/api/neurosphere_api/lifecycle/**
  - services/api/neurosphere_api/map/router.py
  - services/api/neurosphere_api/replay/router.py
  - services/api/neurosphere_api/reports/router.py
  - services/api/neurosphere_api/catalog/router.py
  - services/api/tests/lifecycle_api/**
  - services/api/tests/residency_api/**
  - services/api/tests/read_audit_api/**
  - tests/security/authz/test_read_audit_coverage.py
  - tests/security/authz/test_lifecycle_admin*.py
  - tests/security/encryption/**
  - packages/core/neurosphere_core/compliance/library/gdpr.yaml
  - frontend/src/features/admin/lifecycle/**
  - frontend/src/features/admin/shared/areas.ts
  - frontend/tests/mock-api/features/admin-lifecycle.ts
  - frontend/tests/e2e/admin-lifecycle/**
  - docs/runbooks/lifecycle.md
  - docs/runbooks/data-protection.md
tier1:
  - infra/bicep/modules/cosmos.bicep
  - infra/bicep/modules/storage.bicep
  - infra/bicep/modules/eventhubs.bicep
  - infra/bicep/modules/search.bicep
  - infra/bicep/modules/main.bicep
tier2_appends:
  - services/api/neurosphere_api/runtime/settings.py
  - frontend/src/app/appRoutes.ts
  - frontend/src/app/route-manifest.json
  - frontend/src/app/workspaceNav.ts
  - frontend/tests/mock-api/features/index.ts
  - frontend/tests/e2e/a11y/route-samples.ts
  - frontend/tests/real-stack/routes.spec.ts
  - services/api/tests/authz/test_route_inventory.py
  - services/api/tests/authz/test_startup_route_check.py
  - services/api/tests/runtime_routes/manifest_calls.py
  - tests/integration/real_stack/test_manifest_routes.py
  - mkdocs.yml
must_not_touch:
  - packages/contracts/**
  - services/api/neurosphere_api/runtime/builders/**
  - services/api/neurosphere_api/authz/dependencies.py
  - services/api/neurosphere_api/authz/read_audit.py
  - packages/core/neurosphere_core/lifecycle/engine.py
  - packages/core/neurosphere_core/lifecycle/targets.py
  - packages/core/neurosphere_core/compliance/library/soc2_tsc.yaml
  - packages/core/neurosphere_core/compliance/library/iso_27001_annex_a.yaml
  - infra/demo/**
  - infra/appservice/**
  - infra/helm/**
  - frontend/tests/mock-api/server.ts
```

## Implementation blueprint

Parallelization: items 1, 3 and 4 are [P] (no shared file or dependency). Item 2 is independent too but shares `lifecycle/**` with item 5, so item 5 follows items 2 and 1. Item 6 after 3, 4 and 5; item 7 last.

### Item 1 - Residency policy and report  [P]
- Deliverable: `neurosphere_core/residency/` (`ResidencySettings` with `NS_RESIDENCY_APPROVED_REGIONS`, `ApprovedRegions.check`, reasons `residency_region_not_approved` and `residency_region_wrong_cloud`), the check inside `DomainAdmin._check`, `admin/platform/residency.py` (`GET /api/v1/admin/platform/residency` with `within_policy` per domain) registered in `admin/platform/__init__.py`, `NS_RESIDENCY_` field group in `runtime/settings.py` only if the API needs it for display.
- Owned files: `packages/core/neurosphere_core/residency/**`, `admin/platform/domains.py`, `services/api/neurosphere_api/admin/platform/{residency,__init__}.py`, `packages/core/tests/residency/**`, `services/api/tests/residency_api/**`.
- Must NOT touch: `runtime/builders/**`, contracts.
- Depends on: none.
- Acceptance criteria: the residency criteria; unset policy leaves every existing `admin_platform` test passing unchanged; a Government region on a Commercial deployment is refused whatever the approved set says.
- Tests: `packages/core/tests/residency/test_policy.py`, `services/api/tests/residency_api/test_domain_create.py`, `test_report.py`; re-run `packages/core/tests/admin_platform` and `services/api/tests/admin_platform_api`.
- Pattern references: `domains.py` `_check_canonical`; `admin/platform/domains.py` routes.

### Item 2 - Lifecycle API corrections  [P]
- Deliverable: job-level dedupe key including `dry_run` (`jobs.py`, `memory.py`), `RequestView.subject_ref` and `target_summary`, no subject id anywhere in a view, status view unchanged; execute-mode steps and the dry-run-first procedure added to `docs/runbooks/lifecycle.md`.
- Owned files: `packages/core/neurosphere_core/lifecycle/{jobs,memory}.py`, `services/api/neurosphere_api/lifecycle/{models,router}.py`, `docs/runbooks/lifecycle.md`, `packages/core/tests/lifecycle_dedupe/**`, `services/api/tests/lifecycle_api/test_dedupe_dry_run.py`, `test_views_no_subject.py`.
- Must NOT touch: `lifecycle/engine.py`, `targets.py`, `cosmos.py` document-id logic (the digest is of the request key, unchanged).
- Depends on: none.
- Acceptance criteria: the dedupe and no-subject criteria; the PRP-23 suites (`packages/core/tests/lifecycle`, `services/api/tests/lifecycle_api`, worker lifecycle suite) pass unchanged except new fixtures.
- Tests: the new files plus `packages/core/tests/lifecycle`, `services/api/tests/lifecycle_api`, `services/workers/tests/lifecycle_worker`.
- Pattern references: `lifecycle/jobs.py:105-125`.

### Item 3 - Wider allowed-read audit and coverage test  [P]
- Deliverable: `audited_read` on catalog entity get and lineage routes, map viewport, replay trace routes, report get, list and run-read routes and catalog export, each with an operation name; `test_read_audit_coverage.py` enumerating the app's routes, resolving each route's dependencies and failing for a route with a read permission (`data.read`, `evidence.read`, `data.export`, `audit.read`) that has neither an `audited_*` dependency nor an entry in `READ_AUDIT_EXEMPT` (with reason); the exemption list covers health and similar by explicit entry.
- Owned files: `services/api/neurosphere_api/{map,replay,reports,catalog}/router.py` (the read dependencies only), `services/api/tests/read_audit_api/**`, `tests/security/authz/test_read_audit_coverage.py`.
- Must NOT touch: `authz/read_audit.py`, `authz/dependencies.py`.
- Depends on: none; rebase on `main` with PRP-72, PRP-73, PRP-74, PRP-76 merged before starting.
- Acceptance criteria: the read-audit criterion; every previously passing route test still passes; each new record asserted to hold domains and count only; failure of the audit store does not change a response.
- Tests: `services/api/tests/read_audit_api/test_entity_reads.py`, `test_lineage_reads.py`, `test_map_replay_report_reads.py`, `tests/security/authz/test_read_audit_coverage.py`; re-run `services/api/tests/{catalog,map,replay,reports,authz,path_aliases,runtime_routes}` and `tests/security/authz`.
- Pattern references: `services/api/tests/read_audit_api/test_search_reads.py`, `compliance/router.py:61-67`.

### Item 4 - Optional customer-managed keys in Bicep  [P]
- Deliverable: optional key-uri and identity parameters on the four modules (defaults empty, encryption properties unchanged), the matching pass-through parameters in `main.bicep`, a guard that a key without an identity fails compilation, Government gating where support is unverified, `tests/security/encryption/test_bicep_cmk.py` compiling with `az bicep build` (skipped when `az` is absent) and asserting both the unchanged default and the keyed output. ARM property names are taken from the brief, not from memory.
- Owned files: the five Bicep modules, `tests/security/encryption/**` (with `__init__.py`).
- Must NOT touch: `infra/demo/**`, `infra/appservice/**`, `infra/helm/**`, the network module.
- Depends on: none.
- Acceptance criteria: the CMK criterion; `tests/security/network/test_bicep_network.py` still passes; no `az deployment` or what-if is run.
- Tests: `tests/security/encryption/test_bicep_cmk.py`; re-run `tests/security/network`.
- Pattern references: `tests/security/network/test_bicep_network.py`, `cosmos.bicep` parameter style.

### Item 5 - Admin lifecycle page
- Deliverable: `frontend/src/features/admin/lifecycle/` with `LifecyclePage` (mode banner, status, residency card from the report route), `HoldsPanel` (place and release through the governed confirm), `RequestsPanel` (submit with dry-run default and typed confirmation for a real run, outcome rendering in plain words, `deduplicated` notice), hooks, strings, types; `ADMIN_AREAS` entry; mock handlers `admin-lifecycle.ts` with a dry-run and an execute-mode status, a blocked-by-hold outcome and a forbidden fixture.
- Owned files: `frontend/src/features/admin/lifecycle/**`, `frontend/src/features/admin/shared/areas.ts` (append one entry), `frontend/tests/mock-api/features/admin-lifecycle.ts`.
- Must NOT touch: other admin folders, `server.ts`.
- Depends on: items 1 and 2 (response shapes).
- Acceptance criteria: the page criteria (mode banner, hold confirm, dry-run default, typed confirmation, outcome wording, no subject id); strings pass the no-claim scan pattern; loading, empty, error and forbidden states.
- Tests: `frontend/src/features/admin/lifecycle/lifecycle.test.tsx`, `frontend/tests/mock-api/features/admin-lifecycle.test.ts` (new).
- Pattern references: `frontend/src/features/admin/audit/AdminAuditPage.tsx`, `StaleAgentsPage.tsx`.

### Item 6 - Authorization, e2e, mapping flips and runbook
- Deliverable: ABAC negative cases for the lifecycle routes as the page uses them and for the residency route (no role, auditor, ordinary-domain admin, wrong customer), Tier-2 registrations, Playwright specs for hold place and release and a dry-run erasure, axe in three themes, `docs/runbooks/data-protection.md`, the GDPR rows in `gdpr.yaml` moved only where a test now exists, the no-claim scan over the runbook and page strings.
- Owned files: `tests/security/authz/test_lifecycle_admin*.py`, `frontend/tests/e2e/admin-lifecycle/**`, `docs/runbooks/data-protection.md`, `packages/core/neurosphere_core/compliance/library/gdpr.yaml`, Tier-2 lines.
- Must NOT touch: other library files.
- Depends on: items 1 to 5.
- Acceptance criteria: the runbook and mapping criteria; manifest, axe and keyboard suites pass; `packages/core/tests/compliance_lib` passes.
- Tests: `tests/security/authz`, `packages/core/tests/compliance_lib`, `frontend/tests/e2e/admin-lifecycle/lifecycle.spec.ts`.
- Pattern references: PRP-41 authz suite; `frontend/tests/e2e/admin-sources/producers.spec.ts`.

### Item 7 - Integration and close-out
- Deliverable: rebase, Tier-3 regeneration (`openapi.json`, `docs/reference/**`, status table, `PRPs/INDEX.md`, `PRPs/EXECUTION-PLAN.md`), changelog fragment `changelog.d/PRP-83-data-subject-requests-and-residency.md`, completion note with env vars (`NS_RESIDENCY_APPROVED_REGIONS`), the list of newly audited operations, which GDPR rows moved, and the product check (can a records officer place a hold and request a dry-run erasure without raw API calls?). Local evidence: with the compose emulator, one synthetic subject erased in execute mode on the worker and read back, recorded under `docs/evidence/PRP-83/` (local, synthetic data only).
- Owned files: this PRP file, the fragment, `docs/evidence/PRP-83/**`, Tier-3 files.
- Depends on: items 1 to 6.
- Acceptance criteria: validation gates pass; CI green.

## Validation gates
```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q packages/core/tests/residency packages/core/tests/lifecycle packages/core/tests/lifecycle_dedupe packages/core/tests/admin_platform packages/core/tests/compliance_lib services/api/tests/residency_api services/api/tests/lifecycle_api services/api/tests/admin_platform_api services/api/tests/read_audit_api services/api/tests/catalog services/api/tests/map services/api/tests/replay services/api/tests/reports services/api/tests/path_aliases services/api/tests/runtime_routes services/api/tests/authz services/workers/tests/lifecycle_worker tests/security/authz tests/security/encryption tests/security/network services/api/tests/test_openapi_drift.py tests/docs/test_reference_coverage.py
pnpm --filter @neurosphere/frontend lint
pnpm --filter @neurosphere/frontend typecheck
pnpm --filter @neurosphere/frontend test
pnpm --filter @neurosphere/frontend format
NS_E2E_APP_PORT=5295 NS_MOCK_API_PORT=5296 pnpm --filter @neurosphere/frontend test:e2e
python scripts/prp_status.py --check
python scripts/validate_planning.py
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```
Visual baselines: `visual:update` in the pinned Docker image, then `visual:check`. Local execute-mode evidence (item 7) runs only against the compose emulator with synthetic data; one compose lane at a time.

## Migration and rollback
- Residency: no data migration. Unset `NS_RESIDENCY_APPROVED_REGIONS` to switch enforcement off; existing domains are never changed.
- Dedupe key: the job-level key changes shape. Jobs already queued keep their stored key; a new identical request will not deduplicate against an old queued one and may create a second job, which the engine's conflict rules and idempotent targets handle (a duplicate erase finds nothing). Rollback: revert the PR; no stored data needs repair.
- Read audit: additive records on existing chains; rollback by revert. A flood of records on a busy route is a capacity question measured in PRP-66, not a correctness one.
- CMK: parameters default to empty, so existing templates and deployments are unchanged. Turning a key on for an existing account is an operator change with its own provider-side effects (key access, rotation, possible downtime) and is never done by this PRP; rollback of the PR does not undo a key an operator already set.
- Lifecycle page: it only submits requests. Execute mode stays an operator setting. Erased data cannot be restored by this product: recovery is from backup or DR (`docs/runbooks/dr.md`), which is why dry-run is the default and the page asks for typed confirmation. To remove the page, revert the frontend item; the API is unchanged.

## Live and open gates
OPEN until an approved environment runs them (`NS_LIVE_APPROVED=1`, operator, PRP-64 and PRP-66): an execute-mode erasure with evidence on a hosted deployment (G06 customer inputs also OPEN: retention policy and legal-hold process); a CMK deployment against a real Key Vault key and the Azure Government availability check; a `what-if` of the changed modules (an `az deployment` command is denied in this environment); a measured RU and latency cost of the added read-audit records; the real-stack walk of `/admin/lifecycle`. Nothing here claims GDPR compliance, adequacy, FIPS validation or an authorization.

## NOT building
A data-subject export route or download; automatic subject discovery across stores; a UI switch for execute mode; scheduled expiry sweeps; write-time residency checks on ingest and connectors (follow-up, clarification 2); automatic migration or retirement of out-of-policy domains; CMK wiring in `infra/demo`, `infra/appservice` or Helm (PRP-82); a new audit retention setting; a WORM audit store; classification-aware read rules.

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [ ] All clarification questions are decided, not guessed (rows 2, 6 and 9 are ASSUMPTIONS for plan approval; row 10 depends on the orchestrator fetching ARM property names)

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

## Completion note (filled at ship)
- Date, PR, merge commit:
- Deviations from the blueprint and why:
- Descoped items:
- OPEN gates:
- Env vars for the operator:
- Follow-up issue numbers:
- Product check (can an operator use it without editing files or calling raw APIs?):
