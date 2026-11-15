---
name: PRP-23-ato-evidence-and-data-lifecycle
status: backlog
priority: P1
order: 23
review: required
created: 2026-10-08
model: sonnet
orchestrator_model: sonnet
implementer_model: sonnet
phase: 4
ns: NS-08
depends_on: []
wave: W12
branch: prp-23-round2-lifecycle-runtime
allow_parallel: true
absorbs: P4.5, G06
issues: [229, 119, 120]
---

# PRP-23: ATO evidence and data lifecycle (round 2)

## Goal
Make the shipped data lifecycle engine do real work behind an explicit safety switch, and finish the compliance documentation polish. Today the lifecycle worker role is registered but idle (`_lifecycle_job_source()` returns `None`) and its target registry is empty, there is no API to place a legal hold or request a job, no store has a delete, and a FAILED queue outcome is silently dropped. This PRP adds a Cosmos-backed job source and a lifecycle API (holds, requests, status), delete backends for the catalog, ledger and archive stores, retry of FAILED queued outcomes, a retention-policy file source, and a dry-run mode that is the default, so nothing is deleted until an operator sets execute mode. It also lands the #120 documentation and tooling polish and upgrades the CA-7, CP-2 and PM-5 control statuses (their documents now exist). It is for customer security teams and records officers; it is `review: required` because it deletes data. G06 stays OPEN: classification, payload opt-in, retention periods and the legal-hold process are customer inputs.

Out of scope: contracts and permission restructuring (PRP-37/PRP-65 owns `packages/contracts/**` and `permissions.py` restructuring); catalog repository internals beyond a new delete module (PRP-43); the compliance control library for NIST AI RMF, SR 11-7, HIPAA and OMB M-25-21 (PRP-56); scheduled expiry sweeps from policy rules (follow-up issue); a lifecycle UI (not planned); live Azure runs (none needed).

## Why
- The role runs nothing: `services/workers/neurosphere_workers/runtime/factories.py:698-705` `_lifecycle_job_source()` returns `None`, so `build_lifecycle` (`:714`) returns `IdleRole` (reason `lifecycle_no_job_source`, `:253`), and `_lifecycle_targets()` (`:708-711`) is an empty `TargetRegistry`.
- No delete exists in the stores: the engine calls `target.delete` (`packages/core/neurosphere_core/lifecycle/engine.py:414-437`) but the catalog, ledger and archive have no `DocumentBackend` (`lifecycle/adapters.py:31-53` defines the surface only). The durable stores are NOT missing: `CosmosMappingStore`, `CosmosHoldRegistry` and `CosmosRequestQueue` exist (`lifecycle/cosmos.py:132,186,240`), so #119 bullet 1 and the round-1 completion note are stale.
- `process_queue` drops FAILED outcomes: `engine.py:512-520` removes every outcome that is not `QUEUED`, including `FAILED`, so a transient store error loses the request after auditing it.
- No `neurosphere_api` module references the lifecycle package, so a hold or request cannot be created over HTTP; the control mapping marks AU-11 and SI-12 `planned` for that reason (`docs/compliance/ssp/control-mapping.yaml:186-190,605-609`).
- CA-7, CP-2 and PM-5 are `planned` with text saying the plan and inventory are "not yet in the repository" (`control-mapping.yaml:239-245,299-305,431-437`), but `docs/compliance/plans/*` and `scripts/compliance/collect_evidence.py` shipped, so the statuses are stale (lane-c).
- #120 review findings are authored from review and still open: negation exemption over the whole sentence in `scripts/compliance/check_statements.py`, leaf-only symlink check in `collect_evidence.py`, missing AC-5 and SC-18 evidence entries, no mermaid-diff test.

## Acceptance criteria
- [ ] Given dry-run mode (the default) and a due DELETE request, When the worker processes it, Then the target record still exists, the audit chain holds a before and after record whose detail is `dry_run:would_delete`, and the outcome carries `dry_run=true`, `effect=none` (test per action kind).
- [ ] Given execute mode, a DELETE on a catalog, ledger or archive record, When processed, Then the record is gone, a read-back confirms it, and the outcome is `completed/deleted`; a held record is still refused and audited; the audit container is still refused (backend tests per store plus the existing engine tests).
- [ ] Given a queued request whose first execution FAILED, When `process_queue` runs, Then it stays queued with an attempt count and `not_before` backoff and is retried until a configured maximum, after which it is audited as `failed_final` and removed (test with a flaky target).
- [ ] Given `POST /api/v1/lifecycle/requests`, When the caller lacks the lifecycle permission, Then 403; when it holds it, a job is persisted and 202 returns the request id, and `GET .../requests/{id}` shows pending, then the outcome after the worker ran (API test with in-memory stores).
- [ ] Given hold placement and release routes, Then both are audited with the server-derived identity, a caller-supplied customer or domain is ignored, and a held target blocks deletion end to end (API plus engine test).
- [ ] Given no retention policy file, Then the engine reports `policy_status=unset` and expiry deletes nothing; given a valid file, the policy is loaded; an invalid file fails closed to unset and is reported on the lifecycle status route.
- [ ] Given execute mode is not set, the status route and `/readyz` detail say the role is in dry-run; setting `NS_LIFECYCLE_MODE=execute` is the only way mutation happens (test).
- [ ] The #120 items pass: negation limited to the same clause with a regression test, resolved-path containment in `collect_evidence.py`, AC-5 and SC-18 evidence entries, a mermaid-vs-`diagrams/*.mmd` diff test, DR drill size wording aligned, the Chrome `executablePath` note moved to a contributor note.
- [ ] CA-7, CP-2 and PM-5 are `designed` or `implemented_tested` with evidence paths that exist; AU-11 and SI-12 change status only if the compose integration test passes (otherwise they stay `planned` with updated text); no entry says "compliant" or "authorized".
- [ ] PRP exit: touched suites pass, `verify-gates.ps1 -Mode full` green, the one independent review pass is approved, G06 and G02 recorded OPEN.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|---|---|---|
| 1 | Default mutation mode | Execute by default; dry-run by default | Dry-run by default (`NS_LIFECYCLE_MODE=dry_run`); `execute` is explicit. Jobs may also request dry-run individually; a job can only make the run safer, never override dry-run mode |
| 2 | Where requested jobs are stored | New container; reuse `lifecycle_requests` | ASSUMPTION: reuse the existing `lifecycle_requests` container with job documents marked `job_state`, because a new container is a Tier-1 stores edit owned by PRP-37/PRP-65 in W12; the queue's `pending()` query is changed to exclude job documents |
| 3 | Retention policy source | Cosmos admin store; settings; file | ASSUMPTION: a JSON file at `NS_LIFECYCLE_POLICY_FILE` loaded through `load_policy`; unset or invalid means unset and nothing expires. The admin-store source can replace it later through the same loader |
| 4 | New permission | Reuse `config.manage`; new `lifecycle.manage` | New `Permission.LIFECYCLE_MANAGE` (`lifecycle.manage`), granted to the admin role. PRP-37/PRP-65 (same wave) is adding lifecycle permissions to `permissions.py`; after rebase use its name if it exists, otherwise append this one (Tier 2) and say so in the completion note |
| 5 | FAILED retry policy | Retry forever; bounded | Bounded: `NS_LIFECYCLE_MAX_ATTEMPTS` (default 5) with exponential `not_before` backoff; then `failed_final`, audited and removed |
| 6 | Archive delete | Edit the archive writer; own backend module | Own backend in `lifecycle/archive_backend.py` over the blob container client; the PRP-07 archive writer is not edited |
| 7 | Conversation target | Build the shim here | Not built: the `ConversationBackend` shim over the API conversation store needs API-hosted wiring; filed as a follow-up. The worker registers catalog, ledger and archive only |
| 8 | Review and model | sonnet/none; sonnet/required | sonnet, review required, one pass; approve unless a blocking defect (wrong deletion, hold bypass, audit gap) |

## Context manifest

### Files to read first
- `packages/core/neurosphere_core/lifecycle/engine.py` - `submit`, `_decide`, `_run`, `_execute_*`, `process_queue` (lines 187-340, 373-520).
- `packages/core/neurosphere_core/lifecycle/{targets.py,adapters.py,models.py,policy.py}` - target protocols, `DocumentBackend`, enums, `load_policy`.
- `packages/core/neurosphere_core/lifecycle/cosmos.py` - the three Cosmos stores (pattern for the job store).
- `services/workers/neurosphere_workers/lifecycle/worker.py` - `LifecycleWorker`, `JobSource`, `RequestedJob`, `process_batch`.
- `services/workers/neurosphere_workers/runtime/factories.py:690-745` - the lifecycle builder bodies (W12 Tier-1, owned here).
- `packages/core/neurosphere_core/stores/containers.py:174-180` and `infra/compose/cosmos-containers.json` - lifecycle containers (read only).
- `packages/core/neurosphere_core/catalog/partitioning.py` and `catalog/repo/cosmos.py` - partition keys for the catalog delete module; `ledger/cosmos.py` (partition = customer id).
- `docs/compliance/ssp/control-mapping.yaml`, `scripts/compliance/{check_statements,collect_evidence}.py`, `tests/compliance/`.
- `docs/ops/dr-runbook.md` - the recovery path referenced in rollback.

### Interfaces consumed
- Audit chain: `neurosphere_core.audit.builders.AuditContext.from_scope`, `run_audited_mutation` (PRP-06, shipped).
- `Permission` and role mapping (`auth/scope/permissions.py`); lifecycle permission naming coordinated with PRP-37/PRP-65.
- Hold, queue and mapping Cosmos stores (PRP-23 round 1).

### Interfaces provided
- API: `POST/GET /api/v1/lifecycle/holds`, `DELETE /api/v1/lifecycle/holds/{hold_id}`, `POST/GET /api/v1/lifecycle/requests`, `GET /api/v1/lifecycle/requests/{request_id}`, `GET /api/v1/lifecycle/status` (policy state, mode, queue depth).
- Core: `lifecycle.jobs.CosmosJobStore`, `LifecycleOutcome.dry_run`, engine `mode`, `catalog/lifecycle_delete.py`, `ledger/lifecycle_delete.py`, `lifecycle/archive_backend.py`.
- Settings: `NS_LIFECYCLE_MODE`, `NS_LIFECYCLE_POLICY_FILE`, `NS_LIFECYCLE_MAX_ATTEMPTS`.

### Patterns to match
- Cosmos store shape and error mapping: `lifecycle/cosmos.py:132-300` (`from_client`, `_select`, `_raise_mapped`).
- Router per module with `require(...)` and server-derived scope: `services/api/neurosphere_api/federation/router.py`.
- Role builder returning `IdleRole` with a reason: `factories.py:714-728`.
- Compliance test style: `tests/compliance/test_statements.py`, `test_control_mapping.py`.

### Gotchas
- Real test directories are `services/workers/tests/lifecycle_worker/`, `packages/core/tests/lifecycle/`, `packages/core/tests/lifecycle_cosmos/` and `tests/integration/lifecycle/`; the round-1 gate listed a `lifecycle` worker directory that does not exist. The new API tests live in `services/api/tests/lifecycle_api/`.
- The audit container must stay unregistrable (`TargetRegistry.register` refuses it); never register `audit` or its chain as a target in any backend.
- Deletion is irreversible: only dry-run is reversible. Do not run execute mode against any shared or hosted store during development; tests use in-memory and emulator stores only.
- Do not edit existing files in `neurosphere_core/catalog/` or `ledger/` (PRP-43 and PRP-07 area); only the two new `lifecycle_delete.py` modules are added.
- Adding `LIFECYCLE_MANAGE` touches the Tier-2 inventories (`packages/core/tests/auth/scope/test_roles.py`, `tests/security/authz/test_privileged_roles.py`, `services/api/tests/authz/test_route_inventory.py`, `test_startup_route_check.py`); append lines only.
- `services/api/openapi.json` changes with the new routes (Tier 3): regenerate in the last commit.

Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership

```ownership
owns:
  - docs/compliance/**
  - scripts/compliance/**
  - tests/compliance/**
  - docs/evidence/inventory.md
  - docs/runbooks/lifecycle.md
  - docs/dev/diagram-rendering.md
  - packages/core/neurosphere_core/lifecycle/**
  - packages/core/tests/lifecycle/**
  - packages/core/tests/lifecycle_cosmos/**
  - packages/core/neurosphere_core/catalog/lifecycle_delete.py
  - packages/core/neurosphere_core/ledger/lifecycle_delete.py
  - services/workers/neurosphere_workers/lifecycle/**
  - services/workers/tests/lifecycle_worker/**
  - services/api/neurosphere_api/lifecycle/**
  - services/api/tests/lifecycle_api/**
  - tests/integration/lifecycle/**
tier1:
  - services/workers/neurosphere_workers/runtime/factories.py
tier2_appends:
  - services/api/neurosphere_api/routers.py
  - services/api/neurosphere_api/authz/routes.py
  - services/api/neurosphere_api/runtime/builders/__init__.py
  - services/api/neurosphere_api/runtime/settings.py
  - packages/core/neurosphere_core/auth/scope/permissions.py
  - services/api/tests/authz/test_route_inventory.py
  - services/api/tests/authz/test_startup_route_check.py
  - packages/core/tests/auth/scope/test_roles.py
  - tests/security/authz/test_privileged_roles.py
must_not_touch:
  - packages/contracts/**
  - packages/core/neurosphere_core/stores/containers.py
  - infra/compose/cosmos-containers.json
  - services/api/neurosphere_api/runtime/builders/data.py
  - docker-compose.yml
```

## Implementation blueprint

Items A, 1 and 2 are independent [P] (disjoint files). Item 3 waits for 1; item 4 waits for 1 and 2; item 5 closes out. `control-mapping.yaml` is edited by item A first and by item 5 last, never in parallel.

### Item A - Compliance docs and tooling polish (#120)  [P]
- Deliverable: clause-scoped negation in `check_statements.py` with a regression test ("authorized, unlike X which is not" must fail); `full.resolve()` containment under the repo root in `collect_evidence.py` with a symlinked-parent test; AC-5 evidence adds `hitl/policy.py`, SC-18 cites a specific chart-sandbox test; a test diffing each fenced mermaid block in `docs/compliance/plans/*.md` against `diagrams/*.mmd`; DR drill size wording aligned in `contingency-plan.md` and the G07 DR README reference; Chrome workaround moved to `docs/dev/diagram-rendering.md`; CA-7, CP-2 and PM-5 upgraded with real evidence paths; `docs/evidence/inventory.md` regenerated by the collector.
- Owned files: `docs/compliance/**`, `scripts/compliance/**`, `tests/compliance/**`, `docs/evidence/inventory.md`, `docs/dev/diagram-rendering.md` (new).
- Must NOT touch: `docs/evidence/G07/**`, `docs/RESEARCH-AND-GATES.md`, any product code.
- Depends on: none.
- Acceptance criteria: the #120 and CA-7/CP-2/PM-5 criteria; running the collector twice leaves `inventory.md` byte-identical.
- Tests: `tests/compliance/test_statements.py`, `tests/compliance/test_no_credential_collection.py`, `tests/compliance/test_inventory_idempotent.py`, `tests/compliance/test_control_mapping.py`, `tests/compliance/test_plan_diagrams_rendered.py`, `tests/compliance/test_plan_mermaid_matches_source.py` (new).
- Pattern references: `scripts/compliance/check_statements.py`, `tests/compliance/conftest.py`.

### Item 1 - Engine: dry-run, retry, policy file, job store  [P]
- Deliverable: engine `mode` (`dry_run` default | `execute`) and `LifecycleOutcome.dry_run`; in dry-run `_execute_delete`, `_execute_pseudonymize` and `_execute_erase` perform the decision, the existing-record read and a before/after audit with detail `dry_run:would_<effect>` but call no mutating target method; `process_queue` keeps FAILED items with `attempts`, `not_before` backoff and a maximum, then `failed_final`; `load_policy_file(path)` helper over `load_policy`; `CosmosJobStore` in `lifecycle/jobs.py` (submit with dedupe, get, list, claim after a checkpoint, record outcome) over the `lifecycle_requests` container using `job_state` documents; `CosmosRequestQueue.pending()` excludes job documents.
- Owned files: `packages/core/neurosphere_core/lifecycle/**` (except `archive_backend.py`, item 2), `packages/core/tests/lifecycle/**`, `packages/core/tests/lifecycle_cosmos/**`.
- Must NOT touch: `stores/containers.py`, `infra/compose/cosmos-containers.json`, contracts.
- Depends on: none.
- Acceptance criteria: dry-run, retry and policy criteria above; existing conflict-rule, audit-immutable and no-policy tests unchanged and green.
- Tests: `packages/core/tests/lifecycle/test_dry_run.py` (new), `packages/core/tests/lifecycle/test_retry_failed.py` (new), `packages/core/tests/lifecycle/test_policy_file.py` (new), `packages/core/tests/lifecycle_cosmos/test_job_store.py` (new), plus the existing files in both directories.
- Pattern references: `engine.py:373-440`, `lifecycle/cosmos.py:240-300`.

### Item 2 - Delete backends for catalog, ledger and archive  [P]
- Deliverable: `DocumentBackend` implementations: `catalog/lifecycle_delete.py` (entity and edge documents by id with the catalog partition rules, `read`, `remove`, `page`, `page_by_subject`, `redact_subject`, `project`), `ledger/lifecycle_delete.py` (cost-ledger entries, partition = customer id), `lifecycle/archive_backend.py` (blob container; blob names verified against `services/workers/neurosphere_workers/archive/` read only). Each wraps through the existing adapter classes in `adapters.py` and never accepts the audit container.
- Owned files: `packages/core/neurosphere_core/catalog/lifecycle_delete.py`, `packages/core/neurosphere_core/ledger/lifecycle_delete.py`, `packages/core/neurosphere_core/lifecycle/archive_backend.py`, tests beside them.
- Must NOT touch: existing modules in `catalog/` and `ledger/`, `neurosphere_workers/archive/**`.
- Depends on: none.
- Acceptance criteria: each backend deletes and then reads back absent against its in-memory or emulator store; a missing record is a no-op; the audit container is refused.
- Tests: `packages/core/tests/lifecycle/test_catalog_backend.py` (new), `packages/core/tests/lifecycle/test_ledger_backend.py` (new), `packages/core/tests/lifecycle/test_archive_backend.py` (new), `tests/integration/lifecycle/test_targets_compose.py` (emulator, integration marker).
- Pattern references: `lifecycle/adapters.py:31-120`, `ledger/cosmos.py:32-100`.

### Item 3 - Lifecycle API (holds, requests, status)
- Deliverable: `services/api/neurosphere_api/lifecycle/` router, models and dependencies; `LIFECYCLE_MANAGE` permission (see Clarification 4) appended in `permissions.py` unless PRP-37/PRP-65 already added it, granted to the admin role; routes listed under Interfaces provided; every write audited with `AuditContext.from_scope`; a builder is not required if the router reads stores from `app.state` set by a new `runtime/builders` helper registered as a Tier-2 line (state: job store, hold registry, queue, engine policy status); route allowlist and inventory lines; `openapi.json` regenerated last.
- Owned files: `services/api/neurosphere_api/lifecycle/**`, `services/api/tests/lifecycle_api/**`, Tier-2 lines in `routers.py`, `authz/routes.py`, `permissions.py` and the four inventories.
- Must NOT touch: `runtime/builders/data.py`, `authz/dependencies.py`, contracts.
- Depends on: item 1.
- Acceptance criteria: the API, hold and status criteria above; app boot refuses nothing (no undeclared route).
- Tests: `services/api/tests/lifecycle_api/test_requests_api.py` (new), `services/api/tests/lifecycle_api/test_holds_api.py` (new), `services/api/tests/lifecycle_api/test_status_api.py` (new), `services/api/tests/test_openapi_drift.py`.
- Pattern references: `federation/router.py`, `authz/dependencies.py:165-210`.

### Item 4 - Worker runtime wiring
- Deliverable: `_lifecycle_job_source` returns a Cosmos-backed `JobSource` (new `services/workers/neurosphere_workers/lifecycle/job_source.py` adapting `CosmosJobStore.claim` to `RequestedJob`); `_lifecycle_targets` registers catalog, ledger and archive targets from the new backends; `build_lifecycle` loads `NS_LIFECYCLE_POLICY_FILE`, sets mode from `NS_LIFECYCLE_MODE`, and passes an `on_outcome` sink that records the outcome on the job; the idle path remains when the Cosmos client is unavailable; mode is logged at startup and shown in the role status.
- Owned files: `services/workers/neurosphere_workers/lifecycle/**`, `services/workers/neurosphere_workers/runtime/factories.py` (`build_lifecycle`, `_lifecycle_job_source`, `_lifecycle_targets` bodies only), `services/workers/tests/lifecycle_worker/**`, `docs/runbooks/lifecycle.md` (new).
- Must NOT touch: other builder bodies in `factories.py`, `runtime/roles.py`, Helm.
- Depends on: items 1 and 2.
- Acceptance criteria: with a fake Cosmos and in-memory targets a submitted job runs to an outcome visible on the job; dry-run default leaves targets intact; `execute` mutates; role is `idle` with a reason when storage is not configured.
- Tests: `services/workers/tests/lifecycle_worker/test_job_verification.py`, `services/workers/tests/lifecycle_worker/test_runtime_wiring.py` (new), `services/workers/tests/lifecycle_worker/test_job_source.py` (new).
- Pattern references: `factories.py:714-745`, `worker.py:60-120`.

### Item 5 - Integration and close-out
- Deliverable: upgrade AU-11 and SI-12 in `control-mapping.yaml` only if the emulator integration test (`tests/integration/lifecycle`, local) passes, otherwise leave `planned` with updated narrative; regenerate `docs/evidence/inventory.md`; Tier 3 regeneration (`openapi.json`, `docs/reference/**`, status table, index); completion note with "Env vars for the operator" (`NS_LIFECYCLE_MODE`, `NS_LIFECYCLE_POLICY_FILE`, `NS_LIFECYCLE_MAX_ATTEMPTS`); one independent review pass; follow-up issues (conversation shim, expiry sweeps from policy, Helm role wiring check); link #132 lifecycle bullet to #119.
- Owned files: this PRP file; `docs/compliance/ssp/control-mapping.yaml`; `docs/evidence/inventory.md`.
- Must NOT touch: items 1-4 source except an integration defect (record it).
- Depends on: items A, 1-4.
- Acceptance criteria: statuses match what ran; completion note filled.

## Validation gates

```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q packages/core/tests/lifecycle packages/core/tests/lifecycle_cosmos services/workers/tests/lifecycle_worker services/api/tests/lifecycle_api services/api/tests/authz services/api/tests/test_openapi_drift.py packages/core/tests/auth/scope tests/security/authz tests/compliance
python scripts/compliance/collect_evidence.py
python scripts/compliance/check_statements.py
docker compose up -d --wait
uv run pytest -q -m integration tests/integration/lifecycle
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
python scripts/validate_planning.py
```

Run the collector twice and confirm `git diff --stat docs/evidence/inventory.md` is empty the second time.

## Migration and rollback
- Migration: none to existing data. Job documents are added to the existing `lifecycle_requests` container under a `job_state` marker; no container or schema change. New settings default to dry-run and unset policy.
- Dry-run: `NS_LIFECYCLE_MODE=dry_run` (default) runs every decision and audit step but mutates nothing; a job can also be submitted as dry-run through the API. Review the dry-run outcomes (`GET /api/v1/lifecycle/requests`) before switching to `execute`.
- Rollback and kill switch: set `NS_LIFECYCLE_MODE=dry_run` and restart (settings apply on restart, assumption A1) or remove `lifecycle` from `NS_WORKER_ROLES`; this stops all further mutation. Revert the PRP branch to remove the code.
- Deleted data cannot be restored by this PRP. Recovery is the store-level path in `docs/ops/dr-runbook.md` (Cosmos backup restore, blob soft delete where enabled), and a restore must be followed by replaying the lifecycle audit chain so erased subjects are not resurrected. State this in the runbook; the audit record of each deletion holds the record id and digest, never the body.
- Per-pass bound: the worker batch size (50) limits how many jobs run per fetch; a larger purge needs repeated requests, each audited.

## Live and open gates
- G06 (retention, classification, legal-hold process) and G02 stay OPEN: customer inputs, no guess. No live Azure item here; no `NS_LIVE_APPROVED=1` run is needed.
- Hosted Helm and Bicep wiring of the lifecycle role (values already list the role) is verified, not changed, and any gap is filed for PRP-58; live deletion against hosted stores is not run.

## NOT building
- A conversation target shim, scheduled expiry sweeps from policy rules, a lifecycle UI, a soft-delete or undo feature.
- New contracts, new Cosmos containers or Bicep changes (PRP-37/PRP-65 owns those).
- The extended compliance control library (PRP-56) or any compliance, authorization or certification claim.
- Edits to existing catalog or ledger repository code.

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [x] All clarification questions are decided, not guessed (rows 2 and 3 are labelled assumptions)

## Execution state

| Item | Status | Branch/worktree | Notes |
|------|--------|-----------------|-------|
| A | merged | prp-23-round2-lifecycle-runtime | #120 polish done, CA-7/CP-2/PM-5 designed |
| 1 | merged | prp-23-round2-lifecycle-runtime | dry-run, retry, policy file, job store |
| 2 | todo | | |
| 3 | todo | | |
| 4 | todo | | |
| 5 | todo | | |

## Completion note (filled at ship)
- Date, PR, merge commit:
- Deviations from the blueprint and why:
- Descoped items:
- OPEN gates (G06, G02):
- Env vars for the operator (`NS_LIFECYCLE_MODE`, `NS_LIFECYCLE_POLICY_FILE`, `NS_LIFECYCLE_MAX_ATTEMPTS`):
- Follow-up issue numbers:
- Product check (can an operator place a hold and request a dry-run deletion without raw API calls?):

## History
- Round 1 (PR #118, merged 2026-10-23) shipped the lifecycle engine with Cosmos hold, queue and mapping stores, the 64-control NIST mapping, the evidence inventory scripts, the compliance plans and rendered diagrams (items 1-4).
- The 2026-11-04 audit reopened it: engine inert at runtime, no lifecycle API, no retry for FAILED outcomes, "durable stores missing".
- The 2026-11-14 re-audit (lane-c) found the durable-stores claim stale (the Cosmos stores exist), the PRP-21 dependency not real (only `docs/evidence/G07/dr/` and the DR runbook are consumed, both present), and the gate path `services/workers/tests/lifecycle` wrong (real: `lifecycle_worker`).
- This rewrite removed the round-1 blueprint, the audit section and `depends_on`, added dry-run and rollback as mandatory, and folded #119 and #120 into items A and 1-5; #132's lifecycle bullet is linked to #119.
- The original text is in git history (`git log --follow PRPs/backlog/PRP-23-ato-evidence-and-data-lifecycle.md`).
