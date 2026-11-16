---
name: PRP-108-agent-approval-gate-and-platform-control-actions
status: backlog
priority: P0
order: 108
review: required
created: 2026-11-16
model: opus
orchestrator_model: opus
implementer_model: opus
phase: 9
ns: NS-02, NS-04, NS-06, NS-08
depends_on: [PRP-99-governance-contracts-a, PRP-105-policy-engine-core, PRP-103-interaction-capture-policy-and-edge]
wave: W23
branch: prp-108-platform-control
allow_parallel: true
issues: []
---

# PRP-108: Agent approval gate and platform-control actions (the fix goes through approval)

## Goal
Make every governance change inside NeuroSphere itself an executed, approved, verified action. This PRP adds the `platform-control` write target: a write connector for NeuroSphere's own governed state with dry run, apply, verify by read-back and rollback, registered in the same `WriteTargetRegistry` as the Foundry and APIM connectors so the one executor runs it for button, chat, REST and MCP alike. It executes five action kinds with approval required and self-approval prohibited: `agent_version_approve`, `agent_version_suspend`, `capture_policy_change`, `governance_policy_publish` and `enforcement_mode_change`. On top of it ships the agent registration approval gate: a draft AgentVersion is submitted, checked against the published registration rules, approved through maker-checker, activated, and verified by reading the stored state back; the agent page shows the panel. UI and audit label these as "NeuroSphere state change", never as a change to an external system. It is for stewards and approvers, for the owner's "the fix goes through approval" (design section 2.4, binding), and for PRP-109's north-star chain. It runs in W23 after PRP-105 (lifecycle and binding functions) and PRP-103 (capture policy store).

Out of scope: external effects (a gateway change stays an APIM kind: `grant_unpublish`, `gateway_policy_apply` from PRP-112); the policy and violation UI (PRP-106); capture policy authoring UI (PRP-103); the CI registration check API (PRP-129); copilot and MCP draft tools for governance kinds (PRP-116); identity run-as fields on the registration form (PRP-118); PRP-76's registration-form and version-history work (W24, edits `catalog/router.py`, `catalog/service.py`, `EntityForm.tsx`).

## Why
- The executor executes only kinds in `ACTION_CONNECTORS` (`packages/core/neurosphere_core/actions/targets.py:59-72`); anything else is advisory and "nothing is changed anywhere to stand in for the change" (`:3-7`). No row exists for any NeuroSphere-internal change, so publishing a policy, enabling capture or approving an agent has no executable path.
- `register_write_targets` registers only names in `SUPPORTED_WRITE_CONNECTORS = frozenset(ACTION_CONNECTORS.values())` (`services/workers/neurosphere_workers/runtime/factories.py:1431`, `_register` `:1578-1610`, `register_write_targets` `:1813-1864`); the API dry-runs through the same function (`services/api/neurosphere_api/runtime/builders/write_targets.py:1-8`, called from `planes.py:204`).
- AgentVersion has `lifecycle_status` draft/active/deprecated/retired and the only built transition is deprecate (`packages/contracts/schemas/catalog/v1/common.schema.json:58-66`; `catalog/protocol.py:214-232` update and deprecate); there is no approval or registration gate (design G-f).
- Self-approval is forbidden by default for maker-checker (`hitl/policy.py:64-66`) but a stored review policy can override it per `(kind, action_kind)` (`admin/platform/review_policy.py:214-221`; contract field `self_approval_forbidden` is a plain boolean, `admin/v1/review-policy-document.schema.json:77`), so "self-approval prohibited" for governance kinds is not guaranteed today.
- `docs/PRD.md:31`: "The same action API serves copilot, recommendation buttons, REST and MCP ... unsupported actions are advisory, not catalog-only pretend changes." `:23` requires prohibiting self-approval where configured. Owner direction 2026-11-16: the governance fix goes through approval.

## Acceptance criteria
- [ ] Given each of the five kinds, When an intent is drafted against a target of the matching `entity_type` (`agent_version` with its catalog id; `capture_policy`, `governance_policy`, `enforcement_binding` with ids `<cloud>:<customer>:neurosphere:<entity_type>:<id>`, the PRP-99 convention), Then validation finds the `platform-control` connector (not advisory), confirmation is bound to target, version, diff, expiry and actor (`actions/hashing.py:45-51`), and the intent goes to `awaiting_approval` (all five in `DEFAULT_ACTION_KINDS` with `requires_approval=True`).
- [ ] Given the maker tries to approve their own intent, Then it is refused `self_approval_forbidden`, also when the stored review policy document sets `self_approval_forbidden: false` for `maker_checker` or for one of these kinds (the pin wins; a stored override that tries is logged with reason `self_approval_pinned`).
- [ ] Given an approved `governance_policy_publish` intent, When the executor runs it, Then dry run recomputes against the current definition ETag (stale is `stale_version`), apply calls PRP-105 `PolicyLifecycle.publish`, verify reads the definition and the catalog `Policy` projection back and matches only when both show the published version, and rollback restores the prior published version (or draft) with its bindings' modes.
- [ ] Given `enforcement_mode_change` to `enforce` on a binding whose point cannot block in this deployment (PRP-105 `ENFORCEMENT_POINT_CAPABILITIES`, for example `gateway` in Government or `evaluator`), Then dry run refuses with `point_cannot_enforce`; nothing is written.
- [ ] Given `capture_policy_change` drafted through `POST /api/v1/actions/domains/{domain}/intents` with a diff in the grammar this PRP defines (stage `propose`, `activate`, `suspend` or `retire`, the full `CapturePolicy` body for `propose`), Then apply goes only through PRP-103's `apply_capture_policy_change` with the approval's audit id, verify uses `read_back_capture_policy`, an activation without approval is impossible (the policy's `approved_intent_id`/`approved_audit_id` come from the executed intent), and the audit records carry the policy id, version and scope, never any content or detector match.
- [ ] Registration gate: Given a draft AgentVersion, When a caller with `action.propose` submits it, Then the server runs PRP-105 `decide` for the `registration_required`, `required_owner` and `required_approval` rules and records the results as the intent's `prerequisite_results`, drafts `agent_version_approve`, and the entity is not written; after approval and execution the entity has `approval.state = approved` with `decided_at`, `audit_id`, `policy_version`, and `lifecycle_status` `active` if it was `draft`; verify reads both back. `agent_version_suspend` sets `approval.state = suspended` and leaves lifecycle unchanged; rollback restores the prior approval block. A suspend request carrying `evidence` (for example a violation canonical id) yields an intent whose `evidence` contains those ids unchanged.
- [ ] `agent_version_approve` drafted through the REST route, through `ActionApi.draft` as the copilot does, and through the MCP `draft_action` tool (`services/api/neurosphere_api/mcp/server/tools.py:373-397`) reaches the same intent store and executor; a test drafts one per channel and asserts one code path. The other kinds are drafted through REST and the UI (see Gotchas) and run through the same executor.
- [ ] Given a `registration` binding of a `required_approval` rule with `block_activation`, Then the approval panel and `RegistrationCheck` report it with its mode; in `audit` the check result is shown and recorded, in `enforce` the submit route refuses to draft an approval while a blocking rule fails (`registration_blocked`). Other activation paths are not gated here (see Gotchas).
- [ ] Every audit record, intent view and UI string for these kinds names the effect "NeuroSphere state change" (`effect: neurosphere_state` in the dry-run result evidence); none says or implies an external system changed.
- [ ] Works in Commercial and Government (internal state, no external call); never crosses cloud: a target whose canonical id cloud differs from the deployment cloud is refused `cloud_boundary_mismatch`.
- [ ] ABAC: submit and suspend routes deny no role, viewer, wrong domain, wrong customer, expired assignment; the executor's worker writes under its own derived scope (needs `catalog.curate` in the agent's domain), never a bypass.
- PRP exit: touched suites, `tests/security/authz`, frontend lint/typecheck/test, ruff, pyright, `validate_planning.py` pass; PR open, CI green.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| 1 | Where the write target lives | In core; split | Split. Core never imports `neurosphere_connector` (`actions/targets.py:15-18`), so pure handlers live in `neurosphere_core.actions.platform_control` and the `WriteConnector` adapter with its manifest lives in `neurosphere_workers.actions.platform_control` (correction to the design's single core path) |
| 2 | Is writing NeuroSphere state a "pretend" change | Yes; no | No, by design 2.4: the governed state is the target; it is labelled as such and never stands in for an external change |
| 3 | Approval for these kinds | Configurable; required | Required, self-approval pinned off regardless of stored review policy |
| 4 | Capture default and who approves a `capture_policy_change` | (a) a second steward approves; (b) the maker-checker approver rule is relaxed for the governance action kinds so an admin approves | Decided by the owner 2026-11-16 (GD-1): capture is off everywhere and turned on per domain and source only by an approved `capture_policy_change`, proposed by a domain steward and never self-approved. Core requires a maker-checker approver to hold `action.approve` (`packages/core/neurosphere_core/admin/platform/review_policy.py:88-93`), which admin does not hold; decided: a second steward approves; no change to who holds `action.approve`; admins do not approve these (option (b), relaxing the approver rule so an admin approves, was not chosen). Here: no approver-permission override is built; the `config.manage` and `govpolicy.manage` values PRP-99 added to `approver_permission` stay unused |
| 9 | Who approves each kind | Several | Decided by the owner 2026-11-16 (GD-20): every governance action kind (`agent_version_approve`, `agent_version_suspend`, `capture_policy_change`, `governance_policy_publish`, `enforcement_mode_change`) is approved by a second person holding `action.approve` in the target's domain (a domain steward), never the maker; no built-in approver-permission override is shipped (GD-1 chose a second steward). Here: the shipped maker-checker rule applies unchanged; this PRP only pins `self_approval_forbidden` for the five kinds (a stored document may change nothing else for them) |
| 10 | Capture policy storage | `admin_config` kind; PRP-102 container | Capture policies are NOT an `admin_kind`: they live in PRP-102's container `interaction_capture_policies` (PRP-99 clarification 3, PRP-102 clarification 5); the `capture_policy_change` handler reads and writes them only through PRP-103's `CapturePolicyStore`, `apply_capture_policy_change` and `read_back_capture_policy` |
| 5 | Pending and rejected approval state | Write to the entity; derive from the intent | ASSUMPTION: the entity's `approval.state` changes only by executed intents (`approved`, `suspended`); `pending` and `rejected` are shown from the open or declined intent, so no write bypasses the executor |
| 6 | Enforcement default | `audit`; per kind | Decided by the owner 2026-11-16 (GD-7): `audit` for every policy and point; `enforce` only by an approved action, per point. Here: bindings start `audit`; `enforce` only through this PRP's approved `enforcement_mode_change` |
| 7 | Capture policy store | Wait for PRP-103; define here | PRP-103 (W22) provides it; dependency added (the design lists 99 and 105 only; PRP-103's own entry says its kind is "executed once PRP-108 lands") |
| 8 | Worker composition file | Not needed; Tier-1 | `runtime/factories.py` (`register_write_targets`, `build_actions`) is Tier-1 worker composition; no other W23 PRP holds it (PRP-107 held it in W22), so this PRP is its W23 owner (correction: the design lists only `builders/write_targets.py`) |

## Context manifest

### Files to read first
- `temp/audit/governance-core-design.md` sections 2.3 and 2.4 and the PRP-108 entry.
- `packages/core/neurosphere_core/actions/targets.py` - `ACTION_CONNECTORS`, `TARGET_KIND_CONNECTORS`, resolution.
- `services/workers/neurosphere_workers/actions/targets.py:76-97` - executor-side resolution and the advisory refusal.
- `services/workers/neurosphere_workers/actions/executor.py:1-41` - pipeline; "no catalog metadata is touched here" (see Gotchas).
- `connectors/sdk-python/neurosphere_connector/write/` - `WriteConnector` protocol (`write_protocol.py:23-52`), `WriteRequest`/`DryRunResult`/`ApplyResult`/`VerifyResult`/`RollbackResult` (`write_models.py:42-115`), `WriteTargetRegistry` (`write_registry.py:54-105`).
- `services/workers/neurosphere_workers/runtime/factories.py:567-720,1431,1578-1612,1813-1864` - `build_actions`, `_action_write_targets`, `_register`, `register_write_targets`.
- `services/api/neurosphere_api/actions/settings.py` - `ActionKindPolicy`, `DEFAULT_ACTION_KINDS`.
- `packages/core/neurosphere_core/admin/platform/review_policy.py:203-240` - `LoadableReviewPolicyRegistry`.
- `services/workers/neurosphere_workers/publication/recorder.py` - worker catalog write under derived scope, audited before and after.
- `services/api/neurosphere_api/catalog/grant_publish.py` - drafting an intent with the connector's dry-run diff.
- `PRPs/backlog/PRP-105-policy-engine-core.md` and `PRPs/backlog/PRP-103-*.md` "Interfaces provided".

### Interfaces consumed
- PRP-99 ("Interfaces provided"; PRP-99 wins on any difference): `AgentVersion.approval` = `AgentVersionApproval` {`state` `AgentVersionApprovalState` not_required/pending/approved/rejected/suspended, `requested_at`, `decided_at`, `decided_by`, `intent_id`, `audit_id`, `policy_id`, `policy_version`, `reason_code`; optional, null = none recorded}; connector-manifest `write_support.actions` and the SDK `WriteAction` literal gain `agent_version_approve`, `agent_version_suspend`, `capture_policy_change`, `governance_policy_publish`, `enforcement_mode_change`; `CapturePolicy` (`state` proposed/active/suspended/retired; `approved_intent_id` and `approved_audit_id` required when active); `PolicyDefinition.published_intent_id`/`published_audit_id`; `EnforcementBinding` (`mode`, `state`, `last_intent_id`, `last_audit_id`, `last_verified_at`); review-policy `approver_permission` values `config.manage`, `govpolicy.manage`; the target-id convention `<cloud>:<customer>:neurosphere:<entity_type>:<id>`.
- PRP-105: `PolicyLifecycle.publish/retire`, `parse_publish_diff`, `parse_mode_change_diff`, `BindingStore.get/set_mode`, `ENFORCEMENT_POINT_CAPABILITIES`, `PolicyDecider.decide`, `PolicyDefinitionStore.get`.
- PRP-103 ("Interfaces provided"): `neurosphere_core.interactions.CapturePolicyStore` (Cosmos and in-memory), `apply_capture_policy_change(store, change, approved_audit_id) -> CapturePolicy`, `read_back_capture_policy(store, policy_id) -> CapturePolicy`. PRP-103 ships no route that proposes a change ("capture policy changes have no route and go through the executor"), so proposals use the shipped generic draft route `POST /api/v1/actions/domains/{domain}/intents` (`services/api/neurosphere_api/actions/router.py:106-123`); this PRP's handler defines and validates the `capture_policy_change` diff grammar.
- Shipped: action plane (PRP-17), write targets (PRP-35, PRP-54), `ActionApi.draft`, `CatalogRepository.update_entity` with ETag, `ScopeProvider`, `run_audited_mutation`.

### Interfaces provided
- Core: `neurosphere_core.actions.targets.PLATFORM_CONTROL_CONNECTOR = "platform-control"`, `PLATFORM_CONTROL_ACTION_KINDS`; rows for the five kinds in `ACTION_CONNECTORS` (no `TARGET_KIND_CONNECTORS` entry: an override by entity type would capture other kinds).
- Core: `neurosphere_core.actions.platform_control` - `PlatformControlHandler` protocol (`entity_types`, `action_kinds`, `current_version`, `plan`, `apply`, `read_back`, `rollback`), `PlatformControlHandlers` registry, the five handlers, `EFFECT_NEUROSPHERE_STATE = "neurosphere_state"`. Later PRPs that add an internal governed kind (PRP-127 register state, PRP-130 attestation) register a handler here and a row in `ACTION_CONNECTORS`.
- Core: `neurosphere_core.catalog.approval` - `RegistrationCheck` (runs `decide` for registration rules), `approval_block(...)`, `approve_diff`/`suspend_diff` and parsers.
- Core: `neurosphere_core.admin.platform.review_policy.PINNED_NO_SELF_APPROVAL` (the five kinds); `LoadableReviewPolicyRegistry.resolve` forces `self_approval_forbidden=True` for them.
- Worker: `neurosphere_workers.actions.platform_control.PlatformControlConnector` and `build_platform_control_target(stores...)`; registered by `register_write_targets` whenever its stores are configured (setting `NS_PLATFORM_CONTROL_ENABLED`, default true; false leaves the kinds advisory).
- API routes under `/api/v1/catalog/approvals` (own prefix, as `/api/v1/catalog/curation`): `POST /domains/{domain}/agent-versions/{entity_id}/submit` (`action.propose`), `POST /domains/{domain}/agent-versions/{entity_id}/suspend` (`action.propose`; body: `reason_code` and optional `evidence`, a list of at most 10 canonical ids such as the violation id `<cloud>:<customer>:neurosphere:policy_violation:<id>`, copied verbatim into the drafted intent's `evidence` so PRP-106's button and PRP-109's trail can link the fix to the violation; an id outside the caller's scope is refused `evidence_out_of_scope`), `GET /domains/{domain}/agent-versions/{entity_id}` (approval status from entity plus open intent; `data.read`), `GET /domains/{domain}/pending` (`data.read`).
- Audit operations `platform_control.apply`, `platform_control.rollback` (plus the executor's own), `catalog.approval.submit`.
- Frontend: `frontend/src/features/catalog/approval/` `AgentApprovalPanel` mounted on the agent-version entity page; mock handlers `frontend/tests/mock-api/features/catalog-approval.ts`.

### Patterns to match
- Write connector with dry run, apply, verify, rollback and a manifest: `connectors/reference/apim-gateway/neurosphere_connector_apim_gateway/mode.py` (`gateway_mode_change`: an audited switch that writes NeuroSphere-held state and verifies by read-back).
- Registration of a target: `services/workers/neurosphere_workers/runtime/factories.py:1704-1735` (`register_deploy_target`).
- Drafting from a domain route: `services/api/neurosphere_api/catalog/grant_publish.py`.
- Worker catalog write: `services/workers/neurosphere_workers/publication/recorder.py:99-150`.
- Confirmation dialog: `frontend/src/features/governed-change/ChangeConfirmDialog.tsx`.

### Gotchas
- `executor.py:40-41` says "no catalog metadata is touched here": keep it true. The executor still only calls `WriteConnector` methods; the platform-control connector is what writes, through the catalog repository with the worker's scope, audited before and after like `publication/recorder.py`. Update that docstring sentence only if review asks; it is not in this PRP's files.
- `SUPPORTED_WRITE_CONNECTORS` is derived from `ACTION_CONNECTORS` at import; adding the rows is what makes `_register` accept the connector.
- Do not add `enforcement_binding` or `policy` to `TARGET_KIND_CONNECTORS`: PRP-112's `gateway_policy_apply` must keep reaching APIM.
- The MCP `draft_action` tool resolves the domain from a catalog entity (`tools.py:377-382`); `agent_version` is one, but `governance_policy`, `enforcement_binding` and `capture_policy` targets are not (the catalog `Policy` projection has a different id, `...:policy:<id>`), so those three are drafted through REST and the UI until PRP-116 adds governance draft tools. The executor path is still the same for all channels. State this in the runbook; do not fake a catalog entity or retarget the intent at the projection.
- The apply of each handler stamps the evidence fields the contract requires: `approved_intent_id`/`approved_audit_id` on an activated capture policy, `published_intent_id`/`published_audit_id` on a published definition, `intent_id`/`audit_id`/`decided_by` on the approval block, `last_intent_id`/`last_audit_id`/`last_verified_at` on a binding.
- Manifest validity: `write_support.supported` true requires `advisory` false and `action_execution` in capabilities (`connector-manifest.schema.json:137-152`); `supported_clouds` both.
- `verify` must read the store, not the apply result; a matched verify with a stale read is a defect.
- `catalog/router.py`, `catalog/service.py` and `EntityForm.tsx` belong to PRP-76 next wave; this PRP adds only new files under `catalog/approval/`, one hook line in `routers.py`, and one import plus one mount in `CatalogEntityPage.tsx`.
- The catalog's own update path can still set an AgentVersion `active` (`catalog/service.py`, PRP-76's file next wave). Closing that path when a `registration` binding is `enforce` is a one-call change in `CatalogService` (call `RegistrationCheck`, refuse `registration_blocked`) that belongs to PRP-76; record it as a follow-up for PRP-76, do not edit `catalog/service.py` here.
- Frontend governance directories: PRP-106 (same wave) owns `frontend/src/features/governance/policy/**`; PRP-112 and PRP-113 (later waves) own `governance/enforcement/**`; PRP-109 (W24) owns `governance/trail/**`. This PRP touches none of them. PRP-78 owns `builders/copilot.py`; PRP-104 owns `interactions/**` and `replay/*`.
Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - packages/core/neurosphere_core/actions/targets.py
  - packages/core/neurosphere_core/actions/platform_control/**
  - packages/core/neurosphere_core/catalog/approval/**
  - packages/core/neurosphere_core/admin/platform/review_policy.py
  - packages/core/tests/platform_control/**
  - packages/core/tests/catalog_approval/**
  - services/workers/neurosphere_workers/actions/platform_control.py
  - services/workers/tests/platform_control_target/**
  - services/api/neurosphere_api/actions/settings.py
  - services/api/neurosphere_api/catalog/approval/**
  - services/api/tests/catalog_approval_api/**
  - frontend/src/features/catalog/approval/**
  - frontend/src/features/catalog/CatalogEntityPage.tsx
  - frontend/tests/mock-api/features/catalog-approval.ts
  - frontend/tests/e2e/catalog-approval.spec.ts
  - tests/security/authz/test_catalog_approval*.py
  - tests/security/platform_control/**
  - docs/runbooks/platform-control.md
tier1:
  - services/api/neurosphere_api/runtime/builders/write_targets.py
  - services/workers/neurosphere_workers/runtime/factories.py
tier2_appends:
  - services/api/neurosphere_api/routers.py
  - services/api/neurosphere_api/authz/routes.py
  - services/api/tests/authz/test_route_inventory.py
  - services/api/tests/authz/test_startup_route_check.py
  - services/api/tests/runtime_routes/manifest_calls.py
  - tests/integration/real_stack/test_manifest_routes.py
  - frontend/tests/mock-api/features/index.ts
  - frontend/tests/e2e/a11y/route-samples.ts
  - mkdocs.yml
must_not_touch:
  - packages/contracts/**
  - packages/core/neurosphere_core/governance/**
  - packages/core/neurosphere_core/interactions/**
  - packages/core/neurosphere_core/hitl/**
  - packages/core/neurosphere_core/catalog/protocol.py
  - packages/core/neurosphere_core/catalog/repo/**
  - services/workers/neurosphere_workers/actions/executor.py
  - services/api/neurosphere_api/catalog/router.py
  - services/api/neurosphere_api/catalog/service.py
  - services/api/neurosphere_api/runtime/builders/copilot.py
  - services/api/neurosphere_api/runtime/builders/data.py
  - services/api/neurosphere_api/mcp/**
  - frontend/src/features/governance/**
  - frontend/src/features/catalog/EntityForm.tsx
```

## Implementation blueprint

Parallelization: items 1 and 2 [P] (disjoint files). Item 3 after 1; item 4 after 3; item 5 after 1 and 4; item 6 after 5; item 7 after 6; item 8 last.

### Item 1 - Platform-control handlers in core  [P]
- Deliverable: `actions/platform_control/{__init__,protocol,registry,policy_publish,mode_change,capture,agent_version}.py`: the handler protocol and the five handlers over PRP-105, PRP-103 and the catalog repository ports; each `plan` validates the diff grammar against the kind (`action_kind_mismatch`), `current_version` returns the target ETag, `read_back` returns the observed fields the diff names, `rollback` restores the captured prior value; `point_cannot_enforce` and `cloud_boundary_mismatch` refusals.
- Owned files: `packages/core/neurosphere_core/actions/platform_control/**`, `packages/core/tests/platform_control/**`.
- Must NOT touch: `governance/**`, `interactions/**`, `catalog/protocol.py`.
- Depends on: PRP-105 and PRP-103 merged.
- Acceptance criteria: criteria 3, 4, 5 and the handler side of 6 on in-memory stores; a stale target version is `stale_version`; rollback is idempotent.
- Tests: `packages/core/tests/platform_control/test_<handler>.py` (five), `test_registry.py`.
- Pattern references: `connectors/reference/apim-gateway/neurosphere_connector_apim_gateway/mode.py`.

### Item 2 - Action-kind table, approval settings and the self-approval pin  [P]
- Deliverable: `PLATFORM_CONTROL_CONNECTOR` and five rows in `ACTION_CONNECTORS`; five `ActionKindPolicy(requires_approval=True)` entries in `DEFAULT_ACTION_KINDS`; `PINNED_NO_SELF_APPROVAL` and the `resolve` override in `LoadableReviewPolicyRegistry` (self-approval pin only; approvers stay the shipped `action.approve` rule, GD-20).
- Owned files: `actions/targets.py`, `api/actions/settings.py`, `admin/platform/review_policy.py`, `packages/core/tests/platform_control/test_targets_rows.py`, `test_self_approval_pin.py`.
- Must NOT touch: `hitl/**`.
- Depends on: none.
- Acceptance criteria: criterion 2; existing `services/api/tests/actions_api`, `packages/core/tests/actions` and admin-platform review-policy suites pass unchanged.
- Tests: the two files above plus `packages/core/tests/actions`, `services/api/tests/actions_api`.
- Pattern references: `actions/targets.py:59-72`, `actions/settings.py:35-37`.

### Item 3 - Worker write connector and registration
- Deliverable: `neurosphere_workers/actions/platform_control.py` (`PlatformControlConnector` implementing `WriteConnector` over the item-1 handlers, manifest via `build_manifest`, `effect: neurosphere_state` in dry-run evidence, audit before/after per apply and rollback); `register_write_targets` and `build_actions` build its stores (Cosmos, PRP-105 stores, PRP-103 capture store, catalog repository, worker `ScopeProvider`) and register it when `NS_PLATFORM_CONTROL_ENABLED` is not false.
- Owned files: `services/workers/neurosphere_workers/actions/platform_control.py`, `runtime/factories.py` (those two bodies), `services/workers/tests/platform_control_target/**`.
- Must NOT touch: `actions/executor.py`, other builder bodies.
- Depends on: item 1.
- Acceptance criteria: the executor runs an approved intent of each kind end to end on fakes (succeeded with verify matched); a verify mismatch rolls back; the existing `write_targets_worker` and `action_executor` suites pass unchanged.
- Tests: `services/workers/tests/platform_control_target/test_connector.py`, `test_executor_end_to_end.py`, plus `services/workers/tests/write_targets_worker`, `services/workers/tests/action_executor`.
- Pattern references: `runtime/factories.py:1704-1735`, `publication/recorder.py:99-150`.

### Item 4 - API composition of the target
- Deliverable: `runtime/builders/write_targets.py` passes the API-side stores to `register_write_targets` so the API dry-runs the same connector; `planes` unchanged.
- Owned files: `runtime/builders/write_targets.py`, `services/api/tests/catalog_approval_api/test_write_targets_builder.py`.
- Must NOT touch: `planes.py`, `data.py`.
- Depends on: item 3.
- Acceptance criteria: validation of each kind finds the connector in the API; with `NS_PLATFORM_CONTROL_ENABLED=false` every kind is advisory with "no supported write connector"; `services/api/tests/runtime_planes` and `runtime_api` pass.
- Tests: the file above plus `services/api/tests/runtime_planes`, `services/api/tests/runtime_api`.
- Pattern references: `write_targets.py:37-47`.

### Item 5 - Registration approval flow (core and routes)
- Deliverable: `catalog/approval/{check,diff,service}.py` in core; `services/api/neurosphere_api/catalog/approval/{__init__,router,service,models}.py` with the routes of "Interfaces provided"; submit runs `RegistrationCheck`, stores results as prerequisite results and drafts `agent_version_approve`; suspend drafts `agent_version_suspend` carrying the request's `evidence` ids in the intent's `evidence`; status merges entity state and open intent.
- Owned files: `packages/core/neurosphere_core/catalog/approval/**`, `packages/core/tests/catalog_approval/**`, `services/api/neurosphere_api/catalog/approval/**`, `services/api/tests/catalog_approval_api/**`; Tier-2 lines in `routers.py`, `authz/routes.py` and inventories.
- Must NOT touch: `catalog/router.py`, `catalog/service.py`.
- Depends on: items 1 and 4.
- Acceptance criteria: criteria 6, 7 and 8 (one draft per channel: REST route, `ActionApi` direct as the copilot path, MCP `draft_action`).
- Tests: `services/api/tests/catalog_approval_api/test_routes.py`, `test_channels.py`; `packages/core/tests/catalog_approval/test_check.py`.
- Pattern references: `catalog/grant_publish.py`, `routers.py:106-109`.

### Item 6 - Approval panel on the agent page
- Deliverable: `AgentApprovalPanel` (status, rule check results, submit and suspend buttons opening `ChangeConfirmDialog` with the exact diff, the label "NeuroSphere state change"), mounted for `agent_version` entities in `CatalogEntityPage.tsx`; mock handlers; e2e.
- Owned files: `frontend/src/features/catalog/approval/**`, one import and one mount in `CatalogEntityPage.tsx`, `frontend/tests/mock-api/features/catalog-approval.ts`, `frontend/tests/e2e/catalog-approval.spec.ts`; Tier-2 `features/index.ts`, `route-samples.ts`.
- Must NOT touch: `EntityForm.tsx`, `frontend/src/features/governance/**`.
- Depends on: item 5.
- Acceptance criteria: criterion 9 in the UI and the binding mode of criterion 8 shown; keyboard and screen-reader pass in the a11y sample; Fluent dialog queries use `hidden: true`.
- Tests: `frontend/src/features/catalog/approval/approval.test.tsx`, `frontend/tests/e2e/catalog-approval.spec.ts`.
- Pattern references: `frontend/src/features/governed-change/ChangeConfirmDialog.tsx`, `frontend/src/features/actions/ActionWorkflow.tsx`.

### Item 7 - Authorization and constraint negative suite
- Deliverable: ABAC cases for the new routes; tests that no route, worker or handler writes `approval`, a published policy, a capture policy or a binding mode outside an executed intent (enumerate writers); self-approval pin under a hostile stored policy; cloud boundary refusal; labels contain no external-change wording.
- Owned files: `tests/security/authz/test_catalog_approval.py`, `tests/security/platform_control/**`.
- Must NOT touch: shared harness files except additive helpers.
- Depends on: item 6.
- Acceptance criteria: criteria 2, 10 and 11; none skipped.
- Tests: `tests/security/authz`, `tests/security/platform_control`.
- Pattern references: `tests/security/authz/test_admin_platform.py`.

### Item 8 - Integration and close-out
- Deliverable: `docs/runbooks/platform-control.md` (kinds, targets, who proposes and approves, the REST-only drafting of bindings and capture policies until PRP-116, how to disable); mkdocs nav; rebase; Tier-3 regeneration; changelog fragment; completion note with `NS_PLATFORM_CONTROL_ENABLED` and the product check (can a steward submit an agent version and an approver activate it in the UI?).
- Owned files: runbook, Tier-2 lines, this PRP file, Tier-3 files.
- Depends on: items 1-7.
- Acceptance criteria: validation gates pass; CI green.

## Validation gates
```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q packages/core/tests/platform_control packages/core/tests/catalog_approval packages/core/tests/actions packages/core/tests/hitl services/workers/tests/platform_control_target services/workers/tests/write_targets_worker services/workers/tests/action_executor services/api/tests/catalog_approval_api services/api/tests/actions_api services/api/tests/hitl_api services/api/tests/mcp_api services/api/tests/runtime_planes services/api/tests/runtime_api services/api/tests/runtime_routes services/api/tests/authz tests/security/authz tests/security/platform_control services/api/tests/test_openapi_drift.py tests/docs/test_reference_coverage.py tests/docs/test_nav_allowlist.py
pnpm --filter @neurosphere/frontend lint
pnpm --filter @neurosphere/frontend typecheck
pnpm --filter @neurosphere/frontend test
pnpm --filter @neurosphere/frontend test:e2e
python scripts/prp_status.py --check
python scripts/validate_planning.py
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```

## Migration and rollback
No data migration: existing AgentVersions have no `approval` block and read as `not_required` (PRP-99 default). Rollback: `NS_PLATFORM_CONTROL_ENABLED=false` makes the five kinds advisory again (drafts stay visible, nothing executes); or revert the PR. Approvals already executed stay recorded on the entities and in audit; a suspend is reversed by a new approve intent, never by an edit.

## Live and open gates
None. The target is internal and runs on in-memory twins and, locally, the Cosmos emulator. The hosted run of the approval step is part of PRP-109's operator-approved north-star run (OPEN until evidenced).

## NOT building
External effects of an approval (revoking a gateway grant stays `grant_unpublish`; enforcement on a gateway is PRP-112); an automatic approval or an approval by policy alone (a person always approves); self-approval under any configuration; a "break glass" bypass of approval; governance draft tools for the copilot and MCP (PRP-116); run-as identity on the form (PRP-118); CI registration checks (PRP-129); bulk approval.

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [ ] All clarification questions are decided, not guessed (rows 4, 5, 6 and 9 are ASSUMPTIONS; PRP-99, PRP-103 and PRP-105 names are taken from their backlog files and are final only when they ship)

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
- Product check (can an operator use it without editing files or calling raw APIs):
