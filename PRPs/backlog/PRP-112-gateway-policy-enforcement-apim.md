---
name: PRP-112-gateway-policy-enforcement-apim
status: backlog
priority: P1
order: 112
review: required
created: 2026-11-16
model: opus
orchestrator_model: opus
implementer_model: opus
phase: 9
ns: NS-06, NS-08, NS-09
depends_on: [PRP-99-governance-contracts-a, PRP-105-policy-engine-core, PRP-108-agent-approval-gate-and-platform-control-actions]
wave: W25
branch: prp-112-gateway-enforcement
allow_parallel: true
issues: []
---

# PRP-112: Gateway policy enforcement through the APIM write connector

## Goal
Turn a published `model_allow_list` policy into a real control on model traffic where, and only where, NeuroSphere can actually stop it: an Azure API Management gateway that is registered in manage mode, in Commercial, on the NeuroSphere-owned grant products. The policy rule is compiled into a typed plan (no free-form XML from a user or a model), rendered by the existing APIM write connector from a reviewed template into a NeuroSphere-namespaced policy fragment, and applied through a new `gateway_policy_apply` action kind: dry run shows the exact fragment and product-policy diff with a plan digest, approval is required, apply follows the connector's dependency order, the executor's verify reads the gateway back, and rollback restores what was there. The binding starts in `audit` (nothing is written; the PRP-105 evaluator flags observed traffic from PRP-33's gateway telemetry); only after an approved `enforcement_mode_change` (PRP-108) can an apply intent be drafted, and the binding shows `applied` only after a verified apply is recorded. Every screen states per point what can be blocked. It is for platform owners who want a model allow-list enforced on the gateway, and it runs in W25 after PRP-108.

Out of scope: per-consumer token limits and budget cut-off (they already exist as `budget_cap_change` on a grant's `llm-token-limit`, PRP-34, and PRP-115 proposes that action; no PRP-99 rule kind carries a rate or token limit); a content-safety check at the gateway (no PRP-99 rule kind expresses it; item 1 only records whether the gateway policy exists, for a future rule kind); enforcement on APIs or products NeuroSphere did not create; the Government gateway (stays advisory, as the connector says today); tool-call and MCP enforcement (PRP-113); the SDK guard (PRP-114); a real gateway run (G17 manage, OPEN, PRP-136).

## Why
- The policy engine (PRP-105) decides and records, but nothing reaches the gateway: `ACTION_CONNECTORS` maps no policy kind to APIM (`packages/core/neurosphere_core/actions/targets.py:59-72`), and the connector's kinds are swap, cap, grant publish/unpublish, MCP publish/unpublish and mode change (`connectors/reference/apim-gateway/neurosphere_connector_apim_gateway/connector.py:90-99`).
- The connector already writes the resources enforcement needs, in a load-bearing order: named values, backends, policy fragments, APIs, API and product policies, products, links, subscriptions (`models.py:44-73`), from templates (`policies/templates/`, `policies/__init__.py:122-195`), with a plan digest bound into the diff (`translate.py:76-89`), translators per target kind (`translate.py:61-73`, `dispatch.py:132-155`) and rollback by apply record.
- Grant products are NeuroSphere-owned (`ns-grant-*` names, `grants.py:20-24`, `:426`) and carry the per-consumer `llm-token-limit` (`policies/templates/grant-product.xml:2`), so a governance fragment included in their product policy acts on exactly the consumers NeuroSphere granted.
- Government manage is refused until the capability row `apim.backend_pool.government.any.standard_v2` is available (`connector.py:136-149`, `README.md:170-171`), and G17 manage has never run live (`docs/RESEARCH-AND-GATES.md:39`; `README.md:172`).
- `docs/PRD.md:31` (actions need "a supported write connector ... unsupported actions are advisory, not catalog-only pretend changes") and `:37` (server-side controls, "approved endpoints"); owner direction 2026-11-16 to plan all identified gaps; design section 2.3 lists the gateway as enforcement point 1.

## Acceptance criteria
- [ ] Given a published policy with a `model_allow_list` rule and a `gateway` binding in `audit`, Then no intent can be drafted that writes to the gateway (`binding_not_enforce`), the gateway is untouched, and violations come only from the PRP-105 evaluator over gateway-sourced model aggregates.
- [ ] Given the binding moved to `enforce` by an approved `enforcement_mode_change`, When a caller with `action.propose` drafts `gateway_policy_apply` (stage `apply`) for that binding, Then the intent carries the connector's dry-run diff with `test /plan_digest`, the rendered fragment and every product-policy change are shown (names, before and after digests, and the allowed model and deployment list), approval is required and self-approval refused.
- [ ] The plan writes only `ns-gov-*` fragments and the product policies of `ns-grant-*` products recorded `created` by a NeuroSphere grant publication apply record on the bound gateway; any other API or product is refused `resource_not_owned` and the binding state is `not_supported` for it.
- [ ] Canary: the first apply for a binding targets exactly one product (`rollout: canary`); a second intent with `rollout: all` is required to widen; each is its own approval.
- [ ] Executed on the in-memory APIM twin: apply writes in dependency order, verify reads fragment and product policy back and matches, a forced verify mismatch rolls back to the captured prior documents, and the executor's existing `check_gateway_binding` refuses a gateway registered in another domain.
- [ ] `POST .../record` accepts only a `succeeded`, verified, non-dry-run `gateway_policy_apply` intent of this binding and then sets binding `state` (`applied` or `pending` after `remove`) with `last_intent_id`, `last_audit_id`, `last_verified_at`; it never changes `mode`. `POST .../check` dry-runs the current desired plan and sets `drifted` when the gateway differs.
- [ ] Stage `remove` (drafted when the binding returns to `audit` or `off`) deletes only fragments recorded `created` and restores product policies to their captured prior document; a product already deleted by a grant unpublish counts as removed.
- [ ] Government, observe mode or an advisory connector: the intent is advisory ("no supported write connector"), the UI says "Government: audit only, the gateway cannot be managed in this cloud" or "gateway in observe mode", and nothing claims enforcement.
- [ ] No user- or model-supplied string reaches XML: the allowed list is validated against PRP-99 `ModelAllowListParams` and the name grammar, rendered through the connector's attribute escaping, and a test renders every variant and parses it.
- [ ] Bindings page lists per point the capability statement from PRP-105 `ENFORCEMENT_POINT_CAPABILITIES`, the mode, the state and the last verified time; routes are scope-filtered, in the inventories and deny every ABAC dimension.
- PRP exit: touched suites (incl. every `connectors/reference/apim-gateway/tests` file), `tests/security/authz`, frontend lint/typecheck/test, ruff, pyright, `validate_planning.py` pass; PR open, CI green; G17 enforcement step OPEN.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| 1 | Which rule kinds compile to the gateway | All; those with a gateway meaning | `model_allow_list` only. Limits and budget cut-off stay `budget_cap_change` (PRP-34, PRP-115); content safety has no PRP-99 rule kind (recorded in item 1, not built) |
| 2 | Where the fragment applies | Customer APIs; NeuroSphere-owned products | NeuroSphere-owned `ns-grant-*` product policies only; customer-authored APIs are never edited (ownership rule as in `grants.py:20-27`) |
| 3 | Audit mode at the gateway | Log-only fragment; nothing written | Nothing written; detection is the PRP-105 evaluator over observed gateway telemetry (PRP-33). A log-only fragment would be a gateway change without a control |
| 4 | Enforcement default | `audit`; `enforce` | ASSUMPTION (GD-7, recommended default): `audit` for every policy and point; `enforce` only by an approved action, per point. Here: per binding, after an approved `enforcement_mode_change` and then an approved `gateway_policy_apply` (row 5) |
| 5 | Two approvals | One combined; two | ASSUMPTION (GD-23, recommended default): gateway enforcement needs two approved intents: `enforcement_mode_change` (NeuroSphere state) and then `gateway_policy_apply` (the external change), with a canary on one product first. Here: the mode change records the decision (NeuroSphere state, PRP-108); the apply changes an external system. Combining would make a NeuroSphere-state intent touch the gateway |
| 6 | Target of the intent | The gateway; the binding | The binding (`enforcement_binding` canonical id per PRP-99 convention); no `TARGET_KIND_CONNECTORS` entry, so `enforcement_mode_change` on the same entity type still reaches platform-control |
| 7 | Who drafts and records | Several | ASSUMPTION: drafting needs `action.propose` in the binding's domain (as grant publish, `catalog/grant_publish.py:3-8`); `record` and `check` need `govpolicy.manage`; reads `govpolicy.read` |
| 8 | Government | Enforce; advisory | Advisory, unchanged (`connector.py:136-149`); never rerouted to Commercial |
| 9 | Verification file location | `docs/connectors/verification/` (PRP-117, W26); connector directory | `connectors/reference/apim-gateway/ENFORCEMENT-VERIFICATION.md`, inside this PRP's ownership |

## Context manifest

### Files to read first
- `temp/audit/governance-core-design.md` section 2.3 (enforcement points) and the PRP-112 entry; section 9 U-4.
- `connectors/reference/apim-gateway/README.md` - what the connector writes, references, gaps (`:120-172`).
- `connectors/reference/apim-gateway/neurosphere_connector_apim_gateway/translate.py:61-89` - `IntentTranslator`, plan digest.
- `.../grants.py:1-60,273-430` - owned product names, product policy rendering, ownership from apply records.
- `.../dispatch.py:92-155` - `GrantDispatchTranslator`, `default_translators`.
- `.../connector.py:90-150` - `ACTION_KINDS`, `manifest_actions`, `government_refusal`.
- `.../policies/__init__.py` - template rendering and attribute escaping.
- `services/workers/neurosphere_workers/actions/targets.py:107-140` - `check_gateway_binding`.
- `services/api/neurosphere_api/catalog/grant_publish.py` - draft with the connector's dry-run diff; the `.../publication` record route.
- `PRPs/backlog/PRP-105-policy-engine-core.md` and `PRPs/backlog/PRP-108-agent-approval-gate-and-platform-control-actions.md` "Interfaces provided".

### Interfaces consumed
- PRP-99: `ModelAllowListParams` {`allowed_models` (model name and version), `allowed_deployment_ids`}; `EnforcementBinding` (`point` `gateway`, `target` the gateway `TargetRef` or null, `mode`, `state` including `not_supported` and `drifted`, `last_*`); manifest action and SDK `WriteAction` value `gateway_policy_apply`.
- PRP-105: `BindingStore` (`get`, `list`, `set_state`), `PolicyDefinitionStore.get`, `ENFORCEMENT_POINT_CAPABILITIES`, permissions `govpolicy.read`/`govpolicy.manage`, router package `neurosphere_api.governance`.
- PRP-108: `enforcement_mode_change` executed by platform-control (sets the binding `mode`); `actions/targets.py` is this PRP's file in W25 for one row.
- Shipped PRP-33/PRP-34: the APIM connector, apply records, gateway registry and mode (`neurosphere_core.gateway`), gateway telemetry; PRP-54 write targets per domain.

### Interfaces provided
- Core: `neurosphere_core.governance.enforcement.gateway` - `GatewayEnforcementPlan` (typed: binding id, policy id and version, gateway id, products, allowed models, allowed deployment ids, rollout `canary|all`, stage `apply|remove`), `compile_binding(definition, binding, owned_products) -> GatewayEnforcementPlan`, `apply_diff(plan)` / `parse_apply_diff(diff)` (one `replace /gateway_enforcement` plus `test /plan_digest`).
- Connector: `GatewayPolicyTranslator` (entity type `enforcement_binding`, kind `gateway_policy_apply`), template `policies/templates/gov-model-allow.xml`, `render_gov_fragment(plan)`, `gov_fragment_id(binding_id)` (`ns-gov-<12 hex>`); `ACTION_KINDS` gains `gateway_policy_apply`; registered in `default_translators`.
- Core table: `ACTION_CONNECTORS["gateway_policy_apply"] = APIM_GATEWAY_CONNECTOR`.
- Routes under `/api/v1/governance/enforcement/gateway`: `GET /domains/{domain}/bindings`, `GET /domains/{domain}/bindings/{binding_id}`, `POST .../bindings/{binding_id}/apply` (body `rollout`; returns the drafted intent), `POST .../bindings/{binding_id}/remove`, `POST .../bindings/{binding_id}/record` (body `intent_id`), `POST .../bindings/{binding_id}/check`.
- Frontend: `frontend/src/features/governance/enforcement/` `EnforcementBindingsPage` (all points, capability statement per point; gateway actions here); PRP-113 adds its tool and MCP rows under `enforcement/tools/`.
- Gate script `scripts/gates/g17_apim_enforce_live.py` (refuses without `NS_LIVE_APPROVED=1`).

### Patterns to match
- Translator with stages, ownership from apply records and digest: `.../mcp.py` (`McpServerTranslator`, deny-first stages) and `.../grants.py`.
- Draft-from-route and record-after-success: `services/api/neurosphere_api/catalog/grant_publish.py`.
- Template rendering test that parses every variant: `connectors/reference/apim-gateway/tests/test_apim_write_policies.py`.
- Gate script refusal shape: `scripts/gates/g17_apim_manage_live.py`.

### Gotchas
- UNVERIFIED (U-4, design section 9): APIM offers policies usable for model allow-listing, token limits per consumer and a content-safety check. Item 1 fetches Microsoft Learn and records, with URL and date: how a request names its deployment or model on the Azure OpenAI and v1 routes as seen by a policy expression (path parameter versus body `model`), whether reading the body in a policy is allowed without breaking streaming, the `return-response`/`choose` behaviour, whether `llm-content-safety` (or any content-safety policy) exists and its prerequisites, and availability in Azure Government. Code only what was verified; anything unverified stays audit-only with the reason on the bindings page.
- The grant product policy is rendered by `GrantPublicationTranslator` (`grants.py:273`); a later grant re-plan must not see the governance include as drift or delete it. Test grant publish, cap change and unpublish with a governance fragment present.
- `cap.py:212-222` refuses a grant fragment with several `llm-token-limit`; the governance fragment is a separate fragment with none, so keep it so.
- Never add `enforcement_binding` to `TARGET_KIND_CONNECTORS` (it would send PRP-108's `enforcement_mode_change` to APIM).
- The API only dry-runs (`runtime/builders/write_targets.py:3-8`); apply, verify and rollback run in the executor worker. `check` is a dry run, never an apply.
- Recording state after a verified intent is not a policy change (mode is untouched), the same rule as the grant publication record route; it must re-read the intent and refuse anything else.
- G17 manage is OPEN: nothing here may say the control works on a real gateway; the runbook and UI say "verified on the in-memory twin only" until PRP-136 evidence exists.
- PRP-117 owns `docs/connectors/verification/**` from W26; do not create files there.
Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - connectors/reference/apim-gateway/**
  - packages/core/neurosphere_core/actions/targets.py
  - packages/core/neurosphere_core/governance/enforcement/__init__.py
  - packages/core/neurosphere_core/governance/enforcement/gateway/**
  - packages/core/tests/governance_enforcement_gateway/**
  - services/api/neurosphere_api/governance/enforcement/__init__.py
  - services/api/neurosphere_api/governance/enforcement/gateway/**
  - services/api/tests/governance_gateway_api/**
  - frontend/src/features/governance/enforcement/**
  - frontend/tests/mock-api/features/governance-enforcement.ts
  - frontend/tests/e2e/governance-enforcement.spec.ts
  - scripts/gates/g17_apim_enforce_live.py
  - tests/security/authz/test_governance_gateway*.py
  - docs/runbooks/gateway-enforcement.md
tier1: []
tier2_appends:
  - services/api/neurosphere_api/routers.py
  - services/api/neurosphere_api/authz/routes.py
  - services/api/tests/authz/test_route_inventory.py
  - services/api/tests/authz/test_startup_route_check.py
  - services/api/tests/runtime_routes/manifest_calls.py
  - tests/integration/real_stack/test_manifest_routes.py
  - frontend/src/app/appRoutes.ts
  - frontend/src/app/route-manifest.json
  - frontend/src/app/workspaceNav.ts
  - frontend/tests/mock-api/features/index.ts
  - frontend/tests/e2e/a11y/route-samples.ts
  - mkdocs.yml
must_not_touch:
  - packages/contracts/**
  - packages/core/neurosphere_core/governance/policy/**
  - packages/core/neurosphere_core/actions/platform_control/**
  - services/workers/neurosphere_workers/actions/**
  - services/workers/neurosphere_workers/runtime/factories.py
  - services/api/neurosphere_api/runtime/builders/**
  - frontend/src/features/governance/policy/**
  - docs/connectors/verification/**
  - docs/RESEARCH-AND-GATES.md
```

## Implementation blueprint

Parallelization: item 1 first (it decides what is coded). Items 2 and 3 [P] after 1 (core and connector share no file; 3 codes against item 2's plan model, frozen in its first commit). Item 4 after 3; item 5 after 2 and 4; item 6 after 5; item 7 after 5; item 8 last.

### Item 1 - Verify-first: APIM policy capabilities
- Deliverable: `connectors/reference/apim-gateway/ENFORCEMENT-VERIFICATION.md` with the facts listed in Gotchas (URL, retrieval date, verified or not, Government availability), and the decision per capability (build, audit-only, not built); the orchestrator pastes Learn excerpts if the session has no Learn access.
- Owned files: that file.
- Must NOT touch: code.
- Depends on: none.
- Acceptance criteria: every capability the later items code is marked verified with a source; anything else is listed as audit-only with its reason.
- Tests: none (document); item 3's template test cites it.
- Pattern references: `connectors/reference/apim-gateway/README.md` "References".

### Item 2 - Core compiler  [P]
- Deliverable: `governance/enforcement/{__init__}.py`, `governance/enforcement/gateway/{plan,compile,diff}.py`: typed plan, compile from definition and binding (refuses non-`model_allow_list` kinds `rule_kind_not_gateway`, unowned products, `audit`/`off` mode for stage `apply`), diff grammar and parser.
- Owned files: those modules, `packages/core/tests/governance_enforcement_gateway/**`.
- Must NOT touch: `governance/policy/**`.
- Depends on: item 1.
- Acceptance criteria: criteria 1 and 9 (core side); deterministic plan for the same inputs; bounded lists.
- Tests: `packages/core/tests/governance_enforcement_gateway/test_compile.py`, `test_diff.py`.
- Pattern references: `packages/core/neurosphere_core/gateway/mode.py`.

### Item 3 - Connector translator and template  [P]
- Deliverable: `GatewayPolicyTranslator` (`current_version` from the fragment and product-policy ETags, `specs` for stages `apply` and `remove`, ownership check against grant apply records, `check_kind`), `gov-model-allow.xml` per item 1, `render_gov_fragment`, `ACTION_KINDS` row, `default_translators` registration, README section.
- Owned files: `connectors/reference/apim-gateway/**`.
- Must NOT touch: core packages other than item 2's import.
- Depends on: items 1 and 2's plan module.
- Acceptance criteria: criteria 3, 5 (connector side), 7 and 9; existing apim tests unchanged and green; grant publish, cap change and unpublish with a governance include present pass.
- Tests: `connectors/reference/apim-gateway/tests/test_apim_gov_enforcement.py`, `test_apim_gov_templates.py`, `test_apim_gov_grant_interplay.py`, plus the whole `connectors/reference/apim-gateway/tests`.
- Pattern references: `.../mcp.py`, `.../grants.py:273-430`, `tests/test_apim_write_policies.py`.

### Item 4 - Action-kind row and executor end to end
- Deliverable: `ACTION_CONNECTORS["gateway_policy_apply"]`; an executor test on the in-memory APIM twin running stage `apply` (canary then all) and `remove`, with verify mismatch rollback and `check_gateway_binding` refusal.
- Owned files: `packages/core/neurosphere_core/actions/targets.py`, `packages/core/tests/governance_enforcement_gateway/test_executor_apim.py`.
- Must NOT touch: `services/workers/neurosphere_workers/actions/**`.
- Depends on: item 3.
- Acceptance criteria: criteria 4 and 5; `packages/core/tests/actions` and `services/workers/tests/action_executor` pass unchanged.
- Tests: the file above plus those suites.
- Pattern references: `connectors/reference/apim-gateway/tests/apim_write_support.py`.

### Item 5 - API routes
- Deliverable: `services/api/neurosphere_api/governance/enforcement/{__init__}.py` and `gateway/{router,service,models}.py`: the routes of "Interfaces provided"; apply and remove draft through `ActionApi.draft` with the connector's dry-run diff (pattern `grant_publish.py`); `record` re-reads the intent; `check` dry-runs; Government and observe-mode answers per criterion 8.
- Owned files: those modules, `services/api/tests/governance_gateway_api/**`; Tier-2 lines.
- Must NOT touch: `runtime/builders/**` (the routes read `app.state` planes published by PRP-105 and the action plane).
- Depends on: items 2 and 4.
- Acceptance criteria: criteria 1, 2, 6 and 8 at the route level.
- Tests: `services/api/tests/governance_gateway_api/test_routes.py`, `test_record.py`, `test_government.py`.
- Pattern references: `catalog/grant_publish.py`, `routers.py:106-109`.

### Item 6 - Bindings page
- Deliverable: `EnforcementBindingsPage` (filters by point and policy; capability statement per point; mode, state, last verified; gateway apply, remove, record and check actions through `ChangeConfirmDialog`; Government and observe banners); route and nav lines; mock handlers; e2e.
- Owned files: `frontend/src/features/governance/enforcement/**`, mock and e2e files; Tier-2 frontend lines.
- Must NOT touch: `frontend/src/features/governance/policy/**` (PRP-106).
- Depends on: item 5.
- Acceptance criteria: criterion 10 in the UI; a11y sample passes.
- Tests: `frontend/src/features/governance/enforcement/bindings.test.tsx`, `frontend/tests/e2e/governance-enforcement.spec.ts`.
- Pattern references: `frontend/src/features/gateways/`, `frontend/src/features/governed-change/ChangeConfirmDialog.tsx`.

### Item 7 - Authorization suite and live gate script
- Deliverable: ABAC cases for every route; a test that no route writes `mode`; `scripts/gates/g17_apim_enforce_live.py` (per-step approval, throwaway Limitlessdata targets only, refuses without `NS_LIVE_APPROVED=1`, writes `docs/evidence/G17/enforce-*.md` only when run by the operator).
- Owned files: `tests/security/authz/test_governance_gateway.py`, the script.
- Must NOT touch: `scripts/gates/g17_apim_manage_live.py`, `docs/RESEARCH-AND-GATES.md`.
- Depends on: item 5.
- Acceptance criteria: criterion 10 (authorization part); the script's refusal path is unit-tested.
- Tests: `tests/security/authz/test_governance_gateway.py`, `tests/security/authz/test_governance_gateway_gate_script.py`.
- Pattern references: `scripts/gates/g17_apim_manage_live.py`.

### Item 8 - Integration and close-out
- Deliverable: `docs/runbooks/gateway-enforcement.md` (what is blocked, where, and what is not; two approvals; canary; Government; G17 OPEN); mkdocs nav; rebase; Tier-3 regeneration; changelog fragment; completion note with the hand-off of the live step to PRP-136 and the product check.
- Owned files: runbook, Tier-2 lines, this PRP file, Tier-3 files.
- Depends on: items 1-7.
- Acceptance criteria: validation gates pass; CI green.

## Validation gates
```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q connectors/reference/apim-gateway/tests packages/core/tests/governance_enforcement_gateway packages/core/tests/actions services/workers/tests/action_executor services/workers/tests/write_targets_worker services/api/tests/governance_gateway_api services/api/tests/runtime_routes services/api/tests/authz tests/security/authz tests/unit/connector_conformance services/api/tests/test_openapi_drift.py tests/docs/test_reference_coverage.py tests/docs/test_nav_allowlist.py
pnpm --filter @neurosphere/frontend lint
pnpm --filter @neurosphere/frontend typecheck
pnpm --filter @neurosphere/frontend test
pnpm --filter @neurosphere/frontend test:e2e
python scripts/prp_status.py --check
python scripts/validate_planning.py
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```

## Migration and rollback
No data migration. Turning it off: return a binding to `audit` (approved `enforcement_mode_change`) and run stage `remove` (approved `gateway_policy_apply`), which deletes only `ns-gov-*` fragments it created and restores product policies. Emergency: the executor kill switch stops further applies; the gateway keeps the last verified state until a `remove` runs. Reverting the PR leaves already-applied fragments on a gateway: run `remove` first.

## Live and open gates
G17 manage plus the enforcement step needs `NS_LIVE_APPROVED=1` on a throwaway Limitlessdata APIM (never the reused Loom APIM) and is OPEN here; it is handed to PRP-136 (governance live gates) and recorded in the G17 row there. Government stays OPEN (no subscription; manage disabled).

## NOT building
Blocking inside third-party SaaS or for traffic that does not pass a NeuroSphere-managed gateway; editing customer-authored APIs or products; gateway content or DLP checks (only if a verified policy and a rule kind exist later; design section 8 item 7); automatic budget cut-off (a proposed `budget_cap_change` with approval, PRP-115; design section 8 item 14); per-consumer rate limits beyond the shipped grant caps; Government enforcement; any claim that enforcement works on a real gateway before G17 evidence exists.

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [ ] All clarification questions are decided, not guessed (rows 4 and 7 are ASSUMPTIONS; item 1 decides what is verified)

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
