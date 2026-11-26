---
name: PRP-105-policy-engine-core
status: active
started: 2026-11-25
execution: session
max_lanes: 2
priority: P0
order: 105
review: required
created: 2026-11-16
model: opus
orchestrator_model: opus
implementer_model: opus
phase: 9
ns: NS-02, NS-04, NS-06, NS-08
depends_on: [PRP-99-governance-contracts-a, PRP-73-graph-access-and-sensitivity-questions]
wave: W21
branch: prp-105-policy-engine-core
allow_parallel: true
issues: []
---

# PRP-105: Governance policy engine core (definitions, evaluator, violations, exceptions, decide)

## Goal
Give NeuroSphere a real policy engine. A policy is a versioned, declarative document made of typed rules from a closed list (no expression language, no generated code); a worker evaluates every published policy as bounded queries over the catalog graph, the aggregates and (once bound) interaction findings, and writes de-duplicated violation records with evidence ids; a violation can get a time-boxed exception through the existing HITL `policy_exception` review kind; each published policy is projected onto the catalog `Policy` entity so it appears in lineage; and one in-process decision function, `decide`, answers "allow, deny or audit" for the enforcement points that later PRPs build. Publishing and retiring a policy and changing an enforcement mode are action-executor intents with confirmation, approval and audit, never direct writes; every enforcement binding starts in `audit`. It is for domain stewards and admins who need "the ultimate team AI governance and auditing tool" (owner, 2026-11-16) and for the eleven later PRPs that consume these interfaces (106, 108, 112 to 116, 119, 129, 132). It runs in W21, after PRP-99 (contracts); PRP-102 declares the three containers in the same wave, so item 1 is `[serial-after: PRP-102]`.

Out of scope: the contracts (PRP-99 owns `policy/v1`); the container declarations (PRP-102, W21 stores owner); the platform-control write target that actually executes publish, retire and mode changes (PRP-108; until it lands the intents drafted here are advisory and say so); the policy UI (PRP-106); gateway compilation (PRP-112); the tool-call hook (PRP-113); the workload decision API and SDK guard (PRP-114); the `budget` rule evaluator (PRP-115), `identity_entitlement` (PRP-119) and `required_attestation` (PRP-130); notification delivery of violation events (PRP-107 binds its publisher to the sink defined here); copilot and MCP governance tools (PRP-116).

## Why
- The catalog `Policy` entity exists (`packages/contracts/schemas/catalog/v1/policy.schema.json:67` `policy_kind`, `:79` `policy_version`, `:84` `enforcement` enforced/advisory/disabled, `:106` `document_ref`) and no Python outside the contracts reads `policy_kind` or `enforcement` (grep over `packages/core` and `services` finds none). A policy is a label, not a control.
- HITL already has the `policy_exception` review kind (`packages/core/neurosphere_core/hitl/models.py:42-44`, insight kind `:50-52`; reviewer needs `catalog.curate`, `hitl/policy.py:61-71`) and nothing opens one: the only references are the model, the policy table, the contract enum and tests.
- The action executor refuses to pretend (`packages/core/neurosphere_core/actions/targets.py:3-7`) and has one kind-to-connector table (`:59-72`); unknown kinds require approval (`services/api/neurosphere_api/actions/settings.py:57-59`). A governance policy change therefore has a ready, audited path once a target exists (PRP-108).
- `docs/PRD.md:14` lists Policy among the versioned catalog entities; `:23` routes "policy exceptions to scoped reviewers"; `:31` requires every channel to "recheck current resource permission and policy at execution"; `:44` promises "CI/CD registration/policy checks". None has an engine behind it.
- Owner direction 2026-11-16: "address it all, add it all"; the governance-core design (`temp/audit/governance-core-design.md` section 2.3, binding) fixes the model: closed rule kinds, a worker evaluator, violations with evidence, exceptions through HITL, enforcement modes `off`/`audit`/`enforce` with `audit` the default.

## Acceptance criteria
- [ ] Given a draft whose rule `kind` is outside the closed list, or whose parameters fail the PRP-99 parameter schema, or which carries any free-text field that could be executed, When it is created, Then it is refused 422 `invalid_schema` and nothing is stored; no code path compiles, evals or templates rule text (static test greps the package for `eval`, `exec`, `compile(`, `jinja`, query-string building).
- [ ] Given a published `data_sensitivity_access` policy "no agent without approval may read PII" and a synthetic agent with a `reads` edge to a `GroundingSource` whose `sensitivity_categories` contains `pii`, When the `policy_eval` role ticks, Then one violation exists with the policy id and version, the rule id, the subject id, evidence ids (the edge and the asset), `first_seen_at`, `last_seen_at`, and no content; a second tick updates `last_seen_at` and `occurrence_count` and does not create a second record.
- [ ] Given that condition disappears and the next run finished without truncation for that rule, Then the violation is `resolved` with `resolved_at`; given the run was truncated (subject or time budget hit), Then nothing is resolved and the run status says `truncated`.
- [ ] Given a violation, When a caller with `action.propose` in its domain requests an exception (justification code, bounded text, expiry at most `NS_GOVPOLICY_EXCEPTION_MAX_DAYS`), Then a HITL item of kind `policy_exception` is opened with the violation's canonical id as `subject_ref`; after a `catalog.curate` reviewer approves, the next tick marks the exception `active` until its expiry and `decide` honours it; a rejected or expired item leaves the violation open. The requester cannot review their own request.
- [ ] Publish and retire are drafted as `governance_policy_publish` intents through the one action plane (`ActionApi.draft`, same as REST, chat and MCP); without a registered platform-control target the intent is advisory with "no supported write connector" and the policy stays a draft. No route, worker or seed outside `NS_ENV=local` writes a published state directly.
- [ ] Every enforcement binding created at publish has mode `audit` (or `off` when the policy's `mode` is `off`); publishing with `mode: enforce` is refused `enforce_requires_mode_change`; no code path sets `enforce` except the `enforcement_mode_change` handler PRP-108 builds on `BindingStore.set_mode`.
- [ ] `decide(scope, request)` returns `allow`, `deny` or `audit` with matched rule ids, policy versions, the binding mode per point, applied exception ids, reason codes and a cache lifetime; `deny` only when a matching rule's binding for that point is `enforce` and no active exception applies; a subject outside the caller's scope is never described in the response.
- [ ] Every read route filters by the subject's domain against the caller's server-derived scope (`govpolicy.read`); customer-wide policies live in the customer-control domain and need the permission there; an out-of-scope id is 404, indistinguishable from missing. Every route is in the route inventories and boots under `verify_route_permissions`; ABAC deny cases pass for no role, viewer without the permission, wrong domain, wrong customer, wrong cloud and expired assignment.
- [ ] Each published policy is projected to `<cloud>:<customer>:neurosphere:policy:<policy_id>` in the catalog (enforcement mapped `off`->`disabled`, `audit`->`advisory`, `enforce`->`enforced`) through the catalog repository with the worker's own derived scope; retire sets the entity `deprecated`.
- [ ] A rule kind with no evaluator in this deployment (`budget`, `required_attestation`, `identity_entitlement`, or `content_rule` while no interaction-finding reader is bound) is reported `evaluator_unavailable` by `GET /status`, and publishing a policy containing it is refused in dry run (`rule_kind_unavailable`), so no policy appears active while doing nothing.
- PRP exit: touched suites, `tests/security/authz`, ruff, pyright, `validate_planning.py` pass; PR open, CI green; `openapi.json` regenerated.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| 1 | Rule language | Expression language; closed typed rule kinds | Closed typed kinds from PRP-99 (design 2.3, binding). Parameters only; no user or model text is executed |
| 2 | Kinds evaluated here | All ten; seven | `model_allow_list`, `data_sensitivity_access`, `residency`, `required_owner`, `required_approval`, `registration_required`, `content_rule` (design PRP-105 entry). `budget` PRP-115, `identity_entitlement` PRP-119, `required_attestation` PRP-130 register evaluators later through `RuleEvaluatorRegistry` |
| 3 | Who executes publish, retire, mode change | Routes write directly; executor | Executor intents (`governance_policy_publish`, `enforcement_mode_change`); the target is PRP-108's platform-control. `enforcement_mode_change` has no route here: it is drafted through the generic actions route with `mode_change_diff` (GD-44) |
| 4 | Enforcement default | `audit`; `enforce` for allow-lists | Decided by the owner 2026-11-16 (GD-7): `audit` for every policy and point; `enforce` only by an approved action, per point |
| 5 | Permissions | Reuse `policy.manage`; new names | New `govpolicy.read` and `govpolicy.manage`; `policy.manage` is the identity principal-policy permission (`auth/scope/permissions.py:90`) and stays unrelated |
| 6 | Role map | Several | Decided by the owner 2026-11-16 (GD-21): `govpolicy.read` is held by viewer, analyst, domain_steward, admin and security_auditor; `govpolicy.manage` (drafting and recording) by domain_steward and admin. Here: approval of the publish intent follows GD-20 (`action.approve`, a second steward, self-approval forbidden), so an admin drafts and a steward approves |
| 7 | Exception requester and reviewer | Several | ASSUMPTION: requester needs `action.propose` in the violation's domain; reviewer is the shipped `policy_exception` policy (`catalog.curate`, `hitl/policy.py:70`) |
| 8 | How an exception decision reaches the engine | Callback in HITL; read back | ASSUMPTION: the evaluator reads the HITL item state each tick (`HitlService.get`); HITL code is not edited. Insight decisions "only record the review outcome" (`services/api/neurosphere_api/hitl/service.py:10-12`) |
| 9 | Where enforcement bindings and run status live | New containers; existing ones | Bindings: `admin_config` documents of `admin_kind: enforcement_binding` through the shipped `AdminConfigRepository` (PRP-99 makes `EnforcementBinding` that body). ASSUMPTION: run status as documents with `doc_kind: evaluation_status` in `policy_definitions` (PRP-102 declares `policy_definitions`, `policy_violations`, `policy_exceptions`, partition `/customer_id`, `/domain_id`) |
| 13 | Policy-level `mode` at publish | Any; `audit`/`off` only | `PolicyDefinition.mode` (PRP-99, default `audit`) seeds the bindings created at publish; publishing with `mode: enforce` is refused (`enforce_requires_mode_change`), so `enforce` is always a per-point approved action (GD-7) |
| 10 | Unavailable rule kinds | Accept silently; refuse | Refuse at publish dry run (`rule_kind_unavailable`); drafts may hold them |
| 11 | Local demo before PRP-108 | Wait; seed | ASSUMPTION: under `NS_ENV=local` only, `NS_GOVPOLICY_LOCAL_SEED_FILE` publishes fixture policies through `PolicyLifecycle.publish` with an audit record `govpolicy.seed`; refused at startup in any other environment (same rule as design PRP-103) |
| 12 | Violation events | Call PRP-107 directly; sink | `ViolationEventSink` protocol with a no-op default; PRP-107 (W22) binds its publisher in its item 6 (the one binding owner). Interaction findings: port `InteractionFindingReader`, unbound here; PRP-104 (W23) binds it in its item 8 (the one binding owner) |
| 14 | How later rule kinds plug in | Each consumer edits this PRP's files; discovery | Discovery: `RuleEvaluatorRegistry.discover(ctx)` imports every module of the plugin package `neurosphere_core.governance.policy.rule_plugins` (`pkgutil.iter_modules`, sorted) and calls its `build(ctx: RuleBuildContext) -> RuleEvaluator | None`; `None` means the kind is unavailable in this deployment. A later kind (PRP-115 `budget`, PRP-119 `identity_entitlement`, PRP-130 `required_attestation`) adds one new module there and edits no file of this PRP; the worker assembly and the API builder both call `discover` |

## Context manifest

### Files to read first
- `temp/audit/governance-core-design.md` sections 2.3, 2.4, 3.2 and the PRP-105 entry - binding design.
- `PRPs/backlog/PRP-99-governance-contracts-a.md` "Interfaces provided" - the `policy/v1` names you build against.
- `packages/contracts/schemas/catalog/v1/policy.schema.json` - the projected entity (required fields `:120-137`).
- `packages/core/neurosphere_core/hitl/service.py:141-201` - `HitlService.open_item` (deterministic `item_id`, audited create).
- `packages/core/neurosphere_core/actions/targets.py` - why an unmapped kind is advisory.
- `services/api/neurosphere_api/catalog/grant_publish.py:1-40` - drafting an intent from a domain route through `ActionApi.draft`.
- `PRPs/backlog/PRP-73-graph-access-and-sensitivity-questions.md` "Interfaces provided" - `AccessEngine.who_accesses`.
- `packages/core/neurosphere_core/catalog/protocol.py:199-246` - `CatalogRepository` (`create_entity`, `update_entity` with ETag, `deprecate_entity`, `list_entities`).
- `packages/core/neurosphere_core/aggregates/subject.py:35-50` - `SubjectKind`, `subject_series_key`, `SubjectMetricsReader`.
- `services/workers/neurosphere_workers/publication/recorder.py:1-80` - worker catalog writes under its own derived `ScopeProvider` scope.
- `services/workers/neurosphere_workers/runtime/factories.py:309-330,522-544,1867-1879` - Cosmos, audit and HITL plumbing; the `BUILDERS` table.
- `services/api/neurosphere_api/authz/read_audit.py:176-193` - `audited_read`.

### Interfaces consumed
- PRP-99 ("Interfaces provided", Policy and admin sections): `neurosphere_contracts.policy.v1` `PolicyDefinition` (`policy_id` slug, `policy_version` int, `status` draft/published/retired, `mode` `EnforcementMode`, `severity`, 1-32 `PolicyRule` {`rule_id`, `kind` `PolicyRuleKind`, `applies_to` `PolicyAppliesTo`, `params` pinned by kind: `ModelAllowListParams`, `DataSensitivityAccessParams`, `ResidencyParams`, `BudgetRuleParams`, `RequiredOwnerParams`, `RequiredAttestationParams`, `RequiredApprovalParams`, `ContentRuleParams`, `RegistrationRequiredParams`}, `content_sha256`, `published_intent_id`), `PolicyViolation` (`dedup_key`, status open/excepted/resolved/superseded, 1-50 `PolicyViolationEvidence`, `resolution`), `PolicyException` (status requested/approved/rejected/expired/revoked, `review_item_id`, `expires_at` at most 365 days after request), `PolicyDecisionRequest` (`decision_point`, `operation`, subject ids, `model`, `data_asset_ids`, `access`), `PolicyDecisionResponse` (`effect` allow/deny/audit, `mode`, `matches`, `reason_codes`, `cache_ttl_seconds`, `policy_set_digest`, `degraded`), `EnforcementBinding` (`point` `EnforcementPoint`: `gateway`, `tool_call`, `mcp_server`, `mcp_client`, `sdk`, `budget`, `registration`; `target` TargetRef or null; `mode`; `state` pending/applied/failed/drifted/not_supported); `interactions/v1` `DetectionFinding`; `admin_kind: enforcement_binding`; `review-policy-document` `approver_permission` value `govpolicy.manage`; conventions: target entity types `governance_policy`, `enforcement_binding`, permission names `govpolicy.read`/`govpolicy.manage`, audit operations `govpolicy.publish`, `govpolicy.violation_open`, `govpolicy.violation_resolve`, `govpolicy.exception_decide`, `govpolicy.decide`. Do not edit contracts; if PRP-99 shipped different names, PRP-99 wins.
- PRP-102: containers `policy_definitions`, `policy_violations`, `policy_exceptions` (`/customer_id`, `/domain_id`; owner module `neurosphere_core.governance.policy.cosmos_store`, the file item 1 creates).
- Shipped PRP-37/PRP-65: `AdminConfigRepository` over `admin_config` (create, get, list by kind, replace with `If-Match`) for the binding documents.
- PRP-73: `neurosphere_core.catalog.graph.access` `AccessEngine`, `AccessQuery` (sensitivity categories, residency, modes read and write, budget), `AccessResult`.
- Shipped: `HitlService` (PRP-17), `ActionApi.draft` (`services/api/neurosphere_api/actions/service.py:120`), `run_audited_mutation` (`audit/repository.py:247`), `customer_control_domain_id` and `permits_customer_wide` (`auth/scope/permissions.py`), `SubjectMetricsReader` (PRP-49), `ScopeProvider` (`publication/recorder.py:71-74`).

### Interfaces provided
- Core package `neurosphere_core.governance.policy`:
  - `RULE_KINDS` (PRP-99 `PolicyRuleKind`), `EVALUATED_KINDS` (the seven here), `POINTS_BY_RULE_KIND` (which `EnforcementPoint` values a rule kind can bind to; ASSUMPTION table in the runbook), and `ENFORCEMENT_POINT_CAPABILITIES` (point -> `{can_block, what_it_blocks, owning_prp}`): `gateway` blocks only model traffic through a NeuroSphere-managed APIM gateway in manage mode on NeuroSphere-owned products, Commercial only, PRP-112; `tool_call` blocks NeuroSphere's own copilot tool calls, PRP-113; `mcp_server` blocks calls to NeuroSphere's MCP server tools, PRP-113; `mcp_client` blocks NeuroSphere's outbound calls to registered external MCP servers, PRP-113; `sdk` cooperative, never a boundary, PRP-114; `budget` proposes a `budget_cap_change`, never automatic, PRP-115; `registration` withholds activation of an unapproved AgentVersion inside NeuroSphere only, PRP-108. Detective evaluation (this PRP's worker) blocks nothing. PRP-106 shows this table; nobody may claim a block outside it.
  - Stores: `PolicyDefinitionStore` (`create_draft`, `replace_draft(if_match)`, `get(policy_id, version=None)`, `list(domain_ids, page)`, `versions`), `ViolationStore` (`upsert_observed(dedup_key, ...)`, `resolve_missing(run_id, policy_id, rule_id)`, `get`, `list(filters, page)`), `ExceptionStore` (`request`, `set_state`, `active_for(subject, rule, now)`, `list`), each with `InMemory*` and `Cosmos*` (`cosmos_store.py`); `BindingStore` over `AdminConfigRepository` (`ensure_bindings(policy, points, mode)`, `get`, `list(point=, policy_id=, target=)`, `set_mode(binding_id, mode, if_match)`, `set_state(binding_id, state, intent_id, audit_id, if_match)`; `target` null = every target of that point in the domain, a `TargetRef` = one tool, MCP server or gateway).
  - `PolicyLifecycle` with `publish(policy_id, version, *, expected_etag, audit_ctx)` and `retire(...)` (validate, mark published or retired, create bindings at the policy's `audit`/`off` mode, project the catalog entity) - the functions PRP-108's handler calls; `publish_diff(stage, policy)` / `parse_publish_diff(diff)` (target `<cloud>:<customer>:neurosphere:governance_policy:<policy_id>`, entity type `governance_policy`) and `mode_change_diff(binding, mode)` / `parse_mode_change_diff(diff)` (entity type `enforcement_binding`).
  - `RuleEvaluator` protocol (`kind`, `async evaluate(ctx, policy, rule) -> RuleOutcome` with findings, `truncated`, reason) and `RuleEvaluatorRegistry` with `register(evaluator)` and the extension point `discover(ctx)`: plugin package `neurosphere_core.governance.policy.rule_plugins` (this PRP ships it with an `__init__.py` and no plugin), each module exposing `build(ctx: RuleBuildContext) -> RuleEvaluator | None`; `RuleBuildContext` carries the catalog repository, `SubjectMetricsReader`, PRP-73 `AccessEngine`, the Cosmos client or `None` (memory backend), the cloud, the worker or API scope provider and a clock, so a plugin builds its own store from the client and edits nothing here (PRP-115 `budget`, PRP-119 `identity_entitlement`, PRP-130 `required_attestation` each add one module `rule_plugins/<kind>.py`); port `InteractionFindingReader` (bound by PRP-104 item 8 through the binding functions below).
  - `PolicyEvaluator.run(customer_id, *, scope, trigger, budget) -> EvaluationRun`.
  - `PolicyDecider.decide(scope, request: PolicyDecisionRequest, *, now) -> PolicyDecisionResponse` over a snapshot refreshed every PRP-99 `EnforcementSetting.decision_cache_ttl_seconds` (stored setting, default 60; no env var); `PolicyDecider.invalidate()`.
  - `ViolationEventSink` protocol (`opened`, `resolved`, `exception_decided`; ids only) and `NoopViolationEventSink`; event classes are PRP-99's `NotificationEventClass` values `policy_violation_opened`, `policy_violation_resolved`, `policy_exception_decided`. The binding points are the functions `violation_event_sink` and `interaction_finding_reader` in `policy_eval/assembly.py` (and `interaction_finding_reader` in `runtime/builders/governance.py`): PRP-107 item 6 fills the first, PRP-104 item 8 the second; nobody else binds them.
  - `governance_policy_chain_id(customer_id)` -> `<customer>.governance-policy`; canonical ids `<cloud>:<customer>:neurosphere:policy_violation:<violation_id>` and `...:policy_exception:<id>`.
- Permissions `Permission.GOVPOLICY_READ = "govpolicy.read"`, `Permission.GOVPOLICY_MANAGE = "govpolicy.manage"`.
- Routes under `/api/v1/governance/policy`: `GET|POST /domains/{domain}/policies`, `GET /domains/{domain}/policies/{policy_id}` (`?version=`, `ETag`), `GET .../versions`, `PUT .../draft` (`If-Match`), `POST .../publish`, `POST .../retire` (both return the drafted intent view), `GET /domains/{domain}/violations`, `GET /domains/{domain}/violations/{violation_id}`, `POST .../violations/{violation_id}/exception-requests`, `GET /domains/{domain}/exceptions`, `GET /domains/{domain}/bindings`, `GET /status`.
- API: builder module `runtime/builders/governance.py` (`BUILDER`), optional component `governance_policy`, `app.state.governance_policy` (`GovernancePolicyPlane`: stores, lifecycle, decider), settings `GovernancePolicySettings` (`NS_GOVPOLICY_ENABLED` default true, `NS_GOVPOLICY_BACKEND` `cosmos|memory` with memory only under `NS_ENV=local`, `NS_GOVPOLICY_EXCEPTION_MAX_DAYS` 90, `NS_GOVPOLICY_LOCAL_SEED_FILE`).
- Worker: role `policy_eval`, `build_policy_eval` in `neurosphere_workers.policy_eval.assembly`, settings `NS_POLICY_EVAL_INTERVAL_SECONDS` (300), `NS_POLICY_EVAL_SUBJECT_BUDGET` (5000), `NS_POLICY_EVAL_TIME_BUDGET_SECONDS` (120).
- Audit operations (PRP-99 names first, each carrying the triggering `correlation_id`): `govpolicy.publish`, `govpolicy.violation_open`, `govpolicy.violation_resolve`, `govpolicy.exception_decide`, `govpolicy.decide` (written only for `deny` and audit-mode would-deny, never per allow); added here: `govpolicy.draft_create`, `govpolicy.draft_replace`, `govpolicy.retire`, `govpolicy.seed`, `govpolicy.exception_request`, `govpolicy.evaluation_run`.

### Patterns to match
- Drafting an intent from a domain route: `services/api/neurosphere_api/catalog/grant_publish.py` (whole module).
- Audited admin writes with `ETag`/`If-Match`: `services/api/neurosphere_api/mcp/admin/router.py:96-198`.
- Cosmos store with ETag create and replace: `packages/core/neurosphere_core/mcp/cosmos_store.py:86-140`.
- Worker tick role: `services/workers/neurosphere_workers/runtime/factories.py:344-345` (`_tick_role`) and `:720-727` (`build_hitl_timers`).
- Worker catalog write under derived scope: `services/workers/neurosphere_workers/publication/recorder.py:99-150`.
- Separate sub-prefix router registration: `services/api/neurosphere_api/routers.py:106-109` (`_register_catalog_curation`).

### Gotchas
- No content anywhere: violations carry ids, counts and category names; `content_rule` reads only `DetectionFinding` metadata through the port, never an interaction body (design 2.1).
- Resolve only after a complete run for that rule: a truncated or failed run must never resolve violations (it would silently "fix" them).
- HITL `subject_ref` must match the canonical grammar (`hitl/models.py:80`); use the `policy_violation` canonical id, and pass a deterministic `item_id` so a retried request turns into `review_item_exists`, not a duplicate.
- The worker cannot import `_cosmos`, `_audit` or `_hitl_service` from `runtime/factories.py` (factories imports your module for `BUILDERS`; circular). Build clients in `policy_eval/assembly.py` from the public pieces they wrap (`create_cosmos_client`, `CosmosAuditStore.from_client`, `CosmosHitlStore.from_client`) and take `RuntimeConfig` under `TYPE_CHECKING`, as `admin_platform/policy.py:13` does.
- The worker evaluates only domains its own derived scope covers; it never constructs a wider scope. Customer-wide policies apply to subjects in domains that scope can see, and the run status lists domains skipped for lack of scope.
- `policy_exception` reviewers need `catalog.curate`; an analyst requester cannot approve their own request (`self_approval_forbidden` holds for insight kinds by default; assert it).
- Adding the API builder breaks tests that pin `default_builders` order and the component set: `services/api/tests/runtime_api/test_readiness.py`, `runtime_gateway_builder/test_gateway_builder.py`, `runtime_data/data_helpers.py`. Adding a worker role breaks `services/workers/tests/worker_roles/test_roles.py`.
- The `policy` container is the identity principal-policy store (`stores/containers.py:100`); never write governance documents there.
- New test directories need unique names (`governance_policy`, `governance_policy_api`, `policy_eval_worker`).
Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - packages/core/neurosphere_core/governance/__init__.py
  - packages/core/neurosphere_core/governance/policy/**
  - packages/core/tests/governance_policy/**
  - services/workers/neurosphere_workers/policy_eval/**
  - services/workers/tests/policy_eval_worker/**
  - services/api/neurosphere_api/governance/__init__.py
  - services/api/neurosphere_api/governance/policy/**
  - services/api/neurosphere_api/runtime/builders/governance.py
  - services/api/tests/governance_policy_api/**
  - tests/security/authz/test_governance_policy*.py
  - tests/security/governance_policy/**
  - docs/runbooks/governance-policy.md
tier1: []
tier2_appends:
  - services/api/neurosphere_api/routers.py
  - services/api/neurosphere_api/runtime/builders/__init__.py
  - services/api/neurosphere_api/runtime/status.py
  - services/api/neurosphere_api/authz/routes.py
  - packages/core/neurosphere_core/auth/scope/permissions.py
  - packages/core/neurosphere_core/admin/models.py
  - packages/core/tests/admin/test_config_store.py
  - services/workers/neurosphere_workers/runtime/roles.py
  - services/workers/neurosphere_workers/runtime/factories.py
  - services/api/tests/authz/test_route_inventory.py
  - services/api/tests/authz/test_startup_route_check.py
  - services/api/tests/runtime_routes/manifest_calls.py
  - tests/integration/real_stack/test_manifest_routes.py
  - packages/core/tests/auth/scope/test_roles.py
  - tests/security/authz/test_privileged_roles.py
  - services/api/tests/runtime_api/test_readiness.py
  - services/api/tests/runtime_gateway_builder/test_gateway_builder.py
  - services/api/tests/runtime_data/data_helpers.py
  - services/workers/tests/worker_roles/test_roles.py
  - mkdocs.yml
must_not_touch:
  - packages/contracts/**
  - packages/core/neurosphere_core/stores/containers.py
  - infra/**
  - packages/core/neurosphere_core/catalog/**
  - packages/core/neurosphere_core/hitl/**
  - packages/core/neurosphere_core/actions/**
  - packages/core/neurosphere_core/interactions/**
  - services/api/neurosphere_api/runtime/builders/data.py
  - services/api/neurosphere_api/hitl/**
  - frontend/**
```
The `factories.py` entry is the `BUILDERS` table line only (Tier 2); no builder body in that file changes.

## Implementation blueprint

Parallelization: items 1 and 2 [P] after PRP-99 merges (2 codes against item 1's model module, frozen in its first commit). Item 3 after 1 and 2; item 4 after 3; items 5 and 6 after 4 (they share no file); item 7 after 6; item 8 last.

### Item 1 - Models, validation and stores  [P]  [serial-after: PRP-102]
- Deliverable: `governance/policy/{models,validation,store,cosmos_store,memory_store,ids,capabilities}.py`: re-exports of the PRP-99 types; draft validation (closed kind list, per-kind parameter schema, rule ids unique, bounded counts: at most 50 rules, 200 list items per parameter); the four stores with ETag create and replace; `dedup_key` = `sha256:` of (policy id, rule id, subject canonical id, evidence class); canonical id helpers; `ENFORCEMENT_POINT_CAPABILITIES`; the `enforcement_binding` line in `ADMIN_KIND_MODELS` (core refuses an unregistered `admin_kind`, and this PRP is the first to store bindings).
- Owned files: `packages/core/neurosphere_core/governance/__init__.py`, `governance/policy/{models,validation,store,cosmos_store,memory_store,ids,capabilities}.py`, `packages/core/tests/governance_policy/test_validation.py`, `test_stores.py`; Tier-2 line in `packages/core/neurosphere_core/admin/models.py`; drop `enforcement_binding` from `PENDING_ADMIN_KINDS` in `packages/core/tests/admin/test_config_store.py` (PRP-99 hand-off: the PRP that registers a kind removes its entry; added at execution 2026-11-25).
- Must NOT touch: contracts, `stores/containers.py`.
- Depends on: PRP-99 merged; `[serial-after: PRP-102]` (same wave W21; PRP-102 declares `policy_definitions`, `policy_violations`, `policy_exceptions`).
- Acceptance criteria: criterion 1; stale `If-Match` raises `stale_version`; a published version is immutable (replace refused `policy_published`); memory and Cosmos stores pass one shared contract test.
- Tests: `packages/core/tests/governance_policy/test_validation.py`, `test_stores.py`, `test_no_generated_code.py`.
- Pattern references: `packages/core/neurosphere_core/mcp/cosmos_store.py:86-140`, `packages/core/tests/hitl_cosmos/contract.py`.

### Item 2 - Rule evaluators and the plugin extension point  [P]
- Deliverable: `governance/policy/rules/` with one module per evaluated kind and `RuleEvaluatorRegistry`: `model_allow_list` (catalog `uses_model` edges plus model subject points not in the list), `data_sensitivity_access` (PRP-73 `AccessEngine.who_accesses` filtered by sensitivity categories and the accessor's approval state), `residency` (asset `residency_region`/`residency_geography` against the allowed set), `required_owner` (no `owned_by` edge), `required_approval` (AgentVersion approval state not `approved`), `registration_required` (agent subject points with no catalog Agent, or an AgentVersion without approval), `content_rule` (counts of detected categories from `InteractionFindingReader`; unavailable when unbound). Each is bounded by the run budget and reports `truncated`. The extension point of clarification 14: `RuleBuildContext`, `RuleEvaluatorRegistry.discover(ctx)` and the empty plugin package `governance/policy/rule_plugins/__init__.py`; a plugin whose `build` raises is reported `evaluator_unavailable` with reason `plugin_failed`, never crashes the run.
- Owned files: `packages/core/neurosphere_core/governance/policy/rules/**`, `packages/core/neurosphere_core/governance/policy/rule_plugins/__init__.py`, `packages/core/tests/governance_policy/rules/**`.
- Must NOT touch: `catalog/**`, `aggregates/**`.
- Depends on: item 1's models module.
- Acceptance criteria: one positive, one negative and one truncation case per kind on in-memory catalog and aggregate fakes; no evaluator reads an interaction body or a field outside its ports; a test plugin module placed on a temporary plugin path is discovered, and one returning `None` reports its kind unavailable.
- Tests: `packages/core/tests/governance_policy/rules/test_<kind>.py` (seven files), `test_discovery.py`.
- Pattern references: PRP-73 `AccessEngine` usage; `aggregates/subject.py:57-65`.

### Item 3 - Evaluation run, violations, exceptions and catalog projection
- Deliverable: `governance/policy/{evaluate,exceptions,projection,lifecycle,actions,events}.py`: `PolicyEvaluator.run` (published policies in scope, per-rule budget, upsert and resolve, run status); exception request opening HITL `policy_exception` with a deterministic item id and the tick-time read-back of its state; `project_policy` and retire to the catalog `Policy` entity; `PolicyLifecycle.publish/retire` with `audit` bindings and the `rule_kind_unavailable` refusal; the two diff grammars; `ViolationEventSink`.
- Owned files: those modules, `packages/core/tests/governance_policy/test_evaluate.py`, `test_exceptions.py`, `test_projection.py`, `test_lifecycle.py`.
- Must NOT touch: `hitl/**`, `catalog/**`, `actions/**`.
- Depends on: items 1 and 2.
- Acceptance criteria: criteria 2, 3, 4 (engine side), 6, 9 and 10; projection failure leaves the policy published and is retried next tick with a reason code.
- Tests: the four files above.
- Pattern references: `hitl/service.py:141-201`, `publication/recorder.py:99-150`.

### Item 4 - The decision function
- Deliverable: `governance/policy/decide.py`: `PolicyDecider` with an immutable snapshot (published policies, bindings, active exceptions) refreshed on interval and on `invalidate()`, subject resolution through the caller's scope only, combination rule of criterion 7, and the evaluable-at-request subset (`model_allow_list`, `data_sensitivity_access`, `residency`, `registration_required`, `required_approval`, `required_owner`).
- Owned files: `governance/policy/decide.py`, `packages/core/tests/governance_policy/test_decide.py`.
- Must NOT touch: anything outside the package.
- Depends on: item 3.
- Acceptance criteria: criterion 7; a snapshot refresh failure keeps the last snapshot and reports `stale_snapshot`; `decide` performs no write and no unbounded read.
- Tests: `packages/core/tests/governance_policy/test_decide.py`, `test_decide_scope.py`.
- Pattern references: cached snapshot refresh in `services/api/neurosphere_api/ingest/producer_store.py`.

### Item 5 - Worker role `policy_eval`
- Deliverable: `neurosphere_workers/policy_eval/{__init__,assembly,settings,worker}.py`: `build_policy_eval(cfg, lifetime)` building Cosmos stores, audit, `HitlService`, catalog repository and the worker `ScopeProvider`, and the registry through `discover`; two named binding functions in `assembly.py`, `violation_event_sink(cfg, lifetime)` (returns `NoopViolationEventSink`) and `interaction_finding_reader(cfg, lifetime)` (returns `None`), are the binding points PRP-107 item 6 and PRP-104 item 8 fill (the API builder has the matching `interaction_finding_reader` function in `runtime/builders/governance.py`); interval tick plus "due" policies first (published since last run); `ROLE_NAMES` and `BUILDERS` lines.
- Owned files: `services/workers/neurosphere_workers/policy_eval/**`, `services/workers/tests/policy_eval_worker/**`; Tier-2 lines in `runtime/roles.py`, `runtime/factories.py` (`BUILDERS` only), `services/workers/tests/worker_roles/test_roles.py`.
- Must NOT touch: builder bodies in `factories.py`.
- Depends on: item 4.
- Acceptance criteria: a tick on fakes produces criterion 2; a store outage releases the tick with a logged reason code (no crash loop); unknown settings refuse to start.
- Tests: `services/workers/tests/policy_eval_worker/test_worker.py`, `test_assembly.py`.
- Pattern references: `runtime/factories.py:720-727`, `admin_platform/policy.py`.

### Item 6 - API routes, builder and permissions
- Deliverable: `services/api/neurosphere_api/governance/{__init__}.py` and `governance/policy/{router,service,models,deps}.py` for the routes in "Interfaces provided"; publish and retire draft through `ActionApi.draft` with the item-3 diff and `test /policy_digest`; reads through `audited_read`; `runtime/builders/governance.py` with settings, the local seed loader (refused unless `NS_ENV=local`), the `governance_policy` component, the registry through `discover` (so the API's `rule_kind_unavailable` check sees the same kinds as the worker) and the binding function `interaction_finding_reader` (returns `None` until PRP-104 item 8); permissions and role map lines.
- Owned files: `services/api/neurosphere_api/governance/**` (policy only), `runtime/builders/governance.py`, `services/api/tests/governance_policy_api/**`; Tier-2 lines in `routers.py`, `runtime/builders/__init__.py`, `runtime/status.py`, `authz/routes.py`, `permissions.py` and the pinned builder tests.
- Must NOT touch: `runtime/builders/data.py`, `planes.py`, `actions/**`.
- Depends on: item 4.
- Acceptance criteria: criteria 4 (route side), 5 and 8; `GET /status` per criterion 10; seed outside `NS_ENV=local` refuses to start with `govpolicy_seed_not_local`.
- Tests: `services/api/tests/governance_policy_api/test_routes.py`, `test_publish_draft.py`, `test_builder.py`, `test_seed.py`.
- Pattern references: `catalog/grant_publish.py`, `mcp/admin/router.py:96-198`, `runtime/builders/admin_platform.py`.

### Item 7 - Authorization and constraint negative suite
- Deliverable: ABAC cases for every new route; scope tests (violation in a domain the caller cannot see is 404; customer-wide policy needs the customer-control domain); "no direct publish" test (every path that sets `published` or `enforce` is enumerated and only `PolicyLifecycle` and `BindingStore.set_mode` do it); no-content test (violation, audit payload, logs and OpenAPI examples carry no interaction text).
- Owned files: `tests/security/authz/test_governance_policy.py`, `tests/security/governance_policy/**`.
- Must NOT touch: `world.py`, `cases.py` except additive helpers.
- Depends on: item 6.
- Acceptance criteria: every route has a deny case per dimension, none skipped.
- Tests: `tests/security/authz`, `tests/security/governance_policy`.
- Pattern references: `tests/security/authz/test_admin_platform.py`.

### Item 8 - Integration and close-out
- Deliverable: runbook `docs/runbooks/governance-policy.md` (rule kinds, modes, point capability table, exception flow, local seed, "advisory until PRP-108"); mkdocs nav; rebase; Tier-3 regeneration; changelog fragment; completion note with operator env vars and the product check (can a steward author, publish and see a violation without editing files?).
- Owned files: runbook, Tier-2 lines, this PRP file, Tier-3 files per reference section 2.
- Depends on: items 1-7.
- Acceptance criteria: validation gates pass; CI green.

## Validation gates
```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q packages/core/tests/governance_policy services/workers/tests/policy_eval_worker services/workers/tests/worker_roles services/api/tests/governance_policy_api services/api/tests/runtime_api services/api/tests/runtime_gateway_builder services/api/tests/runtime_data services/api/tests/runtime_routes services/api/tests/authz packages/core/tests/auth tests/security/authz tests/security/governance_policy packages/core/tests/hitl services/api/tests/test_openapi_drift.py tests/docs/test_reference_coverage.py tests/docs/test_nav_allowlist.py
python scripts/prp_status.py --check
python scripts/validate_planning.py
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```
Emulator check (local, not CI; only if this session holds the compose stack, otherwise skip and say so): `docker compose up -d --wait`, start the API and the `policy_eval` role with `NS_ENV=local` and the seed file, confirm one violation for the synthetic PII reader.

## Migration and rollback
No migration: all documents are new, in containers PRP-102 declares. Rollback: `NS_GOVPOLICY_ENABLED=false` (component disabled, routes 503 `capability_unavailable`) and drop `policy_eval` from `NS_WORKER_ROLES`; or revert the PR. Projected catalog `Policy` entities stay as `advisory` records and can be deprecated through the catalog. Nothing enforces in this PRP, so turning it off removes no control.

## Live and open gates
None. No external call is made; everything runs on in-memory twins and, locally, the Cosmos emulator. Enforcement on real systems is PRP-112 (G17, OPEN) and PRP-136.

## NOT building
Policy UI (PRP-106); the platform-control target that executes publish and mode changes (PRP-108); any expression language, user-supplied code, model-written rule text or generated query; the `budget`, `identity_entitlement` and `required_attestation` evaluators; gateway, tool-call or SDK enforcement; notification delivery; automatic remediation of a violation (a fix is always a proposed action with approval); legal or compliance verdicts on a violation (it is evidence of a rule match, nothing more); blocking anything: this PRP is detective only.

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [ ] All clarification questions are decided, not guessed (rows 4, 6, 7, 8, 9 and 11 are ASSUMPTIONS; PRP-99 names are taken from its backlog file and are final only when PRP-99 ships)

## Execution state
| Item | Status | Branch/worktree | Notes |
|---|---|---|---|
| 1 | merged | worktree-agent-a3256cd8dd0c738f4 | b03fe4a4+4612ced3 merged to integration (no-ff) 2026-11-25; gates re-run 311 passed, Snyk 0; review A APPROVED (mutation tests killed 5/7, 2 survivors non-gaps); follow-ups #417; draft PR 416 |
| 2 | merged | worktree-agent-abc05e501df34c26f | 5703e615 merged to integration (no-ff) 2026-11-25; gates re-run 311 passed, Snyk 0; review A APPROVED; follow-ups #417; draft PR 416 |
| 3 | review | worktree-agent-a015d8b9f985af658 | db9fb6e9 merged to integration as 04ba198e 2026-11-25; gates re-run 519 passed, Snyk 0; review A fixes (list cursor, resolve_missing paging + resolve_truncated) included; awaits checkpoint review B with item 4 |
| 4 | in-progress | (agent worktree) | dispatched 2026-11-25, opus |
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
