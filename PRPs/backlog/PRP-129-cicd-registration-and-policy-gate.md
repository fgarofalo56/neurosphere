---
name: PRP-129-cicd-registration-and-policy-gate
status: backlog
priority: P2
order: 129
review: required
created: 2026-11-16
model: opus
orchestrator_model: opus
implementer_model: opus
phase: 9
ns: NS-08, NS-09
depends_on: [PRP-108-agent-approval-gate-and-platform-control-actions, PRP-105-policy-engine-core, PRP-127-ai-system-register-tiering-and-impact-assessments]
wave: W31
branch: prp-129-cicd-gate
allow_parallel: true
issues: []
---

# PRP-129: CI/CD registration and policy gate

## Goal
Let a deployment pipeline ask NeuroSphere, before it ships an agent version, whether that version is registered, approved, free of open policy violations, risk-assessed and safety-evaluated, and get back a decision it can act on. A CI service principal calls `POST /api/v1/governance/checks/registration` with a `RegistrationCheckRequest` and receives a `RegistrationCheckResponse` (result, a fixed exit code, and one status plus reason code per check). GitHub Actions is the first-class integration (a composite Action with a documented exit-code contract and a sample workflow); Azure DevOps and Jenkins get documented `curl` recipes against the same API and nothing more. The check authenticates with workload identity federation (no stored secret) once a verify-first item confirms it, is rate limited, and returns only reasons the caller is allowed to see. It checks and reports. It never approves, activates, suspends or waives anything: approvals stay with the action executor (PRP-108), and a green check is evidence at one instant, not an approval. Opus: this is a new machine-to-machine authorization surface.

Out of scope: the approval flow and the platform-control target (PRP-108); policy evaluation and violations (PRP-105); the register, tiers and assessments (PRP-127); safety evaluation records (PRP-131, W32: the safety check reports `unknown` until it ships); the contracts (PRP-110 `RegistrationCheck*`); the SDK runtime guard (PRP-114); Azure DevOps and Jenkins as products (recipes only, design section 8, item 13); creating the Entra federated credential or the repository (operator steps).

## Why
- `docs/PRD.md:44` promises "integrate CI/CD registration/policy checks with GitHub Actions, Azure DevOps and Jenkins"; nothing was built (`docs/validation/lane3-map-copilot-integration.md:39` lists "CI/CD registration (GitHub Actions, Azure DevOps, Jenkins)" as MISSING), and a grep for a registration check route finds none.
- A CI principal can already authenticate: `idtyp=app` becomes principal kind `service_principal` (`packages/core/neurosphere_core/auth/jwt/validator.py:208-209` reads `identity_type`; `packages/core/neurosphere_core/auth/scope/derivation.py:175`). What is missing is a route, a least-privilege permission and a decision.
- Lifecycle has no approval or registration gate state (`catalog/v1/common.schema.json:58-66`; only `deprecate` is built, `services/api/neurosphere_api/catalog/service.py:341`); PRP-108 adds `AgentVersion.approval` and `RegistrationCheck`, PRP-127 the register, PRP-105 violations: this PRP is the pipeline-facing read over them.
- `Permission` has no CI-shaped permission and `Role` is closed (`packages/core/neurosphere_core/auth/scope/permissions.py:73-96`); a gate that needed `catalog.curate` or `action.*` would be a bypass waiting to happen.
- Machine callers need throttling: the only limiter is ingest-local (`services/api/neurosphere_api/ingest/limits.py:51-97`).
- The owner asked on 2026-11-16 for "the ultimate team AI governance and auditing tool"; shipping an agent that skipped registration is the failure this prevents.

## Acceptance criteria
- [ ] Given a CI service principal holding `registration.check` on the agent's domain, When it posts a request naming a registered, approved version with a matching `config_hash`, Then the response is `result: pass`, `exit_code: 0`, one entry per check, and `check_id` appears in an audit record with the pipeline `run_ref` and no token or secret.
- [ ] The decision table holds: any check in `NS_GOV_CHECK_FAIL_ON` with status `fail` gives `fail`/1; none failing but a required check `unknown` gives `warn`/2 ("could not decide"); everything else `pass` or `warn` with 0. Checks: `registered` (version exists in a visible domain, not deprecated or retired, `config_hash` equal when sent), `approved` (PRP-108 `RegistrationCheck`: `approved` passes, `pending|rejected|suspended` fails, `not_applicable` when no registration rule requires approval), `policy_clean` (no open PRP-105 violation at or above `NS_GOV_CHECK_MIN_SEVERITY` on the version or its agent; an excepted violation does not count), `risk_assessed` (PRP-127 reader: a registered AI system with a recorded determination and, where the recorded tier token is in `NS_RISK_ASSESSMENT_REQUIRED_TIERS`, an approved assessment), `safety_evaluated` (`unknown` with `safety_records_unavailable` until PRP-131).
- [ ] No oracle: an id that does not exist, belongs to another domain, customer or cloud, or is outside the caller's permitted domains yields the same `registered: fail`, `not_registered` response and timing class; the response never contains an entity name, a violation text, a tier value or an id from a domain the caller cannot read (`evidence_ref` is null unless the caller has `data.read` there).
- [ ] Not a bypass: the route writes only an audit record; a test asserts it never calls the action executor, `CatalogService`, any `platform_control` handler or `HitlService`; a second test asserts no code outside this package reads a stored check result; the permission set of the role holding `registration.check` contains none of `action.*`, `catalog.curate`, `config.manage`, `policy.manage` or `govpolicy.manage`.
- [ ] Rate limit: Given a principal exceeding `NS_GOV_CHECK_RATE_PER_MINUTE` (burst `NS_GOV_CHECK_BURST`), Then 429 with `Retry-After` and reason `rate_limited` before any store read; the limiter key is the derived principal id, never a header; a body over 4096 bytes or with unknown properties is 413 or 422.
- [ ] Authorization: no role, viewer without the permission, wrong cloud and an expired assignment get 403 and a denial record; the route is in every inventory and boots under `verify_route_permissions`.
- [ ] Verify-first: `docs/integrations/cicd-verification.md` records, from the official GitHub and Microsoft documentation fetched at execution, how a workflow obtains an OIDC token and exchanges it for an Entra token for the NeuroSphere audience through a federated credential, with URLs, retrieval date and what was not confirmed; the Action and recipes use only confirmed steps; if federation cannot be confirmed, the documented fallback is a client secret in the repository secret store and the criterion is recorded OPEN.
- [ ] The Action maps the exit codes 0, 1 and 2 to the job; a network or 401, 403, 429 or 5xx response is exit 2, never 0; the token is never printed (masked); `action.yml` is covered by tests against a local fake server (pass, fail, warn, 429, unreachable, 401).
- [ ] `docs/integrations/cicd.md` documents the API, the exit-code table, the permission and role to grant, the federated-credential setup as operator steps, the Azure DevOps and Jenkins `curl` recipes, and states that a pass is not an approval and that the check does not block anything by itself (the pipeline decides).
- PRP exit: touched suites, `tests/security/authz`, ruff, pyright, `validate_planning.py` pass; PR open, CI green; `services/api/openapi.json` regenerated. The live run is recorded OPEN for PRP-136.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| 1 | Credential for the pipeline | Client secret; workload identity federation | Federation (design U-19), a verify-first item; secret fallback documented only if federation is not confirmed |
| 2 | Permission and role | Reuse `data.read`; new permission; new role | New permission `registration.check`. Decided by the owner 2026-11-16 (GD-45): no dedicated CI role: `registration.check` is granted to the read-class roles (viewer, analyst, domain_steward, admin). Here: The CI principal then also holds `data.read`: stated plainly in the doc. Owner may ask for a dedicated role (a `ci` value in the contract role enum from the next contracts owner) |
| 3 | What "required" means | Product-fixed; configurable | Decided by the owner 2026-11-16 (GD-36): no risk tier requires an approved impact assessment by default (`NS_RISK_ASSESSMENT_REQUIRED_TIERS` empty); the customer sets the list. Here: `NS_GOV_CHECK_FAIL_ON` default `registered,approved,policy_clean`; `risk_assessed` and `safety_evaluated` report but do not fail unless listed; `NS_RISK_ASSESSMENT_REQUIRED_TIERS` default empty, because the product does not say which tiers need an assessment, the customer does |
| 4 | Exit 2 vs result | Align; separate | `result` and `exit_code` follow the PRP-110 contract (exit 0 pass, 1 fail, 2 unknown or error); the Action never turns exit 2 into success unless `fail-on-unknown: false` is set explicitly |
| 5 | Every check audited | Only failures; all | ASSUMPTION: all, one record per call (`governance.registration_check`, ids and codes only), bounded by the rate limit; release evidence matters more than volume |
| 6 | Where the Action lives | `.github/workflows`; `integrations/github-action/` | The latter (Tier-1 workflows avoided); implemented as a composite Action around a stdlib-only Python client so it is testable |
| 7 | Rate-limit scope | Shared store; per replica | Per replica in memory (`TokenBucketLimiter` pattern), so the effective limit is replicas times the setting; documented. A shared limiter is a follow-up if PRP-114 provides one |
| 8 | Azure DevOps and Jenkins | Products; recipes | Recipes only (design section 8, item 13) |

## Context manifest

### Files to read first
- `PRPs/backlog/PRP-110-governance-contracts-b.md` - `RegistrationCheckRequest`/`Response` shapes and the exit-code rule.
- `PRPs/backlog/PRP-108-agent-approval-gate-and-platform-control-actions.md` - `AgentVersion.approval`, `RegistrationCheck`, why executor-only writes.
- `PRPs/backlog/PRP-105-policy-engine-core.md` - `ViolationStore.list`, `PolicyDecider.decide`, `GovernancePolicyPlane`.
- `PRPs/backlog/PRP-127-ai-system-register-tiering-and-impact-assessments.md` - `RiskRegisterReader`.
- `packages/core/neurosphere_core/auth/jwt/validator.py:195-215`, `auth/scope/derivation.py:150-200` - how an app token becomes a service-principal scope.
- `packages/core/neurosphere_core/auth/scope/permissions.py:73-150` - roles, permissions, privileged roles.
- `services/api/neurosphere_api/ingest/limits.py:51-97` - token bucket and `RateLimitedError`.
- `services/api/neurosphere_api/authz/read_audit.py:176-195`, `services/api/neurosphere_api/catalog/dependencies.py:97` - `audited_read`, `entity_access`.
- `docs/validation/lane3-map-copilot-integration.md:39`; `docs/PRD.md:44`.

### Interfaces consumed
- PRP-110: `neurosphere_contracts.policy.v1` `RegistrationCheckRequest`, `RegistrationCheckResponse` (`check` values `registered|approved|policy_clean|risk_assessed|safety_evaluated`, status `pass|fail|warn|not_applicable|unknown`, `reason_code`, `evidence_ref`). Names UNVERIFIED until merged; PRP-110 wins.
- PRP-108: `neurosphere_core.catalog.approval.RegistrationCheck`, `AgentVersion.approval`.
- PRP-105: `neurosphere_core.governance.policy` `ViolationStore`, `GovernancePolicyPlane` on `app.state.governance_policy`, `govpolicy.*` permissions (read only), `ENFORCEMENT_POINT_CAPABILITIES`.
- PRP-127: `RiskRegisterReader.systems_containing`, `.latest_determination`, `.latest_assessment`, `sync_assessment_review`.
- Shipped: `CatalogRepository.get_entity` (scope-filtered), `Permission`, `run_audited_mutation`, `RouterRegistry`, the JWT validator and scope derivation.
- PRP-131 (later): an optional `SafetyRecordReader` port; absent means `unknown`.

### Interfaces provided
- Route `POST /api/v1/governance/checks/registration` (body `RegistrationCheckRequest`, response `RegistrationCheckResponse`, `Cache-Control: no-store`).
- Permission `Permission.REGISTRATION_CHECK = "registration.check"` and its role map.
- Core `neurosphere_core.governance.checks`: `RegistrationChecker.check(scope, request, *, now) -> RegistrationCheckResponse`, the five check functions, `CheckSettings`, ports `ViolationReader`, `RiskReader`, `SafetyReader`, `ApprovalReader`.
- API builder `runtime/builders/governance_checks.py` (`BUILDER`), optional component `governance_checks`, settings `NS_GOV_CHECK_ENABLED` (default true), `NS_GOV_CHECK_FAIL_ON`, `NS_GOV_CHECK_MIN_SEVERITY` (default `high`), `NS_GOV_CHECK_RATE_PER_MINUTE` (60), `NS_GOV_CHECK_BURST` (20), `NS_RISK_ASSESSMENT_REQUIRED_TIERS` (empty).
- Audit operation `governance.registration_check`; denial and rate-limit records as for other routes.
- `integrations/github-action/` (`action.yml`, `check.py`, `README.md`, `examples/workflow.yml`), `docs/integrations/cicd.md`, `docs/integrations/cicd-verification.md`.

### Patterns to match
- Audited read dependency and denial recording: `services/api/neurosphere_api/authz/read_audit.py:176-195`.
- Token bucket and 429 with wait: `services/api/neurosphere_api/ingest/limits.py:51-97`.
- Optional builder component: `services/api/neurosphere_api/runtime/builders/edge.py:17-27`.
- Same-answer for missing and forbidden: `services/api/neurosphere_api/catalog/dependencies.py:97`.
- Stdlib HTTP client plus fake-server test: ingest producer tests `services/api/tests/ingest`.

### Gotchas
- The scope is server-derived; `customer_id`, domain and cloud are never read from the body. Look up the entity only inside domains where the caller holds `registration.check`, so a foreign entity is indistinguishable from a missing one.
- `TokenBucketLimiter.acquire` raises a message saying "Producer rate limit exceeded." (`ingest/limits.py:67-77`): translate it, do not leak the wording or reuse the producer reason code.
- PRP-70 adds `AgentVersion.semver` (`PRPs/backlog/PRP-70-contracts-revision-restored-scope.md:93`); `config_hash` already exists (`catalog/v1/agent_version.schema.json:86-97`). A request with `agent_id` plus `semver` resolves the version; ambiguity (two versions with one semver) is `fail` `ambiguous_version`.
- `tests/integration/` exists; the Action tests live in `tests/cicd_gate/` to avoid a confusing near-duplicate and a shadowed package.
- A new top-level test root would need `pyproject.toml` testpaths and the CI shard matrix; `tests/` is already a root.
- Do not pin Action or tool versions from memory in the sample workflow: pin by commit hash found at execution.
- Never log the bearer token, the request body's `run_ref` at info level, or an entity title.
Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - packages/core/neurosphere_core/governance/checks/**
  - packages/core/tests/governance_checks/**
  - services/api/neurosphere_api/governance/checks/**
  - services/api/neurosphere_api/runtime/builders/governance_checks.py
  - services/api/tests/governance_checks_api/**
  - integrations/github-action/**
  - tests/cicd_gate/**
  - tests/security/authz/test_registration_check.py
  - docs/integrations/cicd.md
  - docs/integrations/cicd-verification.md
tier1: []
tier2_appends:
  - packages/core/neurosphere_core/auth/scope/permissions.py
  - packages/core/tests/auth/scope/test_roles.py
  - tests/security/authz/test_privileged_roles.py
  - services/api/neurosphere_api/routers.py
  - services/api/neurosphere_api/runtime/builders/__init__.py
  - services/api/neurosphere_api/runtime/status.py
  - services/api/neurosphere_api/authz/routes.py
  - services/api/tests/authz/test_route_inventory.py
  - services/api/tests/authz/test_startup_route_check.py
  - services/api/tests/runtime_routes/manifest_calls.py
  - tests/integration/real_stack/test_manifest_routes.py
  - mkdocs.yml
must_not_touch:
  - packages/contracts/**
  - packages/core/neurosphere_core/actions/**
  - packages/core/neurosphere_core/governance/policy/**
  - packages/core/neurosphere_core/catalog/**
  - packages/core/neurosphere_core/risk/**
  - services/api/neurosphere_api/catalog/**
  - services/api/neurosphere_api/governance/policy/**
  - services/api/neurosphere_api/governance/decide/**
  - .github/workflows/**
```

## Implementation blueprint

Parallelization: item 1 first; items 2 and 5 [P] after 1 (core and Action share no file, the Action only needs the contract shape); 3 after 2; 4 after 3; 6 after 4 and 5; 7 after 6; 8 last.

### Item 1 - Verify-first: workload identity federation for CI
- Deliverable: `docs/integrations/cicd-verification.md` from the official GitHub documentation (OIDC tokens in workflows) and Microsoft Learn (federated identity credential for an app registration, the workflow login step, Government cloud availability), each with URL, retrieval date, what was confirmed and what was not; the audience and subject-claim guidance written only from those pages. The orchestrator fetches and pastes into briefs (subagents lack Learn access).
- Owned files: `docs/integrations/cicd-verification.md`.
- Depends on: PRP-108, PRP-105, PRP-127 merged.
- Acceptance criteria: criterion 7; every later statement about tokens cites this file; Government availability is stated as confirmed or unconfirmed.
- Tests: `tests/docs` link check if present.
- Pattern references: `docs/connectors/verification/` template from PRP-117.

### Item 2 - Core check engine  [P]
- Deliverable: `neurosphere_core.governance.checks` with the five check functions, decision table, `CheckSettings`, readers as ports with in-memory fakes, reason-code vocabulary, and the no-oracle lookup rule.
- Owned files: `packages/core/neurosphere_core/governance/checks/**`, `packages/core/tests/governance_checks/**`.
- Must NOT touch: policy, risk and catalog packages.
- Depends on: item 1.
- Acceptance criteria: criteria 2, 3, 4 (pure part); every status and reason code is covered; the module imports no executor, catalog service or HITL symbol (import test).
- Tests: `packages/core/tests/governance_checks/test_decision_table.py`, `test_checks.py`, `test_no_oracle.py`, `test_import_boundary.py`.
- Pattern references: `packages/core/neurosphere_core/compliance/sources/base.py` (read-only ports).

### Item 3 - API route, permission, rate limit, audit
- Deliverable: router and dependencies for `POST /api/v1/governance/checks/registration`; `registration.check` permission and role map; per-principal limiter; size and schema limits; audit record per call.
- Owned files: `services/api/neurosphere_api/governance/checks/**`, `services/api/tests/governance_checks_api/**`, Tier-2 permission lines and role tests.
- Depends on: item 2.
- Acceptance criteria: criteria 1, 5, 6; denial and 429 recorded; `Cache-Control: no-store`.
- Tests: `services/api/tests/governance_checks_api/test_route.py`, `test_rate_limit.py`, `test_limits.py`.
- Pattern references: `authz/read_audit.py:176-195`, `ingest/limits.py:51-97`.

### Item 4 - Composition
- Deliverable: `runtime/builders/governance_checks.py` binding the real readers (PRP-105 plane, PRP-108 `RegistrationCheck`, PRP-127 reader, optional safety reader) with a reason code when a plane is absent (the check then reports `unknown`, never `pass`); Tier-2 appends; update the pinned tests listed in the reference (readiness, builder order).
- Owned files: the builder module, Tier-2 lines, `services/api/tests/runtime_api/test_readiness.py` edits.
- Depends on: item 3.
- Acceptance criteria: with `NS_GOV_CHECK_ENABLED=false` the route is absent; with the policy plane absent the `policy_clean` status is `unknown` with `policy_plane_unavailable`.
- Tests: `services/api/tests/runtime_api`, `runtime_routes`, `runtime_data`, `runtime_gateway_builder`.
- Pattern references: `runtime/builders/edge.py:17-27`.

### Item 5 - GitHub Action and client  [P]
- Deliverable: `integrations/github-action/{action.yml,check.py,README.md,examples/workflow.yml}`: a composite Action running a stdlib-only client (bounded timeout, one retry on connection error only, no redirects to other hosts, token masked, outputs `result`, `exit-code`, `check-id`, `reasons`), an optional step to compute `config_hash` from a file, and the exit-code contract table.
- Owned files: `integrations/github-action/**`, `tests/cicd_gate/**`.
- Must NOT touch: `.github/workflows/**`.
- Depends on: item 1.
- Acceptance criteria: criterion 8; the sample workflow requests only the permissions the verified flow needs and names no secret.
- Tests: `tests/cicd_gate/test_client.py` (fake server: pass, fail, warn, 429, 401, unreachable, oversize response), `test_action_yaml.py` (inputs and outputs declared, no token echo).
- Pattern references: ingest producer tests for a local fake server.

### Item 6 - Documentation and recipes
- Deliverable: `docs/integrations/cicd.md` (API, exit codes, permission and role, operator steps for the federated credential, Azure DevOps and Jenkins `curl` recipes, limits, what a pass means) and the mkdocs nav line; the recipes pass the same body and treat exit 2 as failure.
- Owned files: `docs/integrations/cicd.md`, `mkdocs.yml` line.
- Depends on: items 4 and 5.
- Acceptance criteria: criterion 9; the no-claim scan (`scan_for_claims`) passes; no sentence says a pass approves or certifies.
- Tests: docs link and nav tests (`tests/docs`).
- Pattern references: `docs/runbooks/ingest.md`.

### Item 7 - Authorization and no-bypass suite
- Deliverable: ABAC deny cases, the no-oracle comparison (missing vs foreign vs cross-cloud), the executor-isolation and role-permission tests of criterion 4, token-leak test over logs and audit payloads.
- Owned files: `tests/security/authz/test_registration_check.py`.
- Depends on: item 6.
- Acceptance criteria: criteria 3, 4, 5, 6.
- Tests: `tests/security/authz`.
- Pattern references: PRP-41 item 5.

### Item 8 - Integration and close-out
- Deliverable: Tier-3 regeneration (`openapi.json`, `docs/reference/**`, status table, `PRPs/INDEX.md`), changelog fragment `changelog.d/PRP-129-cicd-registration-and-policy-gate.md`, completion note with the operator steps and the OPEN live run.
- Owned files: this PRP file, Tier-3 files.
- Depends on: items 1-7.
- Acceptance criteria: gates pass; CI green.

## Validation gates
```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q packages/core/tests/governance_checks packages/core/tests/auth services/api/tests/governance_checks_api services/api/tests/runtime_api services/api/tests/runtime_routes services/api/tests/runtime_data services/api/tests/runtime_gateway_builder services/api/tests/authz tests/security/authz tests/cicd_gate tests/docs services/api/tests/test_openapi_drift.py tests/docs/test_reference_coverage.py
python scripts/prp_status.py --check
python scripts/validate_planning.py
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```

## Migration and rollback
No data migration: one route, one permission, an audit operation and new files. `NS_GOV_CHECK_ENABLED=false` removes the route; reverting the PR removes the permission (role tests revert with it). Pipelines that call it get 404 and, by the Action contract, exit 2. Nothing is stored except audit records.

## Live and open gates
Needs an operator and `NS_LIVE_APPROVED=1`: an Entra app registration with a federated credential, a role assignment for the CI principal, and one workflow run in a real repository against a deployed environment. Recorded OPEN here and handed to PRP-136; offline tests use a fake server and in-memory readers.

## NOT building
Blocking inside the pipeline or the platform (the pipeline decides what to do with the answer); approving, activating, suspending or waiving anything (PRP-108); a bypass token or "pre-approved" flag; any claim that a pass means compliant, certified, authorized or safe; Azure DevOps or Jenkins extensions (recipes only); storing check results for later retrieval; a shared cross-replica rate limiter; checks of tools, MCP servers or model deployments (versions only); legal risk classification (the tier is the customer's record); an SDK-side guard (PRP-114).

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [ ] All clarification questions are decided, not guessed (rows 2, 3, 5 and 7 are ASSUMPTIONS for plan approval; token exchange is UNVERIFIED until item 1)

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
- OPEN gates: live run in a real repository, federated credential, Government availability.
- Env vars for the operator: `NS_GOV_CHECK_ENABLED`, `NS_GOV_CHECK_FAIL_ON`, `NS_GOV_CHECK_MIN_SEVERITY`, `NS_GOV_CHECK_RATE_PER_MINUTE`, `NS_GOV_CHECK_BURST`, `NS_RISK_ASSESSMENT_REQUIRED_TIERS`.
- Follow-up issues:
- Product check (can an operator use it without editing files): a pipeline author copies the sample workflow and an admin assigns the CI principal a role; no file edit in NeuroSphere.
