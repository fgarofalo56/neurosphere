---
name: PRP-54-write-targets-from-configuration
status: backlog
priority: P1
order: 41
review: required
created: 2026-11-14
model: sonnet
orchestrator_model: sonnet
implementer_model: sonnet
phase: 6
ns: NS-06, NS-09
depends_on: [PRP-45-system-status-first-run-and-feature-settings]
wave: W17
branch: prp-54-write-targets
allow_parallel: true
issues: [247, 132]
---

# PRP-54: Write targets from stored configuration, more than one per connector kind

## Goal
Make the write side turn on from configuration instead of from seven hand-set env vars that no profile sets. The `WriteTargetRegistry` in the API and in the executor worker is filled from the stored `write_targets` entries that PRP-45 validates and lists (one entry per Foundry account or APIM gateway, each bound to a domain), with the existing `NS_FOUNDRY_*` and `NS_APIM_*` env as the fallback. The registry learns to hold more than one connector of the same kind, selected by the intent's domain, which closes the PRP-35 limit "one Foundry account and one APIM gateway per deployment". Compose, Helm and the hosted Bicep gain an explicit opt-in so a profile can enable the stored targets, and an emulator-backed integration test proves the chain: draft, maker-checker approval, kill-switch check, apply, read-back verify. It is for the operator who today cannot register a write target without an env change and a restart, and for PRP-55, which builds the real deploy apply on the same registry. It runs in W17 on PRP-45 and holds the compose stack and the `planes.py`, `factories.py` and Helm Tier-1 files for the wave.

Out of scope: the settings API, schema and validation of the `write_targets` entries (PRP-45, "stored `write_targets` entries are validated and listed but not registered"); the console pages (PRP-53, PRP-57); the deploy connector, durable `PlanApprovals` and the ARM provisioner (PRP-55); role assignments that give the workload identity write access on a Foundry account or APIM (operator-owned, documented here, live-gated); any live write against Azure (PRP-64); connector SDK behaviour other than the additive registry change (PRP-50); `connector_config` roles (PRP-42).

## Why
- The registry is filled only from env: `runtime/builders/write_targets.py:112-150` (`configure_write_targets`) and the worker `register_write_targets` (`services/workers/neurosphere_workers/runtime/factories.py:1533-1572`) read `FoundryWriteSettings` and `ApimWriteSettings` (`runtime/settings.py:168-231`). Compose sets both flags `"false"` (`docker-compose.yml:168-169,230-231`), the Helm templates have no `NS_FOUNDRY_*` or `NS_APIM_*` at all, and neither Bicep profile sets them (lane-d step 3; `grep` of `infra/` is empty for both prefixes).
- One connector per manifest name: `WriteTargetRegistry` keys by `manifest.name` (`connectors/sdk-python/neurosphere_connector/write/write_registry.py:38`) and `_register` skips a second one as `write_target_duplicate` (`factories.py:1384-1400`); PRP-35 recorded "multiple APIM gateways in one registry" as a follow-up (`PRPs/shipped/PRP-35-runtime-composition.md:26,91`; #132).
- Resolution already carries a natural second key: `check_gateway_binding` asserts the gateway is registered in the intent's own domain (`services/workers/neurosphere_workers/actions/targets.py:93-125`) and the API planning view picks by target kind (`services/api/neurosphere_api/actions/dependencies.py:125-170`).
- Proof exists once: G05 on 2026-11-05 (`docs/evidence/G05/20261105T173214Z-foundry-swap-live.json`); the approvals path and read-back verify are tested with fakes only (`services/workers/tests/action_executor`), not against the composed emulator stack (lane-d step 3).
- Operators cannot see or change targets: "No UI or API to register a write target; it is env plus restart" (lane-d step 3; `docs/validation/lane4-identity-docs-operator-setup.md` row "Action write targets").

## Acceptance criteria
- [ ] Given stored `write_targets` entries (PRP-45) and `NS_WRITE_TARGETS_FROM_STORE=true`, When the API and the `actions` worker start, Then each enabled entry is built by the existing connector factories and registered; the registry holds two APIM connectors for two domains and the dry run of an intent in domain B reaches gateway B, never gateway A.
- [ ] Given `NS_WRITE_TARGETS_FROM_STORE` unset or false, or no stored entries, Then behaviour is exactly today's env path (`services/api/tests/runtime_planes/test_write_targets.py`, `services/workers/tests/action_executor/test_write_target_wiring.py` pass unchanged); with nothing configured the registry is empty and a dry run still reports "no write target".
- [ ] Given a stored entry that cannot be built (Government account, missing `deployments/write` permission, gateway not registered, gateway cloud differs, registration in another domain), Then it is skipped with a logged reason code from the existing set and never registered as advisory; the other entries still register.
- [ ] Given two enabled entries of the same connector in the SAME domain, Then startup keeps the first and logs `write_target_duplicate_domain` for the second (fail closed, no random pick); entries for domains that differ from the gateway registration's domain are `gateway_domain_mismatch`.
- [ ] `WriteTargetRegistry` keeps its existing API unchanged for single-target callers (`register(connector)`, `get(name)`, `supports(name, action)`, `names()`), and gains an additive `target_key` (the domain id): `register(connector, target_key=...)`, `get(name, target_key=...)`, `supports(name, action, target_key=...)`; `get(name)` with several keys and none given raises `capability_unavailable` reason `target_ambiguous`, never picks one.
- [ ] The executor resolves with `stored.domain_id` and the API `connector_for` takes the intent's domain; an intent whose domain has no registered target is advisory, exactly as an unregistered connector is today; the kill switch, maker-checker, `check_gateway_binding` and `check_action` run unchanged.
- [ ] Emulator proof (marked `integration`, local): with the compose Cosmos emulator and fake ARM seams (`WriteTargetSeams`), a `model_deployment_swap` and a `gateway_mode_change` run draft, approval by a different principal, recheck, apply and read-back verify, and the fake target's state changed; a self-approval, a disabled kill switch and a missing approval each stop the apply before the connector is called. No catalog metadata is edited to fake a swap.
- [ ] Profiles: compose passes `NS_WRITE_TARGETS_FROM_STORE` and the env fallback names to the api and workers (default off); the Helm chart gains `writeTargets.fromStore` and `writeTargets.{foundry,apim}` values rendered into the api and workers env only when set; `infra/demo/main.bicep` gains `writeTargetsFromStore` (default false) wired into the api and workers settings; `helm template` and `az bicep build` tests prove all three, and no profile defaults to on.
- [ ] No credential value in any new value, env or log: targets are subscription, resource group, account, region, gateway and domain ids; auth is the workload identity (A7); `.env.example` additions are listed in the completion note (agent-blocked).
- PRP exit: touched suites plus `tests/security/authz`, ruff, pyright, `validate_planning.py` pass; PR open with CI green including the `helm` job; live write gates reported OPEN.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| 1 | Second key for several targets of one kind | Gateway id; target canonical id; intent domain | The intent's domain id: it already gates APIM execution (`check_gateway_binding`), is present on every stored intent and every API draft, and needs no parsing of canonical ids. ASSUMPTION: one target per connector per domain; two in one domain is refused |
| 2 | Stored vs env precedence | Merge; stored wins | A1: when `NS_WRITE_TARGETS_FROM_STORE=true` and the snapshot has at least one entry, stored entries define the targets for that process and env is ignored; otherwise env (applies at startup, no hot reload) |
| 3 | Profile opt-in | Stored entries always honoured; explicit switch | Explicit `NS_WRITE_TARGETS_FROM_STORE` (default false) so a deployment never gains a write path from data alone; the kill switch and approvals remain the runtime gates |
| 4 | Registry API change | New registry type; additive keys | Additive keys on the SDK registry; PRP-50 (W16) has merged first, so rebase and re-run `connectors/sdk-python/tests/write` |
| 5 | Foundry accounts per domain | Many; one | ASSUMPTION: one Foundry account per domain; a model swap routes by the intent's domain. Multiple accounts in one domain would need the swap target to name an account, which the action contract does not carry (no change here) |
| 6 | Write permission on the target | Grant by IaC; operator | Operator-owned role assignment (`Cognitive Services` contributor-class role on the account, APIM contributor on the service), documented in the runbook and checked by the existing permission read, which yields the advisory connector on a shortfall; hosted role assignments for write are not added by this PRP |
| 7 | Key name of the stored setting | `write_target` (PRP-37/PRP-65 schema), `write_targets` (PRP-45 text) | Use the constant and the entry model PRP-45 ships (`SETTING_KEYS`, its snapshot accessor); do not hard-code a spelling |

## Context manifest

### Files to read first
- `PRPs/backlog/PRP-45-system-status-first-run-and-feature-settings.md` and its completion note - stored `write_targets` entry shape, `load_stored_settings`, how the snapshot is exposed to builders and to the worker.
- `services/api/neurosphere_api/runtime/builders/write_targets.py` - `configure_write_targets`, `_gateway_store`, `_records_for`, startup-hook registration.
- `services/workers/neurosphere_workers/runtime/factories.py:654-686,1313-1575` - `_action_write_targets`, `WriteTargetSources`, `WriteTargetSeams`, `_foundry_target`, `_apim_target`, `_register`, `register_write_targets`.
- `connectors/sdk-python/neurosphere_connector/write/write_registry.py` - the registry to extend.
- `packages/core/neurosphere_core/actions/targets.py` and `services/workers/neurosphere_workers/actions/targets.py` - `connector_name_for`, `resolve_write_targets`, `resolve_connector`, `check_gateway_binding`.
- `services/workers/neurosphere_workers/actions/executor.py:393-420` - `_resolve` with `stored.domain_id`.
- `services/api/neurosphere_api/actions/dependencies.py:114-300` - `_PlanningConnector`, `ActionPlane.connector_for`.
- `tests/integration/actions/{conftest,support,test_action_vertical_slice}.py` - emulator harness to extend.
- `infra/helm/values.yaml`, `infra/helm/templates/deployment.yaml:44-205`, `infra/demo/main.bicep:225-285` - env plumbing.

### Interfaces consumed
- PRP-45: the stored `write_targets` entries (validated, listed), `neurosphere_core.admin.runtime.load_stored_settings` snapshot, the `admin_system` component; PRP-37/PRP-65: `SystemSetting` write-target definitions, `CredentialReference` vocabulary (not used for values here), `admin_config` container.
- Shipped: `FoundryWriteSettings`, `ApimWriteSettings`, `WriteTargetSources`, `WriteTargetSeams`, `create_swap_connector`, `build_http_apim_gateway_connector`, `GatewayStore`, `check_gateway_binding`, `ActionService`, maker-checker `ReviewPolicy` for `maker_checker` (PRP-44 may have stored a policy; behaviour is policy-driven).
- PRP-50 (W16): the SDK write-verify changes in the same registry package.

### Interfaces provided
- SDK: `WriteTargetRegistry.register(connector, *, target_key=None)`, `get(name, *, target_key=None)`, `supports(name, action, *, target_key=None)`, `target_keys(name)`.
- Core `neurosphere_core.actions.targets`: `resolve_write_target(source, action_kind, target_kind=None, *, target_key=None)` and `resolve_write_targets(..., target_key=None)` (default behaviour unchanged).
- Worker: `register_write_targets(..., entries=...)`; `WriteTargetEntry` view type; reason codes `write_target_duplicate_domain`, `target_ambiguous`, `write_targets_store_unavailable`.
- API: `ActionPlane.connector_for(action_kind, domain_id=None)`; setting `NS_WRITE_TARGETS_FROM_STORE`.
- Helm values `writeTargets.*`; Bicep param `writeTargetsFromStore`; compose variables `NS_WRITE_TARGETS_FROM_STORE`, `NS_FOUNDRY_*`, `NS_APIM_*` passthrough.

### Patterns to match
- Per-target skip with a logged reason, never an advisory registration: `factories.py:1376-1400`.
- Startup-hook registration with fail-closed logging: `runtime/builders/write_targets.py:112-150`.
- Test seams instead of live ARM: `WriteTargetSeams` (`factories.py:1329-1336`), `services/workers/tests/action_executor/apim_support.py`.
- Helm optional env block: `infra/helm/templates/deployment.yaml:94-97` (`NS_DEPLOY_APPLY_*`); Bicep env as a conditional array: `infra/appservice/main.bicep:146`.
- Existing emulator action test: `tests/integration/actions/test_action_vertical_slice.py`.

### Gotchas
- The API only ever calls `dry_run` (`actions/dependencies.py`); apply, verify and rollback are the worker's. A registry change must keep the API's `_PlanningConnector` refusing everything but planning.
- `connector_for` has nine call sites (`actions/{approval,common,service}.py`, `catalog/{grant_publish,mcp_publish}.py`); each already holds a stored intent, a scope or a domain id. Pass the domain at every site; a site that cannot is a bug to report, not a reason to pass `None`.
- `get(name)` without a key must stay valid for the one-target case or every shipped single-target test breaks; ambiguity is an error only when several keys exist.
- Foundry and APIM factories do network reads (permissions, gateway registry): they run in startup hooks and in the async worker builder, never in a sync API builder.
- `planes.py` shares `_write_targets` with PRP-44's review-policy wiring from W15: rebase first.
- Do not name an env var that looks like a secret (`*_KEY`, `*_SECRET`, `*_TOKEN`); CodeQL flags logging such names.
- Compose is shared across worktrees (fixed project name): this PRP holds the stack for W17; run the integration suite once, with unique `NS_E2E_*` ports if a browser test is added later.
- `.env.example` cannot be edited by an agent: list new `NS_*` names in the completion note.
Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - services/api/neurosphere_api/runtime/builders/write_targets.py
  - packages/core/neurosphere_core/actions/targets.py
  - packages/core/tests/actions/test_targets_keyed.py
  - connectors/sdk-python/neurosphere_connector/write/write_registry.py
  - connectors/sdk-python/tests/write/test_registry_keyed.py
  - services/workers/neurosphere_workers/actions/targets.py
  - services/workers/neurosphere_workers/actions/executor.py
  - services/api/neurosphere_api/actions/dependencies.py
  - services/api/neurosphere_api/actions/approval.py
  - services/api/neurosphere_api/actions/common.py
  - services/api/neurosphere_api/actions/service.py
  - services/api/neurosphere_api/catalog/grant_publish.py
  - services/api/neurosphere_api/catalog/mcp_publish.py
  - services/api/tests/write_targets_runtime/**
  - services/workers/tests/write_targets_worker/**
  - tests/integration/actions/**
  - tests/unit/write_targets_profiles/**
  - docs/runbooks/write-targets.md
tier1:
  - docker-compose.yml
  - infra/helm/**
  - infra/demo/main.bicep
  - services/workers/neurosphere_workers/runtime/factories.py
  - services/api/neurosphere_api/runtime/planes.py
tier2_appends:
  - services/api/neurosphere_api/runtime/status.py
  - mkdocs.yml
must_not_touch:
  - packages/contracts/**
  - services/api/neurosphere_api/admin/**
  - packages/core/neurosphere_core/admin/**
  - services/workers/neurosphere_workers/actions/deploy*.py
  - packages/core/neurosphere_core/deploy/**
  - services/workers/neurosphere_workers/runtime/roles.py
  - infra/appservice/main.bicep
  - frontend/**
```

## Implementation blueprint

Parallelization: item 1 first (shared SDK and core). Items 2 and 3 [P] after it (worker tree and API tree). Item 4 [P] with 2 and 3 (infra tree only). Item 5 after 2, 3 and 4. Item 6 last.

### Item 1 - Keyed write-target registry and resolution  [serial-after: PRP-50]
- Deliverable: additive `target_key` on `WriteTargetRegistry` and the two `resolve_write_target(s)` helpers; `target_ambiguous` refusal; `target_keys(name)`; docstring and runbook text for the domain key.
- Owned files: `connectors/sdk-python/neurosphere_connector/write/write_registry.py`, `connectors/sdk-python/tests/write/test_registry_keyed.py`, `packages/core/neurosphere_core/actions/targets.py`, `packages/core/tests/actions/test_targets_keyed.py`.
- Must NOT touch: connector manifests, `write_protocol.py`.
- Depends on: PRP-50 merged (same package).
- Acceptance criteria: criterion 5; existing registry and targets tests pass unchanged; `names()` still lists each manifest name once; `_check_capable` refusals unchanged.
- Tests: `connectors/sdk-python/tests/write`, `packages/core/tests/actions`, `tests/unit/connector_conformance`.
- Pattern references: `write_registry.py:38-54`, `actions/targets.py:100-140`.

### Item 2 - Worker: registration from stored entries and domain-keyed resolution  [P]
- Deliverable: `register_write_targets` builds one connector per stored entry (Foundry or APIM, per domain) with the existing target builders and `_register(..., target_key=domain)`; stored entries read through PRP-45's sync snapshot reader inside `_action_write_targets`, env fallback otherwise; `resolve_connector` and the executor `_resolve` pass `stored.domain_id`; duplicate-domain and ambiguity reasons.
- Owned files: `services/workers/neurosphere_workers/actions/{targets,executor}.py` (resolution call sites only), Tier-1 `factories.py` (`register_write_targets`, `_register`, `_action_write_targets` and the new entry type only), `services/workers/tests/write_targets_worker/**`.
- Must NOT touch: `register_deploy_target`, `DeployConnector`, other role builders, `BUILDERS`.
- Depends on: item 1 and PRP-45 merged.
- Acceptance criteria: criteria 1 to 4 on the worker side with fake ARM seams: two gateways, two domains, the right one chosen; a skipped entry does not stop the rest; `services/workers/tests/action_executor` passes unchanged.
- Tests: `services/workers/tests/write_targets_worker`, `services/workers/tests/action_executor`, `services/workers/tests/worker_roles`.
- Pattern references: `factories.py:1376-1572`, `executor.py:393-420`.

### Item 3 - API: configure_write_targets from stored entries and domain-aware planning  [P]
- Deliverable: `configure_write_targets` reads the stored entries (snapshot accessor from PRP-45) in its startup hook; `ActionPlane.connector_for(action_kind, domain_id=None)` and `_PlanningConnector` select by domain; all nine call sites pass the domain; `planes.py` `_write_targets` unchanged except the new switch plumbing.
- Owned files: `runtime/builders/write_targets.py`, `actions/{dependencies,approval,common,service}.py`, `catalog/{grant_publish,mcp_publish}.py` (the `connector_for` call lines only), Tier-1 `runtime/planes.py`, `services/api/tests/write_targets_runtime/**`.
- Must NOT touch: `admin/**`, `authz/**`, route signatures, `openapi.json` shape (a response change here is a bug).
- Depends on: item 1 and PRP-45 merged.
- Acceptance criteria: criteria 1 to 4 and 6 on the API side; a draft in a domain with no target is advisory; dry run in domain B plans against gateway B; `services/api/tests/{runtime_planes,actions_api,gateway_api,catalog_api}` pass unchanged.
- Tests: `services/api/tests/write_targets_runtime`, `services/api/tests/runtime_planes`, `actions_api`, `gateway_api`, `catalog_api`.
- Pattern references: `runtime/builders/write_targets.py:112-150`, `actions/dependencies.py:125-170,260-275`.

### Item 4 - Profile wiring: compose, Helm, hosted Bicep  [P]
- Deliverable: compose api and workers env (`NS_WRITE_TARGETS_FROM_STORE` and the fallback names, default off); Helm `writeTargets` values and conditional env in `deployment.yaml` (also the missing `NS_FOUNDRY_*` and `NS_APIM_*` fallback names); `writeTargetsFromStore` parameter in `infra/demo/main.bicep` applied to the api and workers settings; a runbook section on enabling, the operator role assignments and the kill switch.
- Owned files: `docker-compose.yml`, `infra/helm/values.yaml`, `infra/helm/templates/deployment.yaml`, `infra/demo/main.bicep`, `tests/unit/write_targets_profiles/**`, `docs/runbooks/write-targets.md`.
- Must NOT touch: `infra/appservice/main.bicep` (the demo template passes settings through its `apiAppSettings` and `workersAppSettings`), `infra/demo/modules/**`, `.env.example`.
- Depends on: none.
- Acceptance criteria: criterion 8; `helm template` renders the new env only when set and nothing otherwise; `az bicep build infra/demo/main.bicep` passes; a test asserts no profile defaults to on and no new value matches the secret-name pattern.
- Tests: `tests/unit/write_targets_profiles` (helm render and bicep build tests follow `tests/unit/infra/test_helm_render.py` and `test_bicep_build.py`, skipped only when the tool is absent locally; CI has both).
- Pattern references: `deployment.yaml:94-97`, `infra/appservice/main.bicep:146`, `docker-compose.yml:168-169`.

### Item 5 - Emulator proof of approvals and verify-by-change
- Deliverable: integration tests under `tests/integration/actions/` that compose the real intent store, executor worker and registry (two domains, fake ARM and Foundry seams that mutate observable state) against the Cosmos emulator: approval by a second principal, kill switch, self-approval refusal, read-back verify matching, a failed verify triggering rollback; evidence note in `docs/runbooks/write-targets.md` of what was and was not proven.
- Owned files: `tests/integration/actions/test_write_targets_from_store.py`, `tests/integration/actions/support.py` (additive helpers), `docs/runbooks/write-targets.md`.
- Must NOT touch: executor, connector or registry code (bugs found go back to items 1 to 3).
- Depends on: items 2, 3 and 4.
- Acceptance criteria: criterion 7; every refusal asserts the connector was never called; run with `127.0.0.1` emulator endpoints; marked `integration` (skipped by the CI python job; run locally and recorded).
- Tests: `tests/integration/actions`.
- Pattern references: `tests/integration/actions/test_action_vertical_slice.py`, `services/workers/tests/action_executor/executor_support.py`.

### Item 6 - Integration and close-out
- Deliverable: Tier-2 lines (`status.py` only if the component set changed), rebase, regenerate Tier-3 files (`openapi.json` drift check, `docs/reference/**`, status table, `PRPs/INDEX.md`), CHANGELOG entry, completion note with env vars (`NS_WRITE_TARGETS_FROM_STORE`, Helm and Bicep names), #132 commented with the exact bullets closed (write connectors, more than one target) and the ones left (lifecycle `TargetRegistry` is PRP-23, judge and copilot rows are PRP-45 and PRP-16), and the product check (can an admin enable a second APIM gateway without editing env?).
- Owned files: this PRP file, Tier-3 files per reference section 2.
- Depends on: items 1-5.
- Acceptance criteria: validation gates pass; CI green including `helm`; live items listed OPEN.

## Cut line
If context runs low, stop after Item 3 and run Item 6 (close-out) on what exists. Items 1 to 3 are a closed unit: the keyed registry (additive, `get(name)` unchanged for one target), the worker registration and the API planning path with all nine `connector_for` call sites passing the domain. It merges safely on its own because `NS_WRITE_TARGETS_FROM_STORE` defaults to off, so behaviour stays today's env path until someone sets it by hand; there is no registry that is filled but never read. Never stop inside Item 3 (a partial set of `connector_for` call sites is the half-wired state to avoid) and never run Item 5 without Items 2 to 4.

Recorded as unmet in the completion note: criterion 7 (emulator proof of approvals and read-back verify, Item 5) and criterion 8 (compose, Helm and Bicep opt-in, Item 4). Criteria 1 to 6 and 9 must hold at the cut. The remainder (Items 4 and 5) is filed as a follow-up issue linked to this PRP's tracking issue (#247), listing the unmet criteria verbatim; Items 4 and 5 are marked `descoped` in the Execution state with that issue number.

## Validation gates
```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q connectors/sdk-python/tests/write packages/core/tests/actions services/api/tests/write_targets_runtime services/api/tests/runtime_planes services/api/tests/actions_api services/api/tests/gateway_api services/api/tests/catalog_api services/workers/tests/write_targets_worker services/workers/tests/action_executor services/workers/tests/worker_roles tests/unit/write_targets_profiles tests/unit/connector_conformance tests/unit/infra services/api/tests/test_openapi_drift.py
python scripts/prp_status.py --check
python scripts/validate_planning.py
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```
Emulator suite (local, one session holds the stack): `docker compose up -d --wait` then `uv run pytest -q -m integration tests/integration/actions tests/integration/real_stack/test_planes.py`.

## Migration and rollback
No data migration. The registry change is additive and defaults to today's behaviour; stored entries are PRP-45 documents. Turn off: unset `NS_WRITE_TARGETS_FROM_STORE` (env fallback applies, or an empty registry) and restart; the kill switch (`PUT /api/v1/actions/emergency-disable`) stops execution without a restart. Revert: `git revert` the PR; helm and bicep additions are conditional and inert when off.

## Live and open gates
OPEN, not run: any live Foundry or APIM write from a stored entry (needs `NS_LIVE_APPROVED=1`, a Limitlessdata target and the operator's role assignments); a hosted profile with the switch on; a second live gateway. Handed to PRP-64 (G05 targets, G17 manage). Government stays advisory by design (G02 and G17 Government rows OPEN).

## NOT building
The settings API or UI for entries; the deploy connector and apply (PRP-55); role assignments for write access; auto-discovery of targets; several targets of one kind inside one domain; hot reload; any change to the maker-checker, kill switch or recheck logic; catalog metadata edits that imitate a swap.

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [ ] All clarification questions are decided, not guessed (rows 1 and 5 are ASSUMPTIONS for plan approval; PRP-45's snapshot accessor name is unverified until it ships)

## Execution state
| Item | Status | Branch/worktree | Notes |
|---|---|---|---|
| 1 | merged | prp-54-write-targets | keyed registry + resolve helpers (PRP-50 shipped) |
| 2 | merged | prp-54-write-targets | worker registration + domain-keyed resolve; Foundry entries carry no domain (key None) and need NS_FOUNDRY_LOCATION |
| 3 | merged | prp-54-write-targets | configure_write_targets reads stored snapshot; connector_for(kind, domain) at 9 sites (deploy router unkeyed by design) |
| 4 | todo | | |
| 5 | todo | | |
| 6 | todo | | |

## Completion note (filled at ship)
- Date and PR:
- Deviations:
- Descoped items:
- OPEN gates:
- Env vars for the operator:
- Follow-up issues:
- Product check (can an operator use it without editing files):
