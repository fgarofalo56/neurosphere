---
name: PRP-55-real-deploy-apply
status: backlog
priority: P1
order: 45
review: required
created: 2026-11-14
model: opus
orchestrator_model: opus
implementer_model: sonnet
phase: 6
ns: NS-06, NS-07
depends_on: [PRP-54-write-targets-from-configuration]
wave: W18
branch: prp-55-real-deploy-apply
allow_parallel: true
issues: []
---

# PRP-55: Real deploy apply

## Goal
Make an approved NeuroSphere deployment plan actually provision through the durable action executor, end to end, when an operator opts in. PRP-08 round 2 shipped approve, apply and uninstall-preview routes, a deploy intent contract and a worker `DeployConnector`, but apply is not end to end: the approval store is in memory per API process, so the executor worker skips the connector (`deploy_sources_unconfigured`), and no ARM or Fabric provisioner is wired. This PRP adds a durable plan-approval store shared by API and worker, registers `DeployConnector` in the worker with real ARM and Fabric provisioners behind the existing capability gates, and proves approve, confirm, execute, verify-by-change and register write on the emulators with a fake ARM. Apply stays 503 unless `NS_DEPLOY_APPLY_ENABLED` is set; a live apply into a throwaway resource group is operator-gated and handed to PRP-64. For operators who deploy NeuroSphere's own data plane from the `/deploy` wizard.

Out of scope: write-target registry from stored configuration and multiple targets per kind (PRP-54); the plan route body-scan fallback (#36) and uninstall api-version table (#38) (PRP-59); live uninstall (#40) and the live apply run (PRP-64); hosted and Helm profile edits other than the worker deploy env (PRP-58 owns those files in W18); deploy wizard UI changes (no UI change is needed: the step already reflects real API state).

## Why
- `services/api/neurosphere_api/deploy/apply/approvals.py:1-13,179-235`: `PlanApprovalStore` is in memory, per process, capped at 1000 entries with eviction (`:42,208-220`).
- `services/api/neurosphere_api/deploy/apply/bootstrap.py:13-18,135-136`: the worker cannot read approvals, so the deploy connector is skipped; no provisioner is wired.
- `services/workers/neurosphere_workers/runtime/factories.py:682-689` passes `deploy=` with no sources; `register_deploy_target` (`factories.py:1500-1528`) skips with `deploy_sources_unconfigured` and builds `DeployConnector` without `fabric`, `observer` or `arm`.
- `services/workers/neurosphere_workers/actions/deploy.py:179-185,419-445,559-567`: `ArmProvisioner` is a protocol with no implementation; without one an `arm_resource` item is `capability_unavailable`. `FabricProvisioner` (`packages/core/neurosphere_core/deploy/fabric/provisioner.py:65`) has no real transport: `deploy/fabric/transport.py:1-7` says the bearer transport belongs to the API/worker layer and only a recording stub exists.
- PRP-08 completion note (`PRPs/shipped/PRP-08-deployment-intelligence-and-iac.md:338,361-363`): "Apply is NOT end-to-end"; follow-ups "durable `PlanApprovals` + wired provisioners", "test that a target whose customer differs from the connector-bound customer is refused". Lane-d step 3 and unit H2 repeat this.
- Already done, not repeated here: register optimistic concurrency (`packages/core/neurosphere_core/deploy/register/cosmos_store.py:63-81` uses `_etag` and raises `StaleVersionError`).

## Acceptance criteria
- [ ] Given a plan approved through `POST /api/v1/deploy/apply/...` in one process, When an executor worker in another process (separate store instances on the same Cosmos container) executes the confirmed `deploy_plan_apply` intent, Then it reads the same approval and proceeds; with no approval or a changed hash it refuses (`plan_not_approved` / hash mismatch) and nothing is provisioned.
- [ ] The approval store is durable: approve is create-only per `(customer_id, plan_id)`; a second approval with a different hash is `plan_id_conflict`; an expired approval reads as absent; no eviction; no secret or principal e-mail stored (approver pseudonym only).
- [ ] Given `NS_DEPLOY_APPLY_ENABLED=true` and the register container set on the worker, When the `actions` role starts, Then `deploy` is in the worker write-target registry; unset keeps today's behaviour (not registered, API 503 `apply_not_configured`).
- [ ] The ARM provisioner creates only allowlisted services (decision 2) with the `neurosphere:created-by` tag, reports `created=False` for an existing resource, polls long-running operations with a bounded timeout, and uses the deployment cloud's management host (`CloudProfile.management_url`), never another cloud's; any other service stays `capability_unavailable`.
- [ ] Fabric items run through `FabricProvisioner` over a real bearer transport only where `fabric_unavailable_reason` returns `None`; otherwise `capability_unavailable` with that reason, zero HTTP calls.
- [ ] Verify-by-change: success is reported only when `verify` reads each created resource back (ARM GET / Fabric observer); a missing resource after apply is a failed verify and the executor's rollback path runs.
- [ ] Register rows are written as `created` for new resources and `reused` for consented reuse; a target whose customer differs from the connector-bound customer is refused (test).
- [ ] An in-memory end-to-end test (unmarked, runs in CI) covers approve, confirm, execute, verify and register with a fake ARM transport; an `integration` test repeats it on the Cosmos emulator.
- [ ] `scripts/gates/deploy_apply_live.py` (new) refuses without `NS_LIVE_APPROVED=1` (exit non-zero, no Azure call) and documents the throwaway-resource-group run for PRP-64.
- PRP exit: with the opt-in set on API and workers, an approved plan provisions allowlisted resources through the action executor and the register and UI show the verified result; live evidence is OPEN until PRP-64 runs it.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| 1 | Where durable approvals live | New container keyed by customer; documents in `deploy_register` (partition `/deployment_id`) | New `deploy_plan_approvals` container, partition `/customer_id`: `PlanApprovals.get(customer_id, plan_id)` is a point read. Both Bicep modules load `infra/compose/cosmos-containers.json`, so only the registry and its export change. |
| 2 | Which ARM services the provisioner creates | All planner services; a small allowlist | ASSUMPTION: `storage`, `event_hubs`, `monitoring` (Log Analytics) only, matching types already pinned in `infra/scripts/uninstall.py:43-52`. `key_vault` (purge protection), `cosmos_db`, `ai_search`, `container_registry`, `api_management`, `model_endpoint`, hosting stay `capability_unavailable`; follow-up issue. |
| 3 | Resource group creation | Create it; require it to exist | ASSUMPTION: the target resource group must exist; apply refuses `resource_group_missing`. No RG create, no delete (uninstall stays dry-run). |
| 4 | Default enablement | On in profiles; opt-in | Opt-in, unchanged (`NS_DEPLOY_APPLY_ENABLED`); never enabled by default in compose, Helm or hosted. |
| 5 | Fabric in Government | Wire it; keep fail closed | Fail closed until #39 (Government Fabric token scope) is verified; the matrix gate decides. |

## Context manifest

### Files to read first
- `PRPs/reference/parallel-build-reference.md` - tiers, commands, traps, close-out.
- `PRPs/shipped/PRP-08-deployment-intelligence-and-iac.md` - items 12 and 14, completion note, audit gap closure section.
- `services/api/neurosphere_api/deploy/apply/approvals.py` - `ApprovalRecord`, `PlanApprovalStore.approve/record`, `derive_resources`.
- `services/api/neurosphere_api/deploy/apply/bootstrap.py` - opt-in wiring, `NS_DEPLOY_APPLY_REGISTER_CONTAINER`.
- `services/workers/neurosphere_workers/actions/deploy.py:151-230,419-670` - `PlanApprovals`, `ArmProvisioner`, `FabricObserver`, `DeployConnector`.
- `services/workers/neurosphere_workers/runtime/factories.py:640-690,1337-1370,1409,1500-1575` - actions role write targets, `DeployWriteSettings`, `_LazyCredential`, `register_deploy_target`.
- `packages/core/neurosphere_core/deploy/fabric/provisioner.py`, `transport.py` - Fabric adapter and transport seam.
- `packages/core/neurosphere_core/deploy/register/cosmos_store.py`, `scoped.py` - store and customer wrapper patterns.
- `packages/core/neurosphere_core/stores/containers.py:124-140` - `ContainerSpec` entries.

### Interfaces consumed
- From PRP-54 (names in its "Interfaces provided"): the write-target registry populated from stored configuration; `deploy` keeps registering through `register_write_targets` / `register_deploy_target`, and this PRP does not edit `runtime/builders/write_targets.py`.
- Existing: action executor (`services/workers/neurosphere_workers/actions/executor.py`), `deploy_plan_apply` contract (`packages/contracts/schemas/deployment/v1/deploy-action-plan.schema.json`), `CloudProfile.management_url` (`packages/core/neurosphere_core/cloud/profile.py:88`), `fabric_unavailable_reason` (`deploy.py:377`).

### Interfaces provided
- Container `deploy_plan_approvals` (partition `/customer_id`) and `neurosphere_core.deploy.approvals` (new): `PlanApprovalRepository` protocol, in-memory and Cosmos implementations.
- `neurosphere_workers.actions.deploy_http` (new): bearer `FabricHttp` and ARM HTTP transport; `deploy_arm` (new): `HttpArmProvisioner`.
- Worker setting `NS_DEPLOY_APPLY_REGISTER_CONTAINER` (same name as the API's) on `DeployWriteSettings`.
- `scripts/gates/deploy_apply_live.py` (new) for PRP-64.

### Patterns to match
- Cosmos store with ETag and `translating()`: `packages/core/neurosphere_core/deploy/register/cosmos_store.py:47-81`.
- Lazy credential through the lifetime: `factories.py:1409`, `1555`.
- Fabric long-running operation and retry-after handling: `deploy/fabric/provisioner.py:65,278-290`.
- Live-gate refusal: `infra/scripts/uninstall.py:38` (`NS_LIVE_APPROVED`), `scripts/gates/g01_deploy_smoke.py`.

### Gotchas
- `httpx` is not a dependency of `neurosphere-core` (`deploy/fabric/transport.py:1-7`): HTTP transports go in the workers package; core holds only the store, protocols and the service-to-ARM-type table.
- The API already imports `neurosphere_workers.actions.deploy` (`approvals.py:27`); keep the API on the dry-run path only and do not import the ARM transport into the API.
- Adding a container changes `infra/compose/cosmos-containers.json` (regenerate with `uv run python -m neurosphere_core.stores`, drift test `packages/core/tests/stores_registry/test_export_drift.py`); non-local boot checks every registry container exists, so hosted redeploy must precede enabling the image (note in the completion note for PRP-58/PRP-64).
- ARM create is asynchronous (201/202 with `Azure-AsyncOperation`); bound the poll and never log the subscription id (the repo is public: tokenise as G01 evidence does).
- CodeQL: no hostname substring checks without a leading dot; no PEP 695 generics in nested functions.
Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - services/workers/neurosphere_workers/actions/deploy*.py
  - packages/core/neurosphere_core/deploy/**
  - services/api/neurosphere_api/deploy/apply/**
  - tests/integration/deploy_apply/**
  - packages/core/tests/deploy_approvals/**
  - packages/core/tests/deploy_arm/**
  - services/workers/tests/deploy_apply_worker/**
  - services/api/tests/deployment/test_apply*.py
  - scripts/gates/deploy_apply_live.py
tier1:
  - packages/core/neurosphere_core/stores/containers.py
  - infra/compose/cosmos-containers.json
  - services/workers/neurosphere_workers/runtime/factories.py
tier2_appends:
  - services/workers/neurosphere_workers/runtime/settings.py
must_not_touch:
  - services/api/neurosphere_api/runtime/builders/write_targets.py
  - services/api/neurosphere_api/deploy/plan/**
  - services/api/neurosphere_api/deploy/scan/**
  - infra/scripts/uninstall.py
  - infra/demo/**
  - infra/helm/**
  - infra/appservice/**
  - docker-compose.yml
  - packages/contracts/**
  - frontend/**
```

## Implementation blueprint

### Item 1 - durable plan-approval store  [P]
- Deliverable: `neurosphere_core.deploy.approvals` with a record model (customer, plan id, hashes, deployment id, cloud, resources, approver pseudonym, approved/expires timestamps), protocol, in-memory and Cosmos stores (create-only, `plan_id_conflict` on a different hash, expiry on read); `ContainerSpec("deploy_plan_approvals", ("/customer_id",), ...)` and regenerated export.
- Owned files: `packages/core/neurosphere_core/deploy/approvals/**` (new), `packages/core/tests/deploy_approvals/**`, Tier-1 `containers.py`, `infra/compose/cosmos-containers.json`.
- Must NOT touch: `deploy/register/**` behaviour.
- Depends on: none.
- Acceptance criteria: criterion 2; stores-registry drift and value-free tests pass.
- Tests: `packages/core/tests/deploy_approvals/test_store.py`; re-run `packages/core/tests/stores_registry`.
- Pattern references: `deploy/register/cosmos_store.py:47-81`.

### Item 2 - API uses the durable store
- Deliverable: `PlanApprovalStore` delegates to the core repository (eviction removed); bootstrap builds the Cosmos repository when apply is enabled; dry-run path unchanged.
- Owned files: `services/api/neurosphere_api/deploy/apply/**`, `services/api/tests/deployment/test_apply*.py`.
- Depends on: item 1.
- Acceptance criteria: existing apply tests green; approvals survive a new store instance on the same container (test).
- Tests: `services/api/tests/deployment/test_apply.py`, `test_apply_bootstrap.py`.
- Pattern references: `approvals.py:179-240`, `bootstrap.py:100-136`.

### Item 3 - ARM and Fabric transports and ARM provisioner  [P]
- Deliverable: core service table (service key to provider type, api-version, minimal create body, tags) in `neurosphere_core.deploy.arm` (new); worker `actions/deploy_http.py` (bearer transport for ARM and Fabric, token scopes from the cloud profile and `FabricEndpoints.token_scope`) and `actions/deploy_arm.py` (`HttpArmProvisioner.ensure/exists`, LRO polling, `resource_group_missing`).
- Owned files: `packages/core/neurosphere_core/deploy/arm/**` (new), `packages/core/tests/deploy_arm/**`, `services/workers/neurosphere_workers/actions/deploy_http.py`, `deploy_arm.py`, `services/workers/tests/deploy_apply_worker/test_arm*.py`.
- Must NOT touch: `actions/deploy.py` connector logic, `executor.py`.
- Depends on: none.
- Acceptance criteria: criterion 4 with `httpx.MockTransport`; Government profile resolves Government hosts (test).
- Tests: `services/workers/tests/deploy_apply_worker/test_arm_provisioner.py`, `test_transport.py`; `packages/core/tests/deploy_arm/test_service_table.py`.
- Pattern references: `deploy/fabric/provisioner.py:65,278-290`.

### Item 4 - worker registers DeployConnector with provisioners
- Deliverable: `actions/deploy_approvals.py` (new) adapting the core repository to `PlanApprovals`; `DeployWriteSettings.register_container`; the actions role builds `DeploySources` (approvals, Cosmos register) and passes ARM, Fabric and observer (matrix-gated) into `DeployConnector`.
- Owned files: Tier-1 `factories.py` (`actions_role`, `DeployWriteSettings`, `register_deploy_target` bodies), `actions/deploy_approvals.py`, worker `runtime/settings.py` (append only if a field lands there), `services/workers/tests/deploy_apply_worker/test_wiring.py`.
- Must NOT touch: other role builders, `BUILDERS` order.
- Depends on: items 1, 3.
- Acceptance criteria: criteria 3 and 5; `services/workers/tests/action_executor/test_deploy_adapter.py` and `test_write_target_wiring.py` green.
- Tests: `services/workers/tests/deploy_apply_worker/test_wiring.py`.
- Pattern references: `factories.py:1500-1528,1555`.

### Item 5 - verify, register and customer binding
- Deliverable: `DeployConnector.verify` reads back through the ARM provisioner and Fabric observer; register rows for created and reused resources; refusal when the target customer differs from the bound customer.
- Owned files: `services/workers/neurosphere_workers/actions/deploy.py`, `services/workers/tests/deploy_apply_worker/test_verify_register.py`.
- Depends on: item 4.
- Acceptance criteria: criteria 6 and 7.
- Tests: `services/workers/tests/deploy_apply_worker/test_verify_register.py`; re-run `services/workers/tests/action_executor`.
- Pattern references: `deploy.py:559-670`.

### Item 6 - end-to-end proof and live runner
- Deliverable: unmarked in-memory end-to-end test (API approve to worker verify, fake ARM); `integration` emulator twin; `scripts/gates/deploy_apply_live.py` refusing without `NS_LIVE_APPROVED=1`.
- Owned files: `services/workers/tests/deploy_apply_worker/test_end_to_end.py`, `tests/integration/deploy_apply/**`, `scripts/gates/deploy_apply_live.py`.
- Depends on: items 2, 5.
- Acceptance criteria: criteria 1, 8, 9.
- Tests: the files above; `tests/integration/deploy_apply` run locally against emulators at `127.0.0.1` (stack holder in W18 is PRP-58: coordinate the slot).
- Pattern references: `tests/integration/actions/test_action_vertical_slice.py`, `scripts/gates/g01_deploy_smoke.py`.

### Item 7 - worker deploy env in Helm and App Service  [serial-after: PRP-58]
- Deliverable: Helm `deployApply` env and App Service settings also reach the workers (enabled flag and register container), still off by default; render tests.
- Owned files (after PRP-58 merges and this branch rebases): `infra/helm/templates/deployment.yaml`, `infra/helm/values.yaml`, `infra/appservice/main.bicep`, `tests/unit/infra/test_helm_render.py`.
- Depends on: item 4 and PRP-58 merged.
- Acceptance criteria: `helm template` shows the worker env only when `deployApply.enabled`; Bicep builds.
- Tests: `tests/unit/infra/test_helm_render.py`.
- Pattern references: `infra/helm/templates/deployment.yaml:92-99`.

### Item 8 - Integration and close-out
- Deliverable: Tier-3 regeneration (`openapi.json` if a model changed, `docs/reference/**`, status table, `PRPs/INDEX.md`), CHANGELOG entry; operator steps (enable flags, register container on workers, re-approve after upgrade) recorded in the completion note with a docs follow-up issue, because no runbook is owned here; completion note per reference section 6 including "Env vars for the operator" (`NS_DEPLOY_APPLY_REGISTER_CONTAINER` on workers).
- Owned files: this PRP file, Tier-3 outputs.
- Depends on: items 1-7.
- Acceptance criteria: validation gates green; product check recorded.
- Tests: `services/api/tests/test_openapi_drift.py`.
- Pattern references: reference section 6.

## Validation gates
```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run python -m neurosphere_core.stores --check
uv run pytest -q packages/core/tests/deploy_approvals packages/core/tests/deploy_arm packages/core/tests/deploy packages/core/tests/stores_registry services/workers/tests/deploy_apply_worker services/workers/tests/action_executor services/api/tests/deployment tests/unit/infra services/api/tests/test_openapi_drift.py
uv run pytest -q -m integration tests/integration/deploy_apply
python scripts/prp_status.py --check
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
python scripts/validate_planning.py
```
The `-m integration` line needs the compose emulators (`docker compose up -d --wait`) and the W18 stack slot; report it as local evidence, CI skips it.

## Migration and rollback
New container `deploy_plan_approvals`: created by the emulator bootstrap locally and by both Bicep modules from the registry export on the next infrastructure deploy; hosted must be redeployed before an image with this registry boots (non-local boot checks containers). In-flight in-memory approvals are lost on upgrade: operators re-approve (apply fails closed meanwhile). Turn off: unset `NS_DEPLOY_APPLY_ENABLED` on API and workers (routes 503, connector unregistered). Revert: PR revert; the container can stay empty or be dropped by the operator. Created Azure resources are recorded in the register and removed only by the uninstall tool under `NS_LIVE_APPROVED=1`.

## Live and open gates
- Live apply into a throwaway resource group (`scripts/gates/deploy_apply_live.py`, `NS_LIVE_APPROVED=1`, operator approval, spend row): handed to PRP-64, OPEN here.
- Live uninstall (#40), Government Fabric (#39), G01 Government and G02: OPEN, not touched.

## NOT building
- Resource group creation, real uninstall through the API, services outside the decision-2 allowlist, multiple write targets per kind (PRP-54), stored deploy settings, UI changes, `#36`/`#38` (PRP-59), hosted enablement (PRP-58).

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [ ] All clarification questions are decided, not guessed (rows 2 and 3 are assumptions to confirm at plan approval)

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
- Date and PR:
- Deviations:
- Descoped items:
- OPEN gates:
- Env vars for the operator:
- Follow-up issues:
- Product check:
