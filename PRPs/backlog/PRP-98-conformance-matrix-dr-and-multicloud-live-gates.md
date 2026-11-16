---
name: PRP-98-conformance-matrix-dr-and-multicloud-live-gates
status: backlog
priority: P2
order: 89
review: required
created: 2026-11-16
model: sonnet
orchestrator_model: sonnet
implementer_model: sonnet
phase: 8
ns: NS-08, NS-10
depends_on: [PRP-85-deployment-target-ports-and-adapter-boundary, PRP-86-contracts-platform-dimension-and-credential-kinds, PRP-87-api-composition-seam-and-adapter-packages, PRP-88-worker-composition-seam-event-and-object-ports, PRP-89-postgres-foundation-catalog-and-security-stores, PRP-90-postgres-data-plane-stores, PRP-91-postgres-control-plane-stores-and-search, PRP-92-kafka-and-object-store-adapters, PRP-93-generic-oidc-identity, PRP-94-secret-readers-and-workload-identity, PRP-95-model-telemetry-and-analytics-adapters, PRP-96-helm-for-four-platforms-and-on-prem-reference, PRP-97-terraform-reference-for-aws-and-gcp, PRP-64-live-gates-campaign, PRP-66-operations-and-sign-off-gates]
wave: W29
branch: prp-98-conformance-matrix-dr-and-multicloud-live-gates
allow_parallel: true
issues: []
---

# PRP-98: Conformance matrix, DR and RPO/RTO per target, live-gate scripts, closing the ratchet

## Goal
Close the multi-cloud program honestly. Ships: the strict adapter boundary (the ratchet from PRP-85 reaches zero leaks outside named adapter packages, and every required port has an implementation or a recorded reason per platform); a generated conformance matrix (port by backend by platform: passed in containers, recorded-transport only, or OPEN) plus a generated "what is disabled and why" page per platform; DR runbooks and backup and restore tooling for PostgreSQL and the object stores with an emulator-class drill on the portable containers; a per-target RPO/RTO table labelled "target, unmeasured" until a live run; the gate scripts an operator runs later for AWS, GCP and on-prem, each refusing without `NS_LIVE_APPROVED=1`; register rows; and the threat-model and SSP documentation deltas. It is for the architect and the operator who must know exactly what is proven and what is not, and for PRP-64 and PRP-66, which run the live gates. It runs in W29, alone, after PRP-85 to PRP-97. It makes no compliance, availability, authorization or parity claim for any target.

Out of scope: building adapters, charts or Terraform (PRP-87 to PRP-97); running any live gate (operator-only, PRP-64 for service gates and PRP-66 for DR, load and sign-off); measured RPO/RTO on any target (the table is targets only); AWS and GCP equivalents of Azure-only features; migration of an existing Cosmos deployment to PostgreSQL; changes to the Azure DR scripts' behaviour (extended additively only); a Pub/Sub or OpenSearch adapter.

## Why
- Original-PRD 5f (`git show 9fbf5f4c:docs/PRD.md`): "Documented RPO/RTO per deployment target." and "Core platform logic (ingestion normalization, graph API, recommendation engine, copilot) is cloud-agnostic; only infra adapters differ." v1.2 removed multi-cloud and only kept provisional Azure targets: `docs/PRD.md:4`, `docs/PRD.md:53` ("RTO <=4h/RPO <=15min are provisional profile targets requiring measured end-to-end evidence") and `docs/PRD.md:57`; `PRP.md:7` and `PRP.md:11`. The owner's 2026-11-16 decision overrides the exclusions for AWS, GCP and on-prem Kubernetes; the measured-evidence rule stays.
- The boundary is only enforced as a ratchet today: PRP-85 lists the leak files as known violations (about 36 files with 61 `azure.*` import lines at design time, `temp/audit/multicloud-program-design.md` section 2.1) and fails any new one; nothing makes the list reach zero or tests that each port has an implementation per platform. No `tests/architecture/` exists on `main` yet (PRP-85 creates it).
- DR tooling is Azure-store specific: `infra/dr/ns_dr_stores.py` exports Cosmos containers, blobs and Event Hubs checkpoints; `infra/dr/ns_dr_safety.py:1-10` refuses non-local targets unless `NS_LIVE_APPROVED=1` and `--target` are given; `docs/ops/dr-runbook.md` records compose-only measurements and marks failover "not yet exercised" (section 4), guarded by `tests/integration/dr/test_runbook_caveats.py`.
- The recovery targets exist only as Azure provisional numbers (`docs/ops/dr-runbook.md:6-12`; `docs/PRD.md:53`). PRP-85 creates a skeleton `docs/ops/rpo-rto.md`; no target has a mechanism or a drill.
- The register has no multi-cloud rows (`docs/RESEARCH-AND-GATES.md` grep for AWS and multi-cloud finds none), and the live-gate scripts all target Azure (`scripts/gates/*`; refusal pattern `g01_analytics_live.py:778-785`; evidence confinement `scripts/gates/_evidence_paths.py`).
- Every real AWS and GCP run needs an account the project does not have today; saying "supported" without a run would be the failure mode the owner cares about most.

## Acceptance criteria
- [ ] Given the strict boundary test, When it scans non-test product code, Then no `azure.*`, `boto*`, `aiobotocore`, `google.*`, `asyncpg`, `aiokafka` or other vendor-SDK import exists outside the named adapter packages and named adapter modules; `KNOWN_LEAKS` from PRP-85 is empty (or holds only D-11 named exceptions, each with owning PRP and follow-up issue); adding one violating import fails the test (proved with a temporary edit).
- [ ] Given the port inventory (PRP-85) and the implementations registered per platform, When the coverage test runs, Then it fails when a required port has no implementation for a platform and no "disabled with a reason" entry, and when a port with an implementation has no conformance module under `tests/conformance/<port>/`.
- [ ] A generator produces `docs/deploy/platform-matrix.md` from the inventory, the conformance directories and the registered markers: each cell is exactly one of `container` (suite ran against the portable container in CI or locally), `emulator`, `recorded` (recorded transport only), `in-memory`, `disabled: <reason>` or `OPEN`; no cell says "supported" or "certified"; a drift test fails when the committed page differs from the generated one.
- [ ] A generated page `docs/deploy/platform-disabled-features.md` lists, per platform, every feature the capability matrix (PRP-86 `platform` dimension) disables with its reason code, taken from data, not prose.
- [ ] `infra/dr` backs up and restores PostgreSQL (all registered container tables, with row counts and content digests) and the S3-compatible and GCS object stores (blobs with metadata) through the same target-safety rules; an emulator-class drill on the portable containers (PostgreSQL and the object store from the compose fragments) seeds, backs up, loses, restores, verifies digests and records timings; the existing Azure drill, scripts and tests pass unchanged.
- [ ] `docs/ops/rpo-rto.md` has one row per target (Azure, AWS, GCP, on-prem) with the mechanism (managed backup and point-in-time recovery, topic replication, bucket versioning or replication, in-cluster operator backups), the target (4 h RTO, 15 min RPO, copied from `docs/PRD.md:53`) labelled "target, unmeasured", and a measured column that is empty unless a drill on that target is evidenced; the emulator-class drill is recorded as "compose, not representative of production" only.
- [ ] `docs/ops/dr-runbook.md` gains per-target sections (backup, restore, failover and failback steps written from provider documentation, with source URL and date, marked "not exercised") without weakening any caveat checked by `tests/integration/dr/test_runbook_caveats.py` (the test still passes unchanged).
- [ ] `scripts/gates/multicloud_aws_live.py`, `multicloud_gcp_live.py` and `multicloud_onprem_live.py` (and a shared module) refuse with exit code 2 and a message "No connection was attempted" unless `NS_LIVE_APPROVED=1`, check that before parsing arguments, confine `--evidence-dir` under `docs/evidence/multicloud/`, take every target name as an argument, never read `.env` or a credential file, never print a credential, and write an evidence file per phase listing what ran and what did not; a test imports each with the environment variable unset and proves refusal with no socket opened.
- [ ] Each live script's phases match the design's live-gate list: AWS (apply of the reference Terraform, RDS IAM auth, MSK auth, S3 conditional writes, Secrets Manager, Cognito sign-in and token validation, one Bedrock turn, EKS install, restore drill); GCP (apply, Cloud SQL IAM auth, Managed Kafka auth, GCS, Secret Manager, one Vertex turn, GKE install, restore drill, IdP choice); on-prem (install on a customer-like cluster, air-gapped install from the bundle, restore drill, load at stated targets). Every phase that was not run is written OPEN with the reason.
- [ ] `docs/RESEARCH-AND-GATES.md` gains rows for the three platforms (status OPEN, naming exactly which phases remain), and the handoff is stated: service gates to PRP-64, DR, load and sign-off to PRP-66.
- [ ] `docs/security/threat-model.md` and the SSP scope and family text (`docs/compliance/ssp/scope.md` and the family files that name Azure-managed boundaries) carry a delta for the new trust boundaries (broker, database and identity provider no longer Azure-managed; Terraform state sensitivity; image set), stating no authorization or compliance claim for AWS or GCP.
- [ ] Nothing in the generated pages, docs or scripts claims FedRAMP, ATO, compliance parity, availability or "production ready" for any platform; a grep test over the new pages for those words fails on a positive claim and allows negated uses.
- PRP exit: touched suites, `tests/architecture`, `tests/integration/dr`, ruff, pyright, `validate_planning.py` pass; PR open with CI green; the three live runs written OPEN.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| D-1 | Hosting axis (program decision D-1) | new `DeploymentTarget` axis beside `NS_CLOUD`; widen the cloud enum | Decided by the owner 2026-11-16: a new `DeploymentTarget` axis (`NS_PLATFORM` = azure, aws, gcp, kubernetes; default azure) beside the existing `NS_CLOUD` boundary class; `government` is valid only with azure; canonical IDs are unchanged (they keep the `commercial:` first segment on AWS, GCP and on-prem). Recorded in the PRP-85 multicloud-hosting ADR |
| D-2 | Backend strategy (program decision D-2) | a native service adapter per cloud; one portable backend set | Decided by the owner 2026-11-16: one portable backend set (PostgreSQL, Kafka API, S3 API plus native GCS, generic OIDC, OTLP, OpenAI-compatible/Bedrock/Vertex model adapters) running on each cloud's managed service or in-cluster, not a native service adapter per cloud (no DynamoDB, Firestore or Pub/Sub adapters). Recorded in the PRP-85 multicloud-hosting ADR |
| 2 | OPEN backends in the matrix | hide; show | The matrix shows Pub/Sub, OpenSearch, ClickHouse as OPEN, not as gaps hidden |
| 3 | Matrix cell vocabulary | pass/fail; evidence kind | Evidence kind (`container`, `emulator`, `recorded`, `in-memory`, `disabled`, `OPEN`); "container" may be claimed only when the `portable` suite is wired into a workflow that ran, or the completion note records a local run with date and commit |
| 4 | Ratchet end state (owner decision D-11 in PRP-85 for leftovers) | zero everywhere; zero outside named packages | Zero outside named adapter packages and named adapter modules (`ADAPTER_PATHS` in PRP-85's `tests/architecture/boundary.py`; Azure adapters stay inside `neurosphere-core` where they are); per D-11 (recommended), a leak an earlier PRP left stays as a named `KNOWN_LEAKS` entry with its owning PRP and a follow-up issue rather than blocking |
| 5 | RPO/RTO values | new numbers; the Azure provisional ones | Copy `docs/PRD.md:53` (4 h, 15 min) for every target, each "target, unmeasured"; a managed-service default (for example point-in-time recovery windows) is written as mechanism, never as a promise |
| 6 | Drill scope | real clouds; compose containers | Compose containers only (PostgreSQL, S3-compatible store); clearly labelled not representative of production |
| 7 | Live scripts depend on | recorded transports; real SDKs | Real SDK calls only inside functions reachable after the approval check; imports of cloud SDKs are lazy, so importing the module with the variable unset opens no socket and needs no credential |
| 8 | Who runs them | this PRP; operator later | Operator later under `NS_LIVE_APPROVED=1`: service gates through PRP-64, DR, load and sign-off through PRP-66. Each needs a cloud account the project does not have today |
| 9 | Where the register rows go | new gate ids; existing | ASSUMPTION: new ids `G18` (AWS), `G19` (GCP), `G20` (on-prem), chosen after reading the register's current highest id at execution; `docs/RESEARCH-AND-GATES.md` is not in another PRP's ownership in W29 |
| 10 | Tier-1 files | needed; avoided | None expected: generation runs from scripts the existing tests call; no workflow edit. If a CI job for the generator drift test is wanted, use the data-driven runner from PRP-89 (`scripts/portable/run_conformance.py`) or add a `[serial-after]` item and report |

## Context manifest

### Files to read first
- PRP-85's outputs: `packages/core/neurosphere_core/platform/inventory.py`, `tests/architecture/boundary.py` (`ADAPTER_PATHS`, `KNOWN_LEAKS`, `LEAK_CEILING`), `docs/adr/*-multicloud-hosting.md`, `docs/dev/platform-ports.md`, `docs/ops/rpo-rto.md` (skeleton) - the inventory, the known-leaks list and the ADR.
- `tests/conformance/*/` (PRP-89 to PRP-95) - conformance modules and markers (`portable`, `integration`); `scripts/portable/run_conformance.py` and `.github/workflows/portable-conformance.yml`.
- `infra/dr/{ns_dr.py,ns_dr_stores.py,ns_dr_safety.py,ns_dr_drill.py,ns_dr_emulator.py,README.md}` - the structure to extend.
- `tests/integration/dr/{conftest,test_restore_compose,test_runbook_caveats,test_target_refusal}.py`.
- `docs/ops/dr-runbook.md` (all sections) and `docs/evidence/G07/dr/` (the compose measurement and its labels).
- `scripts/gates/g01_analytics_live.py` (approval check and structure) and `scripts/gates/_evidence_paths.py` (confinement).
- `docs/RESEARCH-AND-GATES.md` (row format, highest gate id) and `docs/evidence/inventory.md`.
- `docs/security/threat-model.md`, `docs/compliance/ssp/scope.md` and `docs/compliance/ssp/families/sc.md` (boundary wording).
- `packages/core/neurosphere_core/capabilities/` and the PRP-86 platform rows and loader (source for the disabled-features page).
- `PRPs/backlog/PRP-64-live-gates-campaign.md` and `PRP-66-operations-and-sign-off-gates.md` - how a handed-off gate is recorded.

### Interfaces consumed
- PRP-85: port inventory (name, Protocol, required or optional, implementations per platform), `KNOWN_LEAKS`, `DeploymentTarget`, `docs/ops/rpo-rto.md` skeleton, platform-outputs schema.
- PRP-86: capability-matrix `platform` dimension and rows; `CredentialReference` kinds.
- PRP-87, PRP-88: backend provider and registrations (which implementation serves which port on which platform), adapter packages.
- PRP-89 to PRP-95: conformance directories, markers, compose fragments under `infra/compose/portable/`, adapter names, PostgreSQL table naming (one per registered container) for the DR export.
- PRP-96: install paths, `kind` smoke (a phase in the on-prem script), air-gap bundle (`infra/onprem/`), values-overlay generator.
- PRP-97: Terraform roots and the validate entry point (`scripts/terraform/validate.py`); the AWS and GCP apply phases refer to them.
- PRP-64, PRP-66: where evidence and drills are recorded; their evidence layout under `docs/evidence/`.

### Interfaces provided
- `scripts/platform/gen_matrix.py` (new) writing `docs/deploy/platform-matrix.md` and `docs/deploy/platform-disabled-features.md`; `--check` for drift.
- `scripts/gates/multicloud_{aws,gcp,onprem}_live.py` and `scripts/gates/_multicloud_common.py`; evidence directory `docs/evidence/multicloud/{aws,gcp,onprem}/`.
- `infra/dr/ns_dr_postgres.py` and `ns_dr_objectstore.py` (new modules) behind the existing `ns_dr.py` CLI.
- `tests/architecture/test_strict_boundary.py`, `test_port_coverage.py`; `tests/integration/dr/test_restore_portable.py`.
- Register rows G18, G19, G20 (ids decided at execution) in `docs/RESEARCH-AND-GATES.md`.

### Patterns to match
- Approval refusal before argument parsing, exit code 2, "No connection was attempted": `scripts/gates/g01_analytics_live.py:778-785`.
- Evidence directory confinement: `scripts/gates/_evidence_paths.py:20-32`.
- DR target safety (parsed hostnames, never substrings; `--target` and `--confirm-target`): `infra/dr/ns_dr_safety.py`.
- Contract kit with a deliberately broken implementation to prevent a vacuous pass: `tests/unit/connector_conformance/test_reference_connectors_conformance.py`.
- Drill with digests and timings: `infra/dr/ns_dr_drill.py`, evidence record `docs/evidence/G07/dr/`.

### Gotchas
- `tests/integration/dr/test_runbook_caveats.py` pins phrases in `dr-runbook.md`; append new sections, do not rewrite existing text.
- The architecture tests must not import the adapters they police; they parse source with the AST (no new dependency), as PRP-85 designed.
- The matrix generator must read evidence, not assert it: a `container` cell exists only if the marker and directory exist and the completion note of the owning PRP records a run. A cell can regress to `OPEN`; do not hand-edit generated pages.
- PostgreSQL backup through `pg_dump` is a tool dependency; prefer the export-by-table approach through the adapter (like the Cosmos exporter) so the DR tooling needs no extra binary. Verify at execution whether a managed-service snapshot mechanism can be exercised at all without an account (it cannot; write OPEN).
- Compose lane: the portable drill uses the per-backend compose fragments with their own project name; run it alone.
- Never put an account id, project id, bucket name or endpoint of a real environment in a script default, evidence template or doc; all come from `--target` style arguments the operator types.
- The words "supported", "certified", "authorized" and "production ready" are traps in generated text; use evidence-kind wording only.
- Units an earlier PRP descoped under its `## Cut line` (PRP-87 to PRP-91; Vertex under D-12 for PRP-95) appear as `disabled: <reason>` or `OPEN` cells, never as silent gaps; the port coverage test accepts them only with their recorded reason.
- Test package name clash: new test directories get unique names; `tests/architecture` is created by PRP-85 and shared, so add new files only.

Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - tests/architecture/**
  - infra/dr/**
  - tests/integration/dr/**
  - scripts/gates/multicloud_aws_live.py
  - scripts/gates/multicloud_gcp_live.py
  - scripts/gates/multicloud_onprem_live.py
  - scripts/gates/_multicloud_common.py
  - scripts/platform/**
  - tests/unit/multicloud_gates/**
  - docs/ops/rpo-rto.md
  - docs/ops/dr-runbook.md
  - docs/deploy/platform-matrix.md
  - docs/deploy/platform-disabled-features.md
  - docs/evidence/multicloud/**
  - docs/RESEARCH-AND-GATES.md
  - docs/security/threat-model.md
  - docs/compliance/ssp/scope.md
tier1: []
tier2_appends:
  - mkdocs.yml
must_not_touch:
  - packages/contracts/**
  - infra/helm/**
  - infra/terraform/**
  - infra/onprem/**
  - docker-compose.yml
  - Makefile
  - pyproject.toml
  - uv.lock
  - .github/workflows/**
  - services/api/neurosphere_api/runtime/**
  - services/workers/neurosphere_workers/runtime/factories.py
```

## Implementation blueprint

### Item 1 - Strict boundary and port coverage
- Deliverable: switch the PRP-85 boundary test from ratchet to strict (empty `KNOWN_LEAKS`, `ADAPTER_PATHS` as the named adapter allowlist); add the port coverage test (implementation or "disabled with a reason" per required port per platform; conformance module per implemented port); if a leak remains that a prior PRP did not clean, handle it per owner decision D-11 in PRP-85 (recommended: keep the `KNOWN_LEAKS` entry with the owning PRP named and a follow-up issue, report it), rather than editing product code here.
- Owned files: `tests/architecture/{test_strict_boundary,test_port_coverage}.py` and `tests/architecture/boundary.py` (edit only `KNOWN_LEAKS`, `LEAK_CEILING` and `ADAPTER_PATHS`); `tests/unit/multicloud_gates/test_boundary_fixtures.py`.
- Must NOT touch: product code under `packages/core`, `services/**` (a remaining leak is reported, not fixed here).
- Depends on: all earlier PRPs merged.
- Acceptance criteria: criteria 1 and 2.
- Tests: fixtures with a deliberately violating module and a port with a missing implementation prove both tests can fail.
- Pattern references: `tests/unit/connector_conformance/test_reference_connectors_conformance.py`.

### Item 2 - Matrix and disabled-features generators  [P]
- Deliverable: `scripts/platform/gen_matrix.py` building both pages from the inventory, conformance directories and markers, the capability matrix and the completion-note evidence flags; `--check` for drift; committed pages; a claims-vocabulary test.
- Owned files: `scripts/platform/**`, the two docs, `tests/unit/multicloud_gates/{test_matrix_generation,test_claims_vocabulary}.py`, `mkdocs.yml` (additive).
- Depends on: item 1 for the coverage data model.
- Acceptance criteria: criteria 3, 4 and 11.
- Tests: cell vocabulary closed set; a hand-edited page fails the drift check.

### Item 3 - DR tooling for PostgreSQL and object stores  [P]
- Deliverable: `ns_dr_postgres.py` and `ns_dr_objectstore.py` plugged into the `ns_dr.py` CLI, reusing `ns_dr_safety.py`; per-table export (JSON lines, system fields handled explicitly), restore with digests, object export with metadata; an emulator-class drill on the portable containers; `infra/dr/README.md` rows.
- Owned files: `infra/dr/**`, `tests/integration/dr/test_restore_portable.py`.
- Must NOT touch: Azure export code paths' behaviour.
- Depends on: PRP-89 and PRP-92 compose fragments exist; none on items 1 and 2.
- Acceptance criteria: criterion 5; existing DR tests pass unchanged.
- Tests: portable drill marked `portable` (skips with a reason without containers), target refusal cases for non-local PostgreSQL and bucket endpoints.
- Pattern references: `ns_dr_stores.py`, `ns_dr_drill.py`.

### Item 4 - RPO/RTO table and DR runbooks
- Deliverable: fill `docs/ops/rpo-rto.md` per target; add per-target sections to `docs/ops/dr-runbook.md` (steps written from provider documentation fetched at execution, each with URL and date, all "not exercised"); record the item 3 drill timings labelled "compose, not representative of production".
- Owned files: the two docs.
- Depends on: item 3.
- Acceptance criteria: criteria 6 and 7.
- Tests: `tests/integration/dr/test_runbook_caveats.py` unchanged and green; a new test asserts every target row says "target, unmeasured" unless an evidence file path is cited and exists.

### Item 5 - Live-gate scripts for AWS, GCP and on-prem  [P]
- Deliverable: the three scripts and the shared module (approval check first, confined evidence directory, lazy SDK imports, phases as named in criterion 9, evidence per phase, `OPEN` records, spend cap argument required for every phase that creates paid resources); a run-order note for the operator in each script header.
- Owned files: `scripts/gates/multicloud_*_live.py`, `scripts/gates/_multicloud_common.py`, `docs/evidence/multicloud/README.md`, `tests/unit/multicloud_gates/test_live_scripts_refuse.py`.
- Must NOT touch: existing G01 to G17 scripts.
- Depends on: PRP-96 and PRP-97 names for the install and apply phases.
- Acceptance criteria: criteria 8 and 9.
- Tests: refusal without the variable (no socket opened, patched socket guard), evidence dir traversal refused, no credential-shaped literal in the scripts.
- Pattern references: `g01_analytics_live.py:778-800`.

### Item 6 - Register, threat-model and SSP deltas
- Deliverable: register rows for the three platforms with the OPEN phases and handoffs; threat-model section for the new trust boundaries; SSP scope and family wording with the explicit "no authorization claim" statements.
- Owned files: `docs/RESEARCH-AND-GATES.md`, `docs/security/threat-model.md`, `docs/compliance/ssp/scope.md`.
- Depends on: items 2 and 5.
- Acceptance criteria: criteria 10 and 11.
- Tests: `python scripts/validate_planning.py` (register shape); docs tests.

### Item 7 - Integration and close-out
- Deliverable: rebase, Tier-3 regeneration, changelog fragment `changelog.d/PRP-98-conformance-matrix-dr-and-multicloud-live-gates.md`, completion note listing the final matrix state, the remaining violations (if any) with owning PRP, the OPEN phases, and the exact operator commands for each live script.
- Owned files: this PRP file, Tier-3 files per reference section 2.
- Depends on: items 1 to 6.
- Acceptance criteria: validation gates pass; CI green.

## Validation gates
```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q tests/architecture tests/unit/multicloud_gates tests/integration/dr tests/conformance tests/unit/capabilities tests/docs/test_nav_allowlist.py
python scripts/platform/gen_matrix.py --check
python scripts/prp_status.py --check
python scripts/validate_planning.py
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```
Local, opt-in, alone on the compose lane: `uv run pytest -q -m portable tests/integration/dr/test_restore_portable.py` with the PostgreSQL and object-store fragments up.

## Migration and rollback
No data or schema migration. The generated pages and scripts are additive; the strict boundary tests can only fail on a real leak. Rollback is reverting the PR; if the strict test blocks an urgent unrelated change, the allowlist entry (with the owning PRP named) is the documented escape, never a deletion of the test. DR tooling additions are inert unless invoked.

## Live and open gates
OPEN, operator-only, each needing `NS_LIVE_APPROVED=1`, an owner-approved spend cap and a cloud account or cluster the project does not have today: AWS (apply, RDS IAM auth, MSK auth, S3 conditional writes, Secrets Manager, Cognito, one Bedrock turn, EKS install, restore drill), GCP (apply, Cloud SQL IAM auth, Managed Kafka auth, GCS, Secret Manager, one Vertex turn, GKE install, restore drill, IdP choice), on-prem (real-cluster install, air-gapped install, restore drill, load at stated targets). Service gates are handed to PRP-64 and DR, load and sign-off to PRP-66. Until they run, every target is reported "conformance-tested on containers and recorded transports; live OPEN".

## NOT building
Measured RPO/RTO for any target; multi-region failover design; a managed-service snapshot orchestration; Pub/Sub, OpenSearch, ClickHouse; Government-class boundaries outside Azure; cross-cloud control of Azure resources; certification, compliance or availability statements; a CI job that applies infrastructure; fixes to leaks in product code owned by earlier PRPs.

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [ ] All clarification questions are decided, not guessed (D-1 and D-2 were decided by the owner 2026-11-16; rows 3, 9 and 10 are ASSUMPTIONS for plan approval; row 4 is owner decision D-11 in PRP-85)

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
- Date and PR:
- Deviations:
- Descoped items:
- OPEN gates:
- Env vars for the operator:
- Follow-up issue numbers:
- Product check (can an operator use it without editing files):
