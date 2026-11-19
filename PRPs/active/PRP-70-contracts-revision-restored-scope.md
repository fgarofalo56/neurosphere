---
name: PRP-70-contracts-revision-restored-scope
status: active
started: 2026-11-19
priority: P0
order: 60
review: required
created: 2026-11-16
model: opus
orchestrator_model: opus
implementer_model: sonnet
phase: 7
ns: NS-02, NS-03, NS-05, NS-06, NS-08
depends_on: []
wave: W19
branch: prp-70-contracts-restored-scope
allow_parallel: true
issues: []
---

# PRP-70: Contracts revision for the restored original scope

## Goal
Ship, in one Tier-1 pass, the additive `v1` contract changes that the restored-scope PRPs (PRP-71 to PRP-83) and PRP-61 code against, and nothing above the wire layer: capability tags, capabilities and environment on catalog entities; a sensitivity and residency vocabulary on data assets (PII, PHI, CUI and similar); an entity revision record and a revision diff for version history; the agent-match request, response and feedback contracts for the task-to-agent recommender; map node facets and a topology-change marker; six compliance framework ids (SOC 2, ISO 27001, GDPR, NIST 800-53, EU AI Act, ISO/IEC 42001); optional tool, service and MCP-server identity on the telemetry event (governance-core fold F1); the two recommendation kinds PRP-61 needs (already shipped by PRP-61 if present on main at execution: verify, then skip); and the structured-query allowlist entries that make the new fields filterable. It is for the writers and implementers of PRP-71..83, who are being written against the names in "Interfaces provided" right now, and it runs alone on `packages/contracts/**` in W19 because a wrong name here is refactored in a dozen PRPs. Opus with a required review, following the PRP-37 precedent.

Out of scope: every route, store, container, worker, seed and UI that uses these contracts (PRP-71 seed and demo profile, PRP-72 matcher and feedback store, PRP-73 access and sensitivity queries, PRP-74/77 map, PRP-75 find-an-agent UI, PRP-76 registration form and revision store, PRP-78/80 copilot tools, PRP-81 framework library data, PRP-83 residency enforcement); PRP-61's API `Kind` literal, filter list and detection workers (PRP-61 keeps them; it no longer edits contracts); populating any new field from telemetry or connectors.

## Why
- Restores original 5b (PRD of 2026-10-02, `git show 9fbf5f4c:docs/PRD.md`): "CRUD API + UI for agent registration with required metadata schema (owner, semver, tags, data scopes)" and "Full version history retained and queryable"; story "As a platform engineer, I want to register a new agent version and see its diff against the prior version's declared capabilities." Today `catalog/v1/agent.schema.json` has no `tags`, `capabilities` or environment property, `attributes` rejects arrays (`catalog/v1/common.schema.json` `$defs/attributes`), and `AgentVersion.version_label` is a free string (`catalog/v1/agent_version.schema.json:70`). v1.2 never removed tags explicitly: NS-02 (`docs/PRD.md:14`) lists the versioned entities and simply omits capability tags and version diff.
- Restores original 5c: "Given a task description or workflow context, recommends the best-fit agent(s)/tool(s) based on capability tags, historical performance, graph proximity, and usage patterns"; criteria "Returns ranked list of candidate agents with confidence score and explanation referencing graph relationships/telemetry signals" and "Supports feedback loop (accept/reject) that retrains/adjusts ranking." Demoted by `docs/PRD.md:21`: "Agent/tool selection is an optional secondary recommendation capability, not the product's primary purpose." The recommendation `kind` enum is six detector kinds only (`recommendations/v1/recommendation.schema.json:39-47`); no match contract exists.
- Restores the original persona "Compliance/Security Officer" ("agents touching regulated data (PII, PHI, CUI)") and the 5e story "which agents touch EU customer data?". Data assets carry only `classification` (`public..unknown`, `catalog/v1/common.schema.json:68`), `residency_region` and `contains_personal_data` (`catalog/v1/grounding_source.schema.json:99`); no category or geography vocabulary exists.
- Restores original 5d: "Supports filtering/search by node type, tag, environment, health status" and story "filter the map by environment (prod/staging) or cloud provider". The map wire model has no environment, tag or error field (`services/api/neurosphere_api/map/models.py:41-55`). v1.2 kept the map but bounded it (`docs/PRD.md:25`, `:51`); facets are compatible with that bound.
- Restores original 5g: "Documented mapping of platform controls to SOC 2 Trust Services Criteria and ISO 27001 Annex A controls" and "Data residency controls configurable per tenant/region (GDPR Art. 44-49 support)". Removed by `docs/PRD.md:39` ("Map to applicable NIST 800-53 Rev 5 and agency requirements") and `:57` ("formal certifications ... are outside the initial baseline"). `FrameworkId` is a closed four-value enum (`compliance/v1/control.schema.json:41`).
- PRP-61 (backlog at planning time; shipped as built on main) item 1 planned to add `configuration_finding` and `unregistered_ai_resource` to the recommendation kinds; moving that here leaves one contracts owner per wave (ASSIGNMENTS W19 row).

## Acceptance criteria
- [ ] Every schema and `$defs` entry in "Interfaces provided" exists with the exact name, generates Python and TypeScript bindings, and has at least one valid and one invalid example listed in its area's examples manifest; `python packages/contracts/scripts/generate.py --check` passes.
- [ ] Additive only: `tests/contracts/test_additive_only.py` passes with an EMPTY `ALLOWED_TIGHTENINGS`; every existing example still validates; documents written before this PRP (no new fields) validate unchanged; the baseline snapshot is refreshed only in the close-out commit.
- [ ] Given an Agent with `tags: ["invoice-processing"]`, `capabilities: ["document.summarize"]`, `environment: "production"`, it validates; a tag with uppercase or spaces, more than 32 tags, a capability with more than four dot segments, or an unknown environment is rejected (JSON Schema and Pydantic).
- [ ] Given a GroundingSource with `sensitivity_categories: ["pii","phi"]` and `residency_geography: "eu_eea"`, it validates; a duplicate category or an unknown geography is rejected; `classification` is unchanged.
- [ ] `EntityRevision` accepts a body of the entity type it names and rejects a body of another type (JSON Schema `if/then` test; Pydantic projection documented); `EntityRevisionDiff` rejects more than 200 changes.
- [ ] `AgentMatchRequest` rejects `domain_id`, `customer_id` or any unknown key, a `task_text` over 2000 characters or with control characters other than tab and newline, and `limit` over 50; `AgentMatchResponse` requires a per-candidate `signals` list whose `value` is a number in [0,1] or null (unknown, never 0); `AgentMatchFeedback` stores a `task_digest`, never task text.
- [ ] A recommendation of kind `configuration_finding` or `unregistered_ai_resource` with `evidence_status: sufficient` validates without `score`; the same kind with `advisory: false` or `method: statistical` is rejected; a `cost_spike` without `score` is still rejected (existing invalid example unchanged).
- [ ] `StructuredQuery` accepts the new keyword and boolean fields on catalog entities and `FIELD_APPLICABILITY` lists them; a filter on `sensitivity_category` for `telemetry_event` fails the applicability validator.
- [ ] `Control.framework_id` accepts `soc2_tsc`, `iso_27001_annex_a`, `gdpr`, `nist_800_53_r5`, `eu_ai_act`, `iso_42001` (fold F2; PRP-128 ships the mappings as data with no further contract change); the existing four still validate; no example contains wording that claims compliance (the PRP-56 claims scanner pattern).
- [ ] Fold F1: a `TelemetryEvent` with `tool` {`external_tool_id`, `canonical_tool_id`, `tool_name`}, `service` {`external_service_id`, `canonical_service_id`} and `mcp_server_ref` validates; an event without them validates unchanged and the three fields default to null; `tool` or `service` as an empty object, an unknown key inside them, or a value over its length cap is rejected (JSON Schema and Pydantic); `schema_version` has a minor bump; no body-like field is added and `payload_ref` is untouched (`tests/contracts/test_telemetry_tool_service_identity.py`).
- [ ] The finding-kind criterion (the two recommendation kinds) is already shipped by PRP-61 if present on main at execution: verify it, then skip that part of item 3 and its label edits; otherwise ship it as written.
- [ ] `pnpm --filter @neurosphere/frontend typecheck` passes: the two new kinds have labels in `frontend/src/features/recommendations/strings.ts` (`KIND_LABELS` is a `Record<RecommendationKind, string>`).
- PRP exit: touched suites, `generate.py --check`, ruff, pyright, contracts TS tests, frontend typecheck and `validate_planning.py` pass; PR open with CI green including `contracts`; Tier-3 files regenerated at merge.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| 1 | PII/PHI/CUI vocabulary | extend `classification` enum; new list field | New `sensitivity_categories` list beside `classification` (gap analysis R1 ASSUMPTION): additive, and a source can be both `confidential` and `pii` |
| 2 | EU-data questions | derive from `residency_region` only; add a geography | Add optional `residency_geography` on data assets; ASSUMPTION: PRP-73 derives it from `residency_region` when null, through a core region map it owns |
| 3 | Capability vocabulary | closed taxonomy; open tokens | Open dot-namespaced tokens (`document.summarize`); ASSUMPTION: a closed taxonomy needs customer input, PRP-71 seeds a demo vocabulary |
| 4 | Match explanation | LLM-written text; structured signals | Structured per-signal breakdown plus related entity ids; no free text from a model (gap analysis section 5 item 10) |
| 5 | Match score | probability; relative score | Relative weighted score in [0,1], documented "not a probability" (same stance as detector `score`) |
| 6 | Where match contracts live | new area; `recommendations/v1` | `recommendations/v1`, kebab-case files, beside `recommendation.schema.json` |
| 7 | Map facets | API-local fields; contract fragment | New `map/v1` area with fragment schemas (no `schema_version`, like `actions/v1/target-ref`) so API and frontend share one shape |
| 8 | Revision body | digest only; full body | Full body pinned to the entity schema by `entity_type` (AdminConfigDocument precedent) plus `body_sha256` |
| 9 | New enum values on closed enums (`kind`, `framework_id`) | v2; additive | Additive (the additive-only test does not compare new values); descriptions of `kind`, `framework_id`, `sensitivity_category`, `residency_geography` and `capability` now say "open-ended: readers must tolerate unknown values" |
| 10 | Score rule for the two finding kinds | fabricate 1.0; allow no score | Allow `sufficient` without `score` for those kinds only, with `advisory: true` and `method: rule` (PRP-61 clarification 7, made final here) |
| 11 | Free text on feedback | comment field; reason codes | Reason codes only (no PII-bearing free text stored) |
| 12 | Tool, service and MCP identity on telemetry (fold F1) | wait for PRP-99; fold here | Fold here: PRP-71 seeds telemetry in W20 in parallel with PRP-99 and needs the names; optional nullable, additive. The content channel, interactions, policy and every other governance schema stay in PRP-99 and PRP-110 |
| 13 | EU AI Act and ISO/IEC 42001 ids (fold F2) | wait for PRP-128; fold here | Fold here, inside item 4, since this PRP already edits and open-ends `framework_id`; values `eu_ai_act`, `iso_42001` (`nist_ai_rmf` already exists) |

## Context manifest

### Files to read first
- `packages/contracts/schemas/telemetry/v1/telemetry-event.schema.json` and its examples - where fold F1 lands.
- `docs/adr/0004-contract-versioning.md` - additive-only rule and the PRP-37 amendment (baseline test, allowlist).
- `packages/contracts/scripts/generate.py` - discovery `*/v*/*.schema.json`, `--check`; `packages/contracts/scripts/test_generate.py:45-60` area set.
- `packages/contracts/schemas/catalog/v1/common.schema.json` - `$defs` style (`token`, `classification`, `relation_type`, `entity_type`).
- `packages/contracts/schemas/catalog/v1/agent.schema.json`, `grounding_source.schema.json`, `agent_version.schema.json` - entity shape and cloud `allOf` pins.
- `packages/contracts/schemas/admin/v1/admin-config-document.schema.json` - `body` anyOf plus kind pins (precedent for `EntityRevision.body`).
- `packages/contracts/schemas/recommendations/v1/recommendation.schema.json:39-47,102-118` - kind enum and the score `allOf`.
- `packages/contracts/schemas/query/v1/structured-query.schema.json:179-235` - field allowlists; `tests/contracts/validators.py:619-700` `FIELD_APPLICABILITY`.
- `packages/contracts/schemas/compliance/v1/control.schema.json` - `framework_id`.
- `tests/contracts/test_additive_only.py`, `tests/contracts/test_catalog_query_revisions.py`, `tests/contracts/contract_support.py:37-41`.
- `PRPs/backlog/PRP-61-configuration-detections-and-shadow-ai-discovery.md` - clarification 7 and item 1.
- `frontend/src/features/recommendations/strings.ts:49` - `KIND_LABELS`.

### Interfaces consumed
- Shipped: PRP-01 conventions (`schema_version` `1.x.y`, `additionalProperties: false`, relative `$ref`), PRP-37 additive-only baseline and `admin/v1`, PRP-56 compliance family. Nothing from unshipped PRPs.

### Interfaces provided
Generated names: Python `neurosphere_contracts.<area>.v1.<file_with_underscores>`, TypeScript `packages/contracts/ts/src/<area>/v1/<file>.ts`, exported by title from `ts/src/index.ts`.

Catalog `$defs` (`catalog/v1/common.schema.json`):
- `tag`: string `^[a-z0-9][a-z0-9._-]{0,62}$`. `tags`: array of `tag`, `uniqueItems`, `maxItems` 32, `default: []`.
- `capability`: string `^[a-z][a-z0-9_]{0,31}(\.[a-z][a-z0-9_]{0,31}){0,3}$`, `maxLength` 128 (open-ended). `capabilities`: array of `capability`, `uniqueItems`, `maxItems` 64, `default: []`.
- `environment`: enum `production`, `staging`, `development`, `test`, `sandbox`, `unknown`, `default: unknown` (the `TelemetryEvent.environment` vocabulary).
- `sensitivity_category`: enum `pii`, `phi`, `cui`, `pci`, `financial`, `biometric`, `credentials`, `export_controlled`, `legal_privileged`, `other` (open-ended).
- `residency_geography`: enum `eu_eea`, `uk`, `switzerland`, `united_states`, `canada`, `asia_pacific`, `latin_america`, `middle_east_africa`, `other` (open-ended).
- `semver`: SemVer 2.0.0 pattern (the semver.org reference regex), `maxLength` 128.

Catalog entity properties (all optional, defaults shown by the `$defs`):
- `Agent`: `tags`, `capabilities`, `environment`. `Tool`: `tags`, `capabilities`, `environment`. `AgentVersion`: `tags`, `capabilities`, `semver` (`semver` or null, default null).
- `Service`, `McpServer`, `ModelDeployment`: `tags`, `environment`.
- `GroundingSource`: `tags`, `environment`, `sensitivity_categories` (array of `sensitivity_category`, `uniqueItems`, `maxItems` 10, `default: []`), `residency_geography` (`residency_geography` or null, default null).

New catalog schemas:
- `catalog/v1/entity_revision.schema.json` -> `EntityRevision` {`schema_version`, `revision_id` (`<entity canonical id>@<entity_version>`), `entity_id`, `entity_type`, `entity_version`, `previous_version` (int or null), `cloud`, `customer_id`, `domain_id`, `operation` (`create`|`update`|`deprecate`|`recertify`|`retire`|`import`|`projection`), `recorded_at`, `recorded_by` (`person_id` or null for workers), `changed_fields` (top-level property names, max 64), `change_reason` (1-500 chars or null), `audit_id` (lowercase UUID or null), `correlation_id` (or null), `body_sha256` (`^sha256:[a-f0-9]{64}$`), `body` (anyOf the 14 entity schemas, pinned by `entity_type`)}.
- `catalog/v1/entity_revision_diff.schema.json` -> `EntityRevisionDiff` {`schema_version`, `entity_id`, `entity_type`, `from_version`, `to_version`, `changes` (max 200 of `{path` JSON Pointer `^(/[a-z0-9_]{1,64}){1,6}$`, `op` `added`|`removed`|`changed`, `before`, `after}`), `capability_changes` {`added`, `removed`}, `tag_changes` {`added`, `removed`}, `truncated`}.

Recommendations (`recommendations/v1/`):
- `recommendation.schema.json`: `kind` adds `configuration_finding`, `unregistered_ai_resource`; `/allOf/0/else` becomes "score required unless kind is one of the two"; appended `allOf` member pins `advisory: true` and `method: rule` for them.
- `agent-match-request.schema.json` -> `AgentMatchRequest` {`schema_version`, `task_text` (3-2000 chars, no control characters except tab and newline; tokenized only, never executed or stored), `candidate_types` (`agent`|`tool`, default `["agent"]`), `required_capabilities` (`capabilities`, max 16), `preferred_tags` (`tags`, max 16), `context_entity_ids` (canonical ids, max 20), `environment` (or null), `limit` (1-50, default 10), `max_graph_depth` (0-3, default 2)}. No scope-shaped field.
- `agent-match-response.schema.json` -> `AgentMatchResponse` {`schema_version`, `match_id` (opaque id), `domain_id`, `generated_at`, `ranker` {`ranker_id`, `ranker_version`}, `cold_start`, `signals_unavailable` (signal names), `candidates` (max 50 of `AgentMatchCandidate`), `truncated`, `partial_reason` (`limit`|`timeout_ms`|null)}; `$defs/candidate` -> `AgentMatchCandidate` {`rank`, `entity_id`, `entity_type` (`agent`|`tool`), `display_name`, `lifecycle_status`, `score` (0-1, relative, not a probability), `signals`, `matched_capabilities`, `matched_tags`, `relations` (max 20 of {`relation_type`, `entity_id`, `direction` `outgoing`|`incoming`}), `evidence_ids`}; `$defs/signal` -> `AgentMatchSignal` {`signal` (`capability_match`|`tag_match`|`text_match`|`graph_proximity`|`historical_success`|`latency`|`usage`|`feedback_prior`), `value` (0-1 or null), `weight` (0-1), `contribution` (-1 to 1), `detail_code` (or null), `evidence_ids`}.
- `agent-match-feedback-request.schema.json` -> `AgentMatchFeedbackRequest` {`schema_version`, `match_id`, `entity_id`, `decision` (`accepted`|`rejected`), `reason_code` (`not_relevant`|`missing_capability`|`poor_quality`|`unavailable`|`policy`|`other`|null)}.
- `agent-match-feedback.schema.json` -> `AgentMatchFeedback` (stored) {`schema_version`, `feedback_id`, `cloud`, `customer_id`, `domain_id`, `match_id`, `entity_id`, `entity_type`, `decision`, `reason_code`, `rank_at_decision`, `score_at_decision`, `task_digest` (`^sha256:[a-f0-9]{64}$` of the normalized task text), `required_capabilities`, `ranker`, `decided_by` (person pseudonym id), `decided_at`, `expires_at` (or null)}.

Query (`query/v1/structured-query.schema.json`): `keyword_field` adds `tag`, `capability`, `sensitivity_category`, `residency_region`, `residency_geography`; `boolean_field` adds `contains_personal_data`. Documented semantics on list-valued fields: `eq` = contains, `in` = contains any, `ne`/`not_in` = contains none.

Compliance: `compliance/v1/control.schema.json` `$defs/framework_id` adds `soc2_tsc`, `iso_27001_annex_a`, `gdpr`, `nist_800_53_r5`, `eu_ai_act`, `iso_42001` (fold F2; every compliance schema that `$ref`s it inherits them).

Telemetry (fold F1, `telemetry/v1/telemetry-event.schema.json`, all optional and nullable, default null, `schema_version` minor bump):
- `tool` -> {`external_tool_id` (length-capped string or null), `canonical_tool_id` (catalog canonical id or null), `tool_name` (length-capped string or null)}; at least one member present when `tool` is not null.
- `service` -> {`external_service_id`, `canonical_service_id`}, same rules.
- `mcp_server_ref` -> length-capped string (canonical McpServer id or external reference) or null.
These are the names PRP-99 and PRP-100 were written against. `payload_ref` and the body-free rule are unchanged.

Map (new area `map/v1/`, fragment schemas without `schema_version`):
- `map-node-facets.schema.json` -> `MapNodeFacets` {`entity_type` (catalog `entity_type` or null for clusters), `environment`, `cloud` (or null), `tags`, `lifecycle_status` (or null), `discovery` (`declared`|`telemetry`|`import`|`unknown`, default `unknown`), `health` (`ok`|`degraded`|`failing`|`unknown`, default `unknown`), `error_rate` (0-1 or null), `error_count` (>=0 or null), `request_count` (>=0 or null), `last_error_at` (or null), `sensitivity_categories`, `residency_geography` (or null)}.
- `map-topology-change.schema.json` -> `MapTopologyChange` {`domain_id`, `changed_at`, `change_kinds` (1+ of `node_added`|`node_removed`|`node_updated`|`edge_added`|`edge_removed`|`edge_updated`), `entity_ids` (max 50), `refetch` (bool), `truncated` (bool)}.

### Patterns to match
- Additive revision with validators row and test file: `tests/contracts/test_catalog_query_revisions.py` (PRP-37 item 3).
- Body pinned by kind: `admin/v1/admin-config-document.schema.json` `body` and its `allOf`.
- Kebab-case area file and `$id`: `recommendations/v1/recommendation.schema.json:1-5`; snake_case catalog files: `catalog/v1/agent_version.schema.json`.
- Fragment schema: `actions/v1/target-ref.schema.json`.
- Examples manifest entries with `derived_from` and `expected_error`: `recommendations/v1/examples/manifest.json`.

### Gotchas
- New fields change every `model_dump()` of the touched entities (`packages/core/neurosphere_core/catalog/repo/documents.py:121-123` dumps the full model), so tests that compare a whole dumped body, search-index digests and `services/api/openapi.json` change. Find them before pushing: grep tests for `model_dump(` on catalog entities and run the consumer sweep in item 5.
- `packages/contracts/scripts/test_generate.py` pins the area set; the new `map` area fails it until added. ADR-0004 lists the areas too.
- Pydantic ignores `if/then` (ADR-0004): the revision body pin, the finding-kind rules and the cloud-prefix pins are JSON Schema tests, not model behaviour.
- `KIND_LABELS` in `frontend/src/features/recommendations/strings.ts` is exhaustive over the generated union; the frontend typecheck fails until both labels exist. Do not add the kinds to `RECOMMENDATION_KINDS` in `types.ts` (PRP-61 owns the filter list).
- Generated `$defs` become exported classes; avoid titles that collide with existing exports in `ts/src/index.ts` (`Budget`, `Page`, `Grant`). The names above were checked against the current index.
- `catalog/v1/common.schema.json` is a library schema (`contract_support.py:41`): no examples for it, but each entity's new fields need examples in the catalog manifest.
Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - packages/contracts/**
  - tests/contracts/**
  - docs/adr/0004-contract-versioning.md
  - frontend/src/features/recommendations/strings.ts
tier1:
  - packages/contracts/schemas/**
tier2_appends: []
must_not_touch:
  - services/**
  - packages/core/**
  - sandbox/**
  - connectors/**
  - infra/**
  - frontend/src/features/recommendations/types.ts
  - frontend/src/features/map/**
  - frontend/src/features/catalog/**
```

## Implementation blueprint

Parallelization: items 1 to 4 and item 7 are serial (they share the generated Python and TypeScript output and `ts/src/index.ts`; item 7 follows item 4). Item 5 after 7; item 6 last.

### Item 1 - Catalog vocabulary, entity fields and query allowlist
- Deliverable: the catalog `$defs` and entity properties in "Interfaces provided"; examples (agent tagged, tool with capabilities, grounding source with categories and geography; invalid uppercase tag, unknown environment, duplicate category); `StructuredQuery` keyword and boolean additions; `FIELD_APPLICABILITY` rows; regenerated bindings.
- Owned files: `packages/contracts/schemas/catalog/v1/**`, `packages/contracts/schemas/query/v1/**`, generated output, `tests/contracts/validators.py`, `tests/contracts/test_catalog_restored_fields.py` (new).
- Must NOT touch: `catalog/v1/canonical_id.schema.json`, `id-corpus.json`, any relation schema.
- Depends on: none.
- Acceptance criteria: criteria 3, 4 and 8; every existing catalog and query example validates; the additive-only test passes.
- Tests: `tests/contracts/test_catalog_restored_fields.py`, `tests/contracts/test_catalog_query_revisions.py`, `tests/contracts/test_schemas.py`, `test_roundtrip.py`, `test_additive_only.py`.
- Pattern references: `tests/contracts/test_catalog_query_revisions.py`, `catalog/v1/mcp_server.schema.json` (`protocol_versions` array default).

### Item 2 - Entity revision and diff
- Deliverable: `entity_revision.schema.json` and `entity_revision_diff.schema.json` with examples (an agent `update` revision, a grounding-source `create` revision; invalid: tool body under `entity_type: agent`, missing `body_sha256`, 201 changes); bindings.
- Owned files: the two schemas and their examples, generated output, `tests/contracts/test_entity_revision.py` (new).
- Must NOT touch: entity schemas (item 1 owns them).
- Depends on: item 1.
- Acceptance criteria: criterion 5; `revision_id` must end in `@<entity_version>` (core validator documented for PRP-76; JSON Schema checks the shape); a Python validator `check_revision_version_order` in `tests/contracts/validators.py` asserts `previous_version < entity_version` and `from_version < to_version`.
- Tests: `tests/contracts/test_entity_revision.py`.
- Pattern references: `admin/v1/admin-config-document.schema.json`, `tests/contracts/test_admin_platform_schemas.py`.

### Item 3 - Agent match contracts and the two finding kinds
- Note: the finding-kind part (recommendation `kind` values, score rule, the two `strings.ts` labels, `test_recommendation_finding_kinds.py`) is already shipped by PRP-61 if present on main at execution: verify, then skip that part. The agent-match schemas still ship here.
- Deliverable: the four `agent-match-*` schemas with examples (cold-start response with `historical_success` value null, scored response, accepted feedback; invalid: request with `domain_id`, signal value 1.2, feedback with free-text `comment`); recommendation kind and rule changes with two valid and two invalid examples; manifest entries; bindings; the two labels in `strings.ts` ("Configuration finding", "Unregistered AI resource").
- Owned files: `packages/contracts/schemas/recommendations/v1/**`, generated output, `frontend/src/features/recommendations/strings.ts`, `tests/contracts/test_agent_match.py` (new), `tests/contracts/test_recommendation_finding_kinds.py` (new; the file PRP-61 planned, now here).
- Must NOT touch: `frontend/src/features/recommendations/types.ts`, `services/api/neurosphere_api/recommendations/**`.
- Depends on: item 2.
- Acceptance criteria: criteria 6, 7 and 10; existing validators `check_recommendation_score_interval` and `check_recommendation_same_boundary` pass on the new examples.
- Tests: `tests/contracts/test_agent_match.py`, `tests/contracts/test_recommendation_finding_kinds.py`, `tests/contracts/test_validators.py`.
- Pattern references: `recommendations/v1/examples/valid/recommendation.cold-start-unused-agent.json`, `tests/contracts/test_admin_no_credential_values.py` (field walker style for "no free text" check).

### Item 4 - Compliance framework ids and the map area
- Deliverable: six `framework_id` values (the four plus `eu_ai_act`, `iso_42001`, fold F2) with one valid `Control` example each (paraphrased title, official source URL, no copied text); `map/v1/map-node-facets.schema.json` and `map-topology-change.schema.json` with examples and manifest; `map` added to the area set in `test_generate.py`; bindings.
- Owned files: `packages/contracts/schemas/compliance/v1/**`, `packages/contracts/schemas/map/v1/**` (new), `packages/contracts/scripts/test_generate.py`, generated output, `tests/contracts/test_map_facets.py` (new), `tests/contracts/test_compliance_schemas.py`.
- Must NOT touch: `packages/core/neurosphere_core/compliance/library/**` (PRP-81 adds the framework data).
- Depends on: item 3.
- Acceptance criteria: criterion 9 (all six ids); `MapNodeFacets` rejects `error_rate` 1.5 and an unknown `health`; `MapTopologyChange` rejects empty `change_kinds`; `packages/core/tests/compliance_lib` still passes (library ids unchanged).
- Tests: `tests/contracts/test_map_facets.py`, `tests/contracts/test_compliance_schemas.py`, `packages/contracts/scripts/test_generate.py`.
- Pattern references: `compliance/v1/examples/valid/control.nist-govern-2.json`, `actions/v1/target-ref.schema.json`.

### Item 7 - Telemetry tool, service and MCP-server identity (fold F1)
- Deliverable: the optional nullable `tool`, `service` and `mcp_server_ref` properties of "Interfaces provided" on `telemetry-event.schema.json`, one valid example with them and one invalid (empty `tool` object), examples manifest entries, a minor `schema_version` bump, regenerated Python and TypeScript bindings.
- Owned files: `packages/contracts/schemas/telemetry/v1/**`, generated output, `tests/contracts/test_telemetry_tool_service_identity.py` (new).
- Must NOT touch: `services/api/neurosphere_api/ingest/**`, `packages/core/**`, the `payload_ref` definition.
- Depends on: item 4.
- Acceptance criteria: the fold F1 criterion; every existing telemetry example still validates; the additive-only test passes with empty `ALLOWED_TIGHTENINGS`.
- Tests: `tests/contracts/test_telemetry_tool_service_identity.py`, `test_additive_only.py`, `test_schemas.py`, `test_roundtrip.py`.
- Pattern references: `tests/contracts/test_catalog_restored_fields.py` (item 1), the optional-nullable properties already in `telemetry-event.schema.json`.

### Item 5 - Consumer sweep
- Deliverable: run the consumer suites named in the gates; list every failure caused by the new optional fields. Allowed fixes are test-expectation updates in `tests/contracts/**`; any failure elsewhere (a test pinning a full entity dump, a snapshot) is recorded as a deviation with the file name and fixed only if it is a pure expectation update, never a product-code change; otherwise stop and report.
- Owned files: none new.
- Depends on: item 7.
- Acceptance criteria: the gate suites pass, or each remaining failure is reported with its file and cause.
- Tests: the `uv run pytest` line in "Validation gates".

### Item 6 - Integration and close-out
- Deliverable: ADR-0004 amendment note (PRP-70: the additive changes listed above including fold F1 telemetry identity and fold F2 framework ids, the open-ended enum wording, the `map` area, empty `ALLOWED_TIGHTENINGS`); refresh the additive-only baseline after review; rebase, regenerate Tier-3 (`services/api/openapi.json`, `docs/reference/**`, status table, `PRPs/INDEX.md`, `PRPs/EXECUTION-PLAN.md`); changelog fragment `changelog.d/PRP-70-contracts-revision-restored-scope.md`; completion note that repeats every provided name for PRP-71..83 authors and tells PRP-99, PRP-100, PRP-71 and PRP-128 authors the F1 and F2 names (PRP-61 has already shipped its own contract changes).
- Owned files: `docs/adr/0004-contract-versioning.md`, `tests/contracts/fixtures/v1-baseline/**`, this PRP file, Tier-3 files per reference section 2.
- Depends on: items 1-5 and 7.
- Acceptance criteria: validation gates pass; CI green including `contracts`.

## Cut line
If the session runs low on context, the `map/v1` area (item 4, second half: `MapNodeFacets`, `MapTopologyChange`, the `test_generate.py` area-set change) and the entity-revision contract (item 2: `EntityRevision`, `EntityRevisionDiff`, `check_revision_version_order`) move to a follow-up PRP. Item 7 (fold F1) and the F2 framework ids never move: PRP-71, PRP-100 and PRP-128 code against them. Everything else (items 1 and 3, the compliance framework ids, item 7, the consumer sweep and close-out) still ships as a mergeable unit; the PRP completion note names the follow-up. PRP-74 (map facets and topology push) and PRP-76 (revision store, version history and diff) are then BLOCKED on that follow-up. Acceptance criteria recorded unmet in that case: criterion 5 (`EntityRevision` and `EntityRevisionDiff`) and the `MapNodeFacets` and `MapTopologyChange` clauses of the item 4 acceptance (rejects `error_rate` 1.5, unknown `health`, empty `change_kinds`); the `generate.py --check` and additive-only criteria must still pass on what shipped.

## Validation gates
```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
python packages/contracts/scripts/generate.py --check
uv run pytest -q tests/contracts packages/contracts/scripts packages/core/tests/catalog packages/core/tests/search packages/core/tests/copilot packages/core/tests/compliance_lib packages/core/tests/recommendations_cosmos services/api/tests/catalog_api services/api/tests/map services/api/tests/copilot_api services/api/tests/compliance_api sandbox/tests services/api/tests/test_openapi_drift.py tests/docs/test_reference_coverage.py
pnpm --filter ./packages/contracts/ts test
pnpm --filter ./packages/contracts/ts typecheck
pnpm --filter @neurosphere/frontend typecheck
pnpm --filter @neurosphere/frontend test
python scripts/validate_planning.py
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```

## Migration and rollback
All changes are additive inside `v1`: new optional properties with defaults, new `$defs`, new schema files, new enum values, one loosened conditional. Stored catalog documents and recommendations without the new fields stay valid; no container or data migration. Nothing writes the new fields until PRP-71..83 ship, so revert is `git revert` plus a contracts regeneration; once later PRPs persist the new fields, revert is no longer safe without a `v2` (ADR-0004).

## Live and open gates
None. Contract work is fully provable offline.

## NOT building
Routes, stores, containers, seeds, UI, the matcher, the revision writer, the residency check, the framework library YAML, the PRP-61 API literal and filter list, a closed capability taxonomy, a `v2` of any schema, a metadata-completeness contract (PRP-76 keeps it API-local unless its writer asks for one).

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [x] All clarification questions are decided, not guessed (rows 2 and 3 confirmed by the owner at plan approval, 2026-11-19)

## Execution state
Plan approved 2026-11-19: one serial lane (1, 2, 3, 4, 7), consumer sweep (5), one review pass on the whole integration diff, close-out (6). Item 3's finding-kind part is already on main (PRP-61): verified, skipped; `strings.ts` is not edited.

| Item | Status | Branch/worktree | Model | Evidence | Updated |
|---|---|---|---|---|---|
| 1 | merged | worktree-agent-aabdf031f856e5395 | sonnet | orchestrator re-run: generate --check OK (104 py, 74 ts), pytest tests/contracts + scripts 2724 passed, ruff, pyright 0 errors, ts 168 passed; dc344adb, merge 3dd87616. Deviation: duplicate-category invalid example is an inline JSON Schema test (Pydantic ignores uniqueItems) | 2026-11-19 |
| 2 | merged | worktree-agent-aadd67d2f248f0069 | sonnet | orchestrator re-run: generate --check OK (106 py, 76 ts), pytest 2804 passed, ruff, pyright 0 errors, ts 171 passed; fd56a191, merge b0cd84d6. Deviations: wrong-body-type case is an inline JSON Schema test (if/then yields several errors, one per invalid file is required); diff before/after typed scalar, array or null, no object (nested changes are deeper paths); examples manifest is index.json | 2026-11-19 |
| 3 | merged | worktree-agent-a88d8be4de11ea9f3 | sonnet | orchestrator re-run: generate --check OK (110 py, 80 ts), pytest 2901 passed, ruff, pyright 0 errors, ts 176 passed, frontend typecheck clean; 8b2421d2, merge c9c26ca4. Finding kinds verified on main (PRP-61), not re-shipped. Extra invalid example for stored feedback (suite needs one per schema) | 2026-11-19 |
| 4 | merged | worktree-agent-a67575ab3efac9132 | sonnet | orchestrator re-run: generate --check OK (114 py, 82 ts), pytest contracts + scripts + compliance_lib 3028 passed, ruff, pyright 0 errors, ts 185 passed; d53b1942, merge ebd4dcc5. Claims scan (tests/marketing/claims_rules.py) covers valid compliance examples only; MapNodeFacets has no required member; entity_ids uniqueItems added | 2026-11-19 |
| 7 | in-progress | | sonnet | | 2026-11-19 |
| 5 | todo | | | | |
| 6 | todo | | | | |

## Completion note (filled at ship)
- Date and PR:
- Provided names (for PRP-71..83 and PRP-61 authors):
- Deviations:
- Descoped items:
- OPEN gates:
- Env vars for the operator: none expected.
- Follow-up issues:
- Product check (can an operator use it without editing files): no, by design; contracts only.
