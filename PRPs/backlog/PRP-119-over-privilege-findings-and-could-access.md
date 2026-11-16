---
name: PRP-119-over-privilege-findings-and-could-access
status: backlog
priority: P1
order: 119
review: required
created: 2026-11-16
model: sonnet
orchestrator_model: sonnet
implementer_model: sonnet
phase: 9
ns: NS-02, NS-03, NS-08
depends_on: [PRP-118-agent-identity-and-entra-entitlements, PRP-73-graph-access-and-sensitivity-questions, PRP-105-policy-engine-core, PRP-61-configuration-detections-and-shadow-ai-discovery, PRP-120-purview-labels-classifications-and-lineage]
wave: W29
branch: prp-119-over-privilege-could-access
allow_parallel: true
issues: []
---

# PRP-119: Over-privilege findings and "who could access"

## Goal
Turn the run-as identities and entitlements of PRP-118 into answers a security lead can act on. Three things ship. First, "who could touch data of sensitivity X" beside PRP-73's "who did": a bounded walk from data assets back through `entitled_to` and `runs_as` to the agents, tools, services and MCP servers whose identity holds an entitlement, filtered by the effective sensitivity of PRP-120, and always shown with the coverage of the entitlement collection, because entitlements inside data services are mostly out of reach (design section 8 item 8). Second, two advisory findings in the existing recommendations list: "entitled, never used in the window" (`unused_entitlement`) and "write entitlement, only reads observed" (`excess_write_entitlement`), each with evidence ids and only where both the entitlement and the usage evidence are actually known. Third, the `identity_entitlement` policy rule evaluator, so a published policy such as "no unapproved agent may hold write access to PII" produces violations through PRP-105's engine. It is for the security lead and the compliance officer; nothing here blocks or revokes anything.

Out of scope: collecting identities and entitlements (PRP-118); Purview and Unity labels and the precedence rule (PRP-120, PRP-121); the policy engine, violations, exceptions and the policy UI (PRP-105, PRP-106); the `unused_entitlement` and `excess_write_entitlement` contract kinds and `IdentityEntitlementParams` (PRP-110); shadow-AI findings (PRP-126); revoking or reducing an entitlement (a customer action in their identity provider; never built here); alert rules on findings (PRP-132).

## Why
- PRP-73 answers "who did" from observed `reads` and `writes` edges and reserves `catalog/access/could/**` for this PRP (design section 6 row 73; PRP-73 "Interfaces provided"). Nothing answers "who could": there is no entitlement data before PRP-118 (`packages/core/neurosphere_core/catalog/protocol.py:70-97` has no identity type or relation).
- The original PRD stories PRP-73 restores ask exactly this: 5b "which agents have write access to the customer database" (`git show 9fbf5f4c:docs/PRD.md`, quoted in `PRPs/backlog/PRP-73-graph-access-and-sensitivity-questions.md:30`). Observed writes answer only part of "have write access".
- The recommendation `Kind` filter knows six kinds (`services/api/neurosphere_api/recommendations/router.py:51-58`); no finding is about privilege. The `identity_entitlement` rule kind is declared by PRP-110 and has no evaluator: PRP-105 reports it `evaluator_unavailable` and refuses to publish a policy that uses it (`PRPs/backlog/PRP-105-policy-engine-core.md:44`).
- Owner direction 2026-11-16: "the ultimate team AI governance and auditing tool", every identified gap planned; design G-c ("nothing answers who could") and the PRP-119 entry.

## Acceptance criteria
- [ ] Given assets with effective sensitivity `pii` (steward value or mapped customer label) and agents whose run-as identities hold `entitled_to` edges to them, When `POST /api/v1/catalog/access/could` asks for `sensitivity_categories: ["pii"]` and `min_access: "write"`, Then every in-scope subject is returned with the identity, entitlement (`grant_kind`, `role_or_permission`, `access`, `plane`, `scope_ref`, `source`, `last_observed`), the asset, its `sensitivity_source`, and a `did` flag that says whether PRP-73's observed edges show use in the window; an out-of-scope subject, identity or asset never appears, not even as a count.
- [ ] Every "who could" response carries `coverage`: identities in scope by collection state (`collected`, `partial`, `not_collected`, `failed`, `declared_only`), subjects with no run-as identity, planes collected, connector freshness, PRP-120's `label_coverage`, and the fixed statement that data-plane permissions inside data services are mostly not collected; when coverage is not full the UI and the response say "partial", never "complete" or "no one".
- [ ] Bounds: at most `MAX_COULD_ASSETS` assets and `MAX_COULD_ROWS` rows, depth fixed at asset <- entitlement <- identity <- runs_as <- subject; `truncated` and `truncated_reason` as PRP-73; request values can only lower the ceilings.
- [ ] Given an entitlement on a target with a usage signal (grounding source: `reads`/`writes`; model deployment: `uses_model`) and a subject that has telemetry in the window but no use of that target for `NS_WORKER_DETECT_UNUSED_ENTITLEMENT_DAYS`, When the `detections` role ticks, Then one `unused_entitlement` recommendation exists (`advisory: true`, `method: rule`, no `score`, evidence: the entitlement edge, the identity, the run-as edge); a subject with no telemetry in the window, an identity not `collected`, or a target type with no usage signal (MCP server, service) produces no finding and is counted by reason.
- [ ] Given a `write` or `admin` entitlement on a grounding source and only `reads` observed in the window, Then one `excess_write_entitlement` recommendation exists with the same evidence rules; findings are de-duplicated by deterministic id and expire when the condition is gone.
- [ ] Given a published policy with an `identity_entitlement` rule (`access: write`, `plane: any`, `sensitivity_categories: ["pii"]`, `allowed_when: agent_version_approved`), When `policy_eval` ticks, Then a violation exists for each subject whose agent version is not approved and that could write PII, with evidence ids; with `unused_for_days` set, only unused entitlements violate; the rule is no longer `evaluator_unavailable` and a policy using it publishes in dry run.
- [ ] The route needs `data.read`, derives scope from the server identity, ignores body-supplied customer, cloud or domain, writes one `audited_read` record (operation `catalog.could_access`, domains and count only); deny cases pass for no role, wrong domain, wrong customer, wrong cloud and expired assignment.
- [ ] The access page gains a "Who could" panel beside "Who did" with the coverage banner, the label banner, a partial-result banner, and links from a finding to its evidence; axe passes in three themes; no string says an estate is "least privilege", "secure" or "compliant".
- PRP exit: touched suites, `tests/security/authz`, ruff, pyright, `validate_planning.py` pass; PR open with CI green; `openapi.json` regenerated.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| 1 | What counts as "used" | Any telemetry; edge to the target | Observed catalog edge from the subject to the target in the window: `reads`/`writes` for grounding sources, `uses_model` for model deployments (relation endpoints checked in `catalog/v1/{reads,writes,uses_model}.schema.json`). `invokes` does not target `mcp_server`, so MCP servers and services have no usage signal and get no "unused" finding |
| 2 | When "never used" may be claimed | Always; only with activity evidence | Decided by the owner 2026-11-16 (GD-34): "never used" is claimed only with activity evidence covering the window, default 30 days. Here: only when the subject has telemetry in the window (`SubjectMetricsReader`) and its identity is `collected`; otherwise counted as `no_activity_evidence` or `entitlement_not_collected`. Absence of evidence is never a finding |
| 3 | Window | Fixed; setting | Decided by the owner 2026-11-16 (GD-34): "never used" is claimed only with activity evidence covering the window, default 30 days. Here: `NS_WORKER_DETECT_UNUSED_ENTITLEMENT_DAYS`, default 30, bounded 1-365 |
| 4 | Where findings live | New store; recommendations | Recommendation kinds `unused_entitlement`, `excess_write_entitlement` (PRP-110) through PRP-61's `finding_to_recommendation` and the `detections` role |
| 5 | Who may ask "who could" | `data.read`; new permission | Decided by the owner 2026-11-16 (GD-32): "who could" answers are readable with `data.read`, like PRP-73's "who did" answers. Here: as PRP-73's sibling routes; entitlement data is security-relevant, so the owner may prefer a stricter permission (for example `security_auditor` only) |
| 6 | Sensitivity used | Asset's own field; effective value | PRP-120's `effective_sensitivity` (GD-11 precedence), so customer labels count; null stays unassessed and is reported with `include_unassessed` as in PRP-73 |
| 7 | Evaluator registration | Edit PRP-105 code; registry | Registers through PRP-105's evaluator extension point as one new plugin file, `governance/policy/rule_plugins/identity_entitlement.py`; no shared assembly or builder file is edited and no Tier-1 grant is needed |

## Context manifest

### Files to read first
- `PRPs/backlog/PRP-118-agent-identity-and-entra-entitlements.md` "Interfaces provided" - `identity_view`, collection attributes, unions.
- `PRPs/backlog/PRP-73-graph-access-and-sensitivity-questions.md` "Interfaces provided" - `AccessEngine`, bounds, truncation, page.
- `PRPs/backlog/PRP-120-purview-labels-classifications-and-lineage.md` "Interfaces provided" - `effective_sensitivity`, `label_coverage`, `LabelSourceBanner`.
- `PRPs/backlog/PRP-105-policy-engine-core.md` "Interfaces provided" - `RuleEvaluator`, `RuleEvaluatorRegistry`, `RuleOutcome`.
- `PRPs/backlog/PRP-61-configuration-detections-and-shadow-ai-discovery.md` "Interfaces provided" - `DetectionRule`, `Finding`, `finding_to_recommendation`, role.
- `PRPs/backlog/PRP-110-governance-contracts-b.md` - `Entitlement`, `IdentityEntitlementParams`, the two finding kinds.
- `packages/core/neurosphere_core/catalog/graph/query.py` - scope rule in `_walk`; `packages/core/neurosphere_core/catalog/protocol.py:199-280` - `list_edges_by_node`, `get_entity`.
- `packages/core/neurosphere_core/aggregates/subject.py:35-65` - `SubjectMetricsReader` for activity evidence.
- `services/api/neurosphere_api/recommendations/router.py:51-58` - `Kind` literal.

### Interfaces consumed
- PRP-118 (W27): `WorkloadIdentity` with `attributes.entitlement_collection`, `entitlement_collected_at`, `entitlement_planes`; `RunsAs`, `EntitledTo` edges; `identity_view`.
- PRP-73 (W20): `AccessEngine`, `AccessQuery` filters, `MAX_ASSET_PAGES`, truncation reasons, page at `frontend/src/features/catalog/access/`, mock handlers.
- PRP-120 (W27): `effective_sensitivity`, `LabelCoverage`, `LabelSourceBanner`.
- PRP-105 (W21): `RuleEvaluator`, `RuleEvaluatorRegistry`, `RuleOutcome`, `PolicyEvaluator` run context, violation de-duplication.
- PRP-61 (W28): `DetectionRule`, `Finding`, `finding_to_recommendation`, role `detections`, settings prefix `NS_WORKER_DETECT_`.
- PRP-117 (W26): `ConnectorStatusRepository` (connector freshness for coverage).
- PRP-110 (W25): `IdentityEntitlementParams`, recommendation kinds `unused_entitlement`, `excess_write_entitlement`.
- Shipped: `audited_read`, `SubjectMetricsReader` (PRP-49), `RecommendationStore`.

### Interfaces provided
- Core `neurosphere_core.catalog.graph.entitlement_access`: `CouldQuery`, `CouldRow`, `CollectionCoverage`, `CouldResult`, `CouldAccessEngine.who_could(scope, query) -> CouldResult`, `MAX_COULD_ASSETS`, `MAX_COULD_ROWS`, `DATA_PLANE_STATEMENT`.
- Core `neurosphere_core.detections.over_privilege`: `UnusedEntitlementRule`, `ExcessWriteEntitlementRule` (generator ids `detect.unused_entitlement`, `detect.excess_write_entitlement`, versioned).
- Core `neurosphere_core.governance.identity_entitlement`: `IdentityEntitlementEvaluator` (kind `identity_entitlement`).
- Route `POST /api/v1/catalog/access/could` (`data.read`, alias `/catalog/access/could`); audit operation `catalog.could_access`.
- Worker setting `NS_WORKER_DETECT_UNUSED_ENTITLEMENT_DAYS`.
- Frontend `frontend/src/features/catalog/access/could/` (`CouldPanel`), mock handlers `frontend/tests/mock-api/features/catalog-access-could.ts`.

### Patterns to match
- Bounded scan with truncation: PRP-73 `catalog/graph/access.py`; `services/api/neurosphere_api/catalog/service.py:562-602`.
- Detection rule and recommendation conversion: PRP-61 `packages/core/neurosphere_core/detections/` and PRP-126's `detections/shadow_ai/` (sibling extension in the same wave).
- Rule evaluator with `truncated` outcome: PRP-105 `governance/policy/rules/`.
- Router with alias and read audit: PRP-73 `services/api/neurosphere_api/catalog/access/router.py`.

### Gotchas
- No external API is called here; the UNVERIFIED facts that limit this PRP are PRP-118's U-7 and U-8: if the directory or ARM reads were not verified, every identity is `declared_only` or `not_collected`, and "who could" returns coverage with no rows rather than an empty "no one".
- An inherited entitlement (scope above the asset) arrives as an ordinary `entitled_to` edge with the original `scope_ref` (PRP-118 Gotchas); show `scope_ref` so a reader sees "subscription-wide", not a per-asset grant.
- A rejected (hidden) edge must not count as an entitlement or as usage; present edges through `rules.present_edge` like PRP-73.
- Two PRPs in W29 append to `detections/role.py` (this one and PRP-126) and nobody else edits it: one line each, keep both at rebase.
- `frontend/src/features/recommendations/types.ts` (`RECOMMENDATION_KINDS`, PRP-61) and the `Kind` literal are additive lines; labels come from PRP-110's `KIND_LABELS`.
- Activity evidence uses agent subject points; tools and services gain subject points only from PRP-100; without them, tool and service subjects never get an "unused" finding.
Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - packages/core/neurosphere_core/catalog/graph/entitlement_access.py
  - packages/core/tests/catalog_could_access/**
  - packages/core/neurosphere_core/detections/over_privilege/**
  - packages/core/tests/detections_over_privilege/**
  - services/workers/neurosphere_workers/detections/over_privilege/**
  - services/workers/tests/detections_worker/test_over_privilege_wiring.py
  - packages/core/neurosphere_core/governance/policy/rule_plugins/identity_entitlement.py
  - packages/core/tests/governance_identity_entitlement/**
  - services/api/neurosphere_api/catalog/access/could/**
  - services/api/tests/catalog_could_access_api/**
  - tests/security/authz/test_catalog_could_access*.py
  - frontend/src/features/catalog/access/could/**
  - frontend/tests/mock-api/features/catalog-access-could.ts
  - docs/runbooks/over-privilege.md
  - changelog.d/PRP-119-over-privilege-findings-and-could-access.md
tier1: []
tier2_appends:
  - services/workers/neurosphere_workers/detections/role.py
  - services/workers/neurosphere_workers/detections/settings.py
  - services/api/neurosphere_api/recommendations/router.py
  - frontend/src/features/recommendations/types.ts
  - frontend/src/features/catalog/access/**
  - services/api/neurosphere_api/routers.py
  - services/api/neurosphere_api/authz/routes.py
  - services/api/tests/authz/test_route_inventory.py
  - services/api/tests/authz/test_startup_route_check.py
  - services/api/tests/runtime_routes/manifest_calls.py
  - tests/integration/real_stack/test_manifest_routes.py
  - frontend/tests/mock-api/features/index.ts
  - mkdocs.yml
must_not_touch:
  - packages/contracts/**
  - packages/core/neurosphere_core/catalog/graph/access.py
  - packages/core/neurosphere_core/catalog/identity/**
  - packages/core/neurosphere_core/catalog/labels/**
  - packages/core/neurosphere_core/governance/policy/rules/**
  - packages/core/neurosphere_core/detections/shadow_ai/**
  - packages/core/neurosphere_core/detections/rules/**
  - connectors/reference/**
  - services/workers/neurosphere_workers/runtime/factories.py
```
The `frontend/src/features/catalog/access/**` line is one mount line for `CouldPanel` in PRP-73's page. The evaluator is the new plugin file `rule_plugins/identity_entitlement.py` (module `build(ctx: RuleBuildContext) -> RuleEvaluator | None`), discovered by PRP-105's `RuleEvaluatorRegistry.discover`, so no worker or API assembly file is edited (`runtime/builders/governance.py` and `policy_eval/assembly.py` are not touched) and nothing is `[serial-after]`.

## Implementation blueprint

Parallelization: items 1, 2 and 3 [P] (disjoint packages, all read the catalog through `CatalogRepository`). Item 4 after 1. Item 5 after 4. Item 6 after 3. Item 7 last.

### Item 1 - "Who could" engine  [P]
- Deliverable: `entitlement_access.py`: bounded scan of in-scope assets by effective sensitivity (PRP-120), `entitled_to` edges in, identities re-fetched through `get_entity`, `runs_as` edges in to subjects, `did` flag from PRP-73 edges in the window, `CollectionCoverage` from identity attributes and PRP-117 status, truncation.
- Owned files: `packages/core/neurosphere_core/catalog/graph/entitlement_access.py`, `packages/core/tests/catalog_could_access/**`.
- Must NOT touch: `catalog/graph/access.py`, `catalog/identity/**`.
- Depends on: PRP-118 and PRP-120 merged.
- Acceptance criteria: criteria 1 to 3; out-of-scope ids never surface; null sensitivity never treated as none.
- Tests: `test_who_could.py`, `test_coverage.py`, `test_truncation.py`, `test_inherited_scope.py`, `test_scope_leak.py` (two-domain world, in-memory repository).
- Pattern references: PRP-73 `access.py`; `catalog/graph/query.py` `_walk`.

### Item 2 - Over-privilege detection rules  [P]
- Deliverable: `detections/over_privilege/` (`unused.py`, `excess_write.py`, `readers.py` protocols) as `DetectionRule`s; worker readers in `services/workers/neurosphere_workers/detections/over_privilege/` (catalog reader, subject activity reader); one rule-list line in `detections/role.py`; the window setting in `detections/settings.py`; `Kind` literal lines and `RECOMMENDATION_KINDS` lines.
- Owned files: the two `over_privilege/` packages, `packages/core/tests/detections_over_privilege/**`, `services/workers/tests/detections_worker/test_over_privilege_wiring.py`; Tier-2 lines.
- Must NOT touch: PRP-61's rules and `finding.py`, PRP-126's `shadow_ai/`.
- Depends on: PRP-61 and PRP-118 merged.
- Acceptance criteria: criteria 4 and 5; counted reasons `no_activity_evidence`, `entitlement_not_collected`, `usage_signal_unavailable`.
- Tests: `packages/core/tests/detections_over_privilege/test_unused.py`, `test_excess_write.py`, `test_no_finding_without_evidence.py`; the wiring test; re-run `services/workers/tests/detections_worker`.
- Pattern references: PRP-61 `detections/rules/`, PRP-126 `detections/shadow_ai/`.

### Item 3 - `identity_entitlement` evaluator  [P]
- Deliverable: `governance/policy/rule_plugins/identity_entitlement.py` (new plugin file) implementing `RuleEvaluator` over `CouldAccessEngine` semantics (shared helper, no duplicate walk) and the approval state of the subject's agent version; `RuleOutcome` with evidence ids and `truncated`; its `build(ctx)` returns the evaluator, or `None` when the catalog is not configured (the worker and the API both discover it through PRP-105's extension point).
- Owned files: `packages/core/neurosphere_core/governance/policy/rule_plugins/identity_entitlement.py`, `packages/core/tests/governance_identity_entitlement/**`.
- Must NOT touch: any other file under `governance/policy/**`.
- Depends on: PRP-105 and PRP-118 merged; uses item 1's engine at integration (stub the engine in unit tests until item 1 lands).
- Acceptance criteria: criterion 6 (worker part); a truncated walk returns `truncated` so PRP-105 resolves nothing.
- Tests: `test_evaluator.py`, `test_allowed_when.py`, `test_unused_for_days.py`; re-run `services/workers/tests/policy_eval_worker`.
- Pattern references: PRP-105 `governance/policy/rules/`.

### Item 4 - API route
- Deliverable: `catalog/access/could/{__init__,router,models}.py`, `audited_read(Permission.DATA_READ, "catalog.could_access")`, ceilings, 422 reason codes, registration with alias; inventories.
- Owned files: `services/api/neurosphere_api/catalog/access/could/**`, `services/api/tests/catalog_could_access_api/**`, `tests/security/authz/test_catalog_could_access.py`; Tier-2 lines.
- Depends on: item 1.
- Acceptance criteria: criterion 7.
- Tests: `services/api/tests/catalog_could_access_api/test_route.py`, `test_read_audit.py`; `tests/security/authz/test_catalog_could_access.py`.

### Item 5 - "Who could" panel
- Deliverable: `CouldPanel` (question presets "who could write PII", "who could read EU data", free filters), result table with entitlement, scope, source, `did` column, coverage banner, PRP-120 label banner; mount line in the access page; mock handlers incl. a partial-coverage fixture.
- Owned files: `frontend/src/features/catalog/access/could/**`, `frontend/tests/mock-api/features/catalog-access-could.ts`; one mount line.
- Depends on: item 4.
- Acceptance criteria: criterion 8.
- Tests: `frontend/src/features/catalog/access/could/could.test.tsx`.

### Item 6 - Evaluator registration check
- Deliverable: a test that the API status route and the publish dry run see `identity_entitlement` as evaluable once this PRP is installed (the evaluator is discovered through PRP-105's evaluator extension point, as is the worker), and that a policy using it publishes in `audit` mode. No registration line is added to any shared file.
- Owned files: tests only (`packages/core/tests/governance_identity_entitlement/**`, `services/api/tests/governance_policy_api` additions).
- Depends on: item 3.
- Acceptance criteria: criterion 6 (publish part).
- Tests: `services/api/tests/governance_policy_api` (status and publish dry run with the new kind).

### Item 7 - Integration and close-out
- Deliverable: runbook `docs/runbooks/over-privilege.md` (what each finding means and does not mean, the activity-evidence rule, coverage, the data-plane statement, that remediation is the customer's action); Tier-2 appends; Tier-3 regeneration after rebase; changelog fragment; completion note.
- Owned files: the runbook, the fragment, this PRP file, Tier-3 outputs.
- Depends on: items 1 to 6.
- Acceptance criteria: validation gates pass; CI green.

## Cut line
If item 6 slips, items 1 to 5 and 7 still merge safely: findings and "who could" work and the evaluator is discovered by the worker and the API through PRP-105's extension point.

## Validation gates
```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q packages/core/tests/catalog_could_access packages/core/tests/detections_over_privilege packages/core/tests/governance_identity_entitlement packages/core/tests/catalog_access packages/core/tests/governance_policy services/workers/tests/detections_worker services/workers/tests/policy_eval_worker services/api/tests/catalog_could_access_api services/api/tests/governance_policy_api services/api/tests/runtime_data services/api/tests/runtime_routes services/api/tests/authz tests/security/authz services/api/tests/test_openapi_drift.py tests/docs/test_reference_coverage.py
pnpm --filter @neurosphere/frontend lint
pnpm --filter @neurosphere/frontend typecheck
pnpm --filter @neurosphere/frontend test
python scripts/prp_status.py --check
python scripts/validate_planning.py
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```

## Migration and rollback
No data migration: findings are ordinary recommendations that expire; violations follow PRP-105's lifecycle. Rollback: remove the two rules from the detections role (findings expire), retire policies that use `identity_entitlement`, or revert the PR. The route holds no state.

## Live and open gates
None run here: everything is proven on the in-memory catalog with fixture identities. The quality of real answers depends on PRP-118's live Graph and ARM read, which is OPEN and handed to PRP-136.

## NOT building
Complete entitlements: data-plane permissions inside data services are mostly not collected, and every answer says so (design section 8 item 8). Revoking, reducing or right-sizing an entitlement, or proposing it as an executor action (the target is the customer's identity provider; no write connector exists). Any statement that an estate is least-privilege, secure or compliant. Blocking access. Shadow-AI discovery (PRP-126). Inferring an entitlement from usage.

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [ ] All clarification questions are decided, not guessed (rows 2, 3 and 5 are ASSUMPTIONS for plan approval)

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
- Follow-up issues:
- Product check (can a security lead ask "who could write PII" and see how complete the answer is, without reading code):
