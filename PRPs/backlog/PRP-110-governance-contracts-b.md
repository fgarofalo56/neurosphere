---
name: PRP-110-governance-contracts-b
status: backlog
priority: P1
order: 110
review: required
created: 2026-11-16
model: opus
orchestrator_model: opus
implementer_model: sonnet
phase: 9
ns: NS-02, NS-03, NS-04, NS-08, NS-09
depends_on: [PRP-99-governance-contracts-a]
wave: W25
branch: prp-110-governance-contracts-b
allow_parallel: true
issues: []
---

# PRP-110: Governance contracts B (identity, labels, estate, risk, safety, incidents)

## Goal
Ship, in one Tier-1 pass on `packages/contracts/**`, the additive `v1` contracts for governance priorities 3 and 4, and nothing above the wire layer except the two core literal mirrors the contract tests pin: agent run-as identity and entitlements (`workload_identity` entity, `runs_as` and `entitled_to` relations, `Entitlement`, the `identity_entitlement` policy rule), customer labels and lineage (`GroundingSource.external_labels`, `LabelMapping`, `LineageEdgeExport`), estate usage (`UsageReport`, three advisory recommendation kinds), the AI risk register (`AiSystem`, `RiskTierDetermination`, `ImpactAssessment`, `SystemCard`, `Attestation`, the CI `RegistrationCheckRequest`/`Response`), `SafetyEvaluationRecord`, and alerts (`AlertRule`, `Incident`, `IncidentTimelineEntry`, `TicketRef`), plus the `ticket_create` and `lineage_push` action kinds. It is for the writers and implementers of PRP-117 to PRP-134, written against "Interfaces provided" now. W25 is the only contracts wave between W20 and W35 (design section 3), so every name those PRPs need must land here.

Out of scope: connectors, stores, containers, workers, routes and UI that use these contracts (PRP-117 runner, PRP-118 identity connector and core catalog models, PRP-120/121 labels and lineage, PRP-122 to PRP-126 estate, PRP-127 register and its containers, PRP-129 CI gate, PRP-130 attestation, PRP-131 cards and safety records, PRP-132 alerts, PRP-133 ticketing); the content channel, policy, notification and approval contracts (PRP-99); platform and credential-kind contracts (PRP-86).

## Why
- The owner asked on 2026-11-16 for "the ultimate team AI governance and auditing tool" with every identified gap planned (`temp/audit/governance-core-design.md` section 0); the contracts split puts identity, labels, estate, risk, safety and alerting here (design 3.3).
- No run-as identity: the catalog has no identity entity (`catalog/v1/common.schema.json` `entity_type`, 14 values) and the closest shapes are `Grant.principal` (`catalog/v1/grant.schema.json:64-80`) and `Owner.owner_kind: service_principal` (`catalog/v1/owner.schema.json:70`); nothing can answer "who could touch this data".
- Purview and Unity Catalog promised and never built: `docs/PRD.md:17` "Purview and Unity Catalog are optional connector integrations; do not assume universal write-back, labeling or OpenLineage support." `GroundingSource` has only `classification`, `residency_region`, `contains_personal_data` (plus PRP-70's categories), no place for a customer label.
- Estate coverage: `docs/connectors/coverage.md:34-40` lists Microsoft 365 Copilot, GitHub Copilot and Anthropic as "not built" and Cursor as "GAP"; there is no usage-report shape for SaaS assistants.
- Risk and lifecycle: no risk tier, impact assessment, card, attestation or CI gate exists (design G-f: "model card", "risk tier", "EU AI Act", "42001" have no hits); safety is only a score dimension (`evaluation/v1/evaluation-result.schema.json:218`).
- Alerts: no incident model and no ticket reference anywhere (design G-g).

## Acceptance criteria
- [ ] Every schema and `$defs` entry in "Interfaces provided" exists with the exact name and title, generates Python and TypeScript bindings, and has at least one valid and one invalid example; `python packages/contracts/scripts/generate.py --check` passes.
- [ ] Additive only: `tests/contracts/test_additive_only.py` passes with an EMPTY `ALLOWED_TIGHTENINGS`; every existing example validates; a `GroundingSource` or `PolicyDefinition` written before this PRP validates unchanged.
- [ ] Given a `WorkloadIdentity` of kind `managed_identity_user` with a lowercase client id, it validates; a `RunsAs` edge from an `agent_version` to it validates and from a `grounding_source` is rejected; an `EntitledTo` edge with an `Entitlement` (plane `data`, access `read`) validates and one without `entitlements` is rejected; `EntityRevision` accepts a `workload_identity` body.
- [ ] `packages/core/tests/catalog/test_protocol_literals.py` passes with the core `EntityTypeName` and `RelationTypeName` literals extended (15 entity types, 12 relation types).
- [ ] A `PolicyDefinition` with an `identity_entitlement` rule validates; its params pinned to that kind; every PRP-99 rule example still validates.
- [ ] `ExternalLabel` rejects an unknown `system` key shape and a label name over 256 characters; `LabelMapping` rejects a mapping to an unknown `sensitivity_category`; `LineageEdgeExport` rejects more than 500 edges and a relation other than `reads` or `writes`.
- [ ] A recommendation of kind `shadow_ai_finding`, `unused_entitlement` or `excess_write_entitlement` with `evidence_status: sufficient` validates without `score` and is rejected with `advisory: false` or `method: statistical`; `cost_spike` without `score` is still rejected.
- [ ] `RiskTierDetermination` requires `determined_by` (a person) and a questionnaire reference, and no example or description states a legal classification or compliance (the PRP-56 claims scanner pattern); `RegistrationCheckResponse.exit_code` is exactly 0, 1 or 2.
- [ ] `SafetyEvaluationRecord` carries findings by severity and evidence by reference only (no prompt or attack text field; the PRP-99 guard walk extended to `evaluation/v1`, `risk/v1`, `incidents/v1`, `estate/v1` finds no body-field or credential-segment property name).
- [ ] `TicketRef.url` has no query string or userinfo; `Incident` and `IncidentTimelineEntry` carry ids and links, never captured content (no property refs `RedactedContent` or `ContentEnvelope`).
- [ ] The SDK `WriteAction` literal test passes with `ticket_create` and `lineage_push`; `pnpm --filter @neurosphere/frontend typecheck` passes with labels for the three new kinds in `KIND_LABELS`.
- PRP exit: touched suites, `generate.py --check`, ruff, pyright, contracts TS tests, frontend typecheck and `validate_planning.py` pass; PR open with CI green including `contracts`; Tier-3 regenerated at merge.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| 1 | Where identity lives | new area; catalog | Catalog: `workload_identity` is a versioned entity like `grant` (PRP-37 precedent), so lineage, scope filtering and the copilot graph tools see it |
| 2 | Entitlement shape | relation attributes; separate store | `Entitlement` fragment carried on the `EntitledTo` edge (1-32 per edge); no separate container |
| 3 | Where label mappings live | own container; `admin_config` | ASSUMPTION: `admin_config` kind `label_mapping` (the PRP-99 choice for operator configuration) |
| 4 | Over-privilege and shadow-AI findings | new schema; recommendation kinds | Recommendation kinds with the PRP-70 rule (`advisory: true`, `method: rule`, no `score`); `unused_entitlement` and `excess_write_entitlement` are ASSUMPTIONS added beyond the design list because PRP-119 (W29) has no contracts owner |
| 5 | Registration check placement | `risk/v1`; `policy/v1` | `policy/v1` beside the decision contracts; the check is a policy read |
| 6 | Free text in risk documents | none; bounded | Bounded customer-authored text in impact assessments and incident notes (max 8000 and 2000 characters); never captured content, never a NeuroSphere verdict |
| 7 | Label precedence | as design | ASSUMPTION (GD-11, recommended default): steward-curated value (locked) over customer label over NeuroSphere inference. Here: recorded in `ExternalLabel` and `LabelMapping` descriptions; PRP-120 implements (GD-49 for the missing field lock) |
| 8 | Risk tier wording | as design | ASSUMPTION (GD-15, recommended default): the risk tier is the customer's recorded determination with the questionnaire as evidence; the product never states a legal classification. Here: `RiskTierDetermination` requires `determined_by` and its description says so |
| 9 | Estate connector order | as design | ASSUMPTION (GD-9, recommended default): estate connector order M365 Copilot and Copilot Studio, GitHub Copilot, ChatGPT Enterprise, Anthropic, Cursor; Entra shadow AI last. Here: `UsageReport.source_system` lists all of them now; order is the connector PRPs' |
| 10 | Entra Agent ID | model now; verify first | `identity_kind` value `entra_agent_id` exists but is documented "used only if PRP-118's verification finds a documented API" (U-9) |
| 11 | CI caller role for the registration check | `ci` role value; read-class roles | ASSUMPTION (GD-45, recommended default): no dedicated CI role: `registration.check` is granted to the read-class roles (viewer, analyst, domain_steward, admin). Here: no role value is added; if the owner chooses a `ci` role, the next contracts owner adds it |
| 12 | Late event classes and dataset reference | leave to consumers; add here | Added here because W26 to W32 have no contracts owner: three `NotificationEventClass` values for PRP-114 and PRP-115, and an optional `SafetyEvaluationRecord.dataset` for PRP-131. Attestation campaigns stay core-local in PRP-130 (no schema) |

## Context manifest

### Files to read first
- `PRPs/backlog/PRP-99-governance-contracts-a.md` - "Interfaces provided" (the conventions, `PolicyRule` pins, `NotificationEventClass`, guard walk) this PRP extends.
- `PRPs/backlog/PRP-70-contracts-revision-restored-scope.md` - `sensitivity_category`, `EntityRevision.body` pins, the finding-kind score rule.
- `docs/adr/0004-contract-versioning.md` - additive rules; PRP-37 traversal bound loosening precedent.
- `packages/contracts/schemas/catalog/v1/grant.schema.json`, `grants_access_to.schema.json`, `common.schema.json` - entity and relation shape to copy.
- `packages/contracts/schemas/catalog/v1/grounding_source.schema.json` - where `external_labels` goes.
- `packages/contracts/schemas/query/v1/structured-query.schema.json:150-155,460-480` - entity list and traversal `relations.maxItems` 10.
- `packages/contracts/schemas/recommendations/v1/recommendation.schema.json:39` - `kind` and the score rule.
- `packages/contracts/schemas/evaluation/v1/evaluation-result.schema.json` - `subject_id` pattern for AgentVersion or ModelDeployment.
- `packages/core/neurosphere_core/catalog/protocol.py:70-97` and `packages/core/tests/catalog/test_protocol_literals.py:33-42` - the literals pinned to the contract.
- `tests/contracts/test_grant_and_mcp_server.py` - the test file shape for a new entity and relation.

### Interfaces consumed
- PRP-99 (W20): `PolicyDefinition`/`PolicyRule`/`PolicyRuleKind` (open-ended), `PolicySeverity`, `NotificationEventClass` (open-ended), `DetectedCategory`, the guard walk `tests/contracts/test_governance_a_guards.py`, `admin_kind` (open-ended), conventions on `TargetRef` ids.
- PRP-70 (W19): `sensitivity_category`, `residency_geography`, `tags`, `environment`, `EntityRevision`, `configuration_finding`/`unregistered_ai_resource` score rule.
- Shipped: catalog entity and relation conventions; `admin/v1/common.schema.json` `https_url`, `principal_id`, `reason_code`.

### Interfaces provided
Naming as PRP-99 (ADR-0004 generated names; catalog files snake_case with `x-ns-name`; other areas kebab-case; fragments without `schema_version`).

Identity (`catalog/v1/`):
- `common.schema.json`: `entity_type` adds `workload_identity`; `relation_type` adds `runs_as`, `entitled_to`.
- `workload_identity.schema.json` -> `WorkloadIdentity` (common entity fields as `service.schema.json`, plus) {`display_name`, `identity_kind` (`app_registration`|`service_principal`|`managed_identity_system`|`managed_identity_user`|`entra_agent_id`|`other`, open-ended), `client_id` (lowercase GUID or null; an identifier, not a credential), `resource_id` (Azure resource id or null), `discovery` (`declared`|`discovered`), `source_connector_id` (slug or null), `tags`}.
- `runs_as.schema.json` -> `RunsAs` relation: source `agent|agent_version|tool|service|mcp_server`, target `workload_identity`; standard edge fields.
- `entitled_to.schema.json` -> `EntitledTo` relation: source `workload_identity`, target `grounding_source|service|model_deployment|mcp_server`; standard edge fields plus `entitlements` (1-32 `Entitlement`).
- `entitlement.schema.json` (fragment) -> `Entitlement` {`grant_kind` (`azure_role_assignment`|`app_role_assignment`|`delegated_permission_grant`|`directory_role`|`data_plane_acl`|`declared`, open-ended), `role_or_permission` (`^[A-Za-z0-9][A-Za-z0-9 ._:/()-]{0,255}$`), `role_definition_ref` (max 1024 or null), `scope_ref` (max 1024 or null), `plane` (`control`|`data`), `access` (`read`|`write`|`admin`), `source` (`entra_graph`|`azure_resource_graph`|`arm`|`declared`|`connector`), `first_observed`, `last_observed`}.
- `query/v1`: entities add `workload_identity`; traversal relations add `runs_as`, `entitled_to`; `relations.maxItems` 10 to 12 (a loosening; PRP-37 precedent); `FIELD_APPLICABILITY` rows.
- `entity_revision.schema.json` (PRP-70): `body` anyOf and kind pin add `WorkloadIdentity`.
- Core mirrors: `EntityTypeName` gains `workload_identity`, `RelationTypeName` gains `runs_as`, `entitled_to` (`packages/core/neurosphere_core/catalog/protocol.py`); no core model is added (PRP-118 adds it; until then the repository refuses such documents).
- `policy/v1/policy-definition.schema.json`: `PolicyRuleKind` adds `identity_entitlement`; `IdentityEntitlementParams` {`access` (`read`|`write`|`admin`), `plane` (`control`|`data`|`any`), `sensitivity_categories` (0-10), `allowed_when` (`agent_version_approved`|`exception_only`), `unused_for_days` (1-365 or null)}; appended `allOf` pin.

Labels and lineage (`catalog/v1/`):
- `grounding_source.schema.json`: `external_labels` (max 32 `ExternalLabel`, default []); `common.schema.json` `$defs/external_label` -> `ExternalLabel` {`system` (`purview`|`unity_catalog`|`manual`, open-ended), `label_kind` (`sensitivity_label`|`classification`|`tag`), `label_id` (1-256), `label_name` (1-256), `source_asset_ref` (max 1024 or null), `observed_at`}.
- `label_mapping.schema.json` -> `LabelMapping` (body of new `admin_kind: label_mapping`) {`schema_version`, `mapping_id` (slug), `cloud`, `customer_id`, `domain_id`, `system`, `entries` (max 512 of {`label_kind`, `label_id`, `sensitivity_categories` (1-10), `classification` (catalog `classification` or null)}), `version`}.
- `lineage_edge_export.schema.json` -> `LineageEdgeExport` (the proposed diff of `lineage_push`) {`schema_version`, `export_id`, `cloud`, `customer_id`, `domain_id`, `target_system` (`purview`|`unity_catalog`), `edges` (1-500 of {`source_id` (agent or agent_version id), `target_id` (grounding_source id), `relation_type` (`reads`|`writes`), `external_target_ref` (1-1024), `evidence_ids` (max 20)}), `generated_at`}.
- `connectors/v1/connector-manifest.schema.json` actions add `lineage_push`, `ticket_create`; SDK `WriteAction` mirrors them.

Estate (new area `estate/v1/`):
- `usage-report.schema.json` -> `UsageReport` {`schema_version`, `report_id`, `cloud`, `customer_id`, `domain_id`, `source_system` (`m365_copilot`|`copilot_studio`|`github_copilot`|`cursor`|`openai_enterprise`|`anthropic_claude`|`claude_code`|`other`, open-ended), `connector_id`, `period_start`, `period_end`, `granularity` (`day`|`week`|`month`|`period_total`; as declared by the vendor), `metrics` (max 64 of {`metric` (`seats_assigned`|`seats_active`|`active_users`|`interactions`|`suggestions_shown`|`suggestions_accepted`|`lines_accepted`|`agents_published`|`cost`, open-ended), `feature` (token or null), `value` (number >= 0 or null: unknown is null, never 0), `unit` (`count`|`currency`|`tokens`), `currency` (ISO 4217 or null)}), `per_user_available` (bool; aggregates only are stored), `collected_at`}.
- `recommendations/v1/recommendation.schema.json`: `kind` adds `shadow_ai_finding`, `unused_entitlement`, `excess_write_entitlement`; the score exemption and the `advisory`/`method` pin extend to them.

Risk (new area `risk/v1/`; containers `ai_systems`, `impact_assessments` declared by PRP-127):
- `ai-system.schema.json` -> `AiSystem` {`schema_version`, `ai_system_id` (slug), `version`, `cloud`, `customer_id`, `domain_id`, `display_name`, `member_ids` (1-64 agent, agent_version or model_deployment ids), `owner_ids` (person ids), `intended_use` (0-2000), `state` (`draft`|`registered`|`retired`), `current_determination_id` (or null), `created_at`, `updated_at`}.
- `risk-tier.schema.json` -> `RiskTierDetermination` {`schema_version`, `determination_id`, `ai_system_id`, `framework` (`eu_ai_act`|`nist_ai_rmf`|`iso_42001`|`internal`, open-ended), `tier` (`prohibited`|`high`|`limited`|`minimal`|`not_determined`, open-ended; these framework tier tokens are placeholders to be verified by PRP-128 against the official sources, not authoritative, and the description says so), `questionnaire_id`, `questionnaire_version`, `answers` (max 100 of {`question_id`, `answer` (`yes`|`no`|`unknown`|`not_applicable`), `note` (0-500)}), `determined_by` (person id, required), `determined_at`, `review_item_id` (or null)}.
- `impact-assessment.schema.json` -> `ImpactAssessment` {`schema_version`, `assessment_id`, `ai_system_id`, `version`, `status` (`draft`|`in_review`|`approved`|`rejected`|`superseded`), `template_id`, `sections` (max 50 of {`section_id`, `title` (1-200), `response` (0-8000), `control_ids` (max 32)}), `review_item_id`, `approved_at`, `audit_id` (or null)}.
- `system-card.schema.json` -> `SystemCard` {`schema_version`, `card_id`, `card_kind` (`agent_card`|`model_card`), `subject_id`, `generated_at`, `fields` (max 100 of {`field_id`, `value` (0-2000 or null), `source_kind` (`catalog`|`evaluation`|`safety_evaluation`|`policy`|`risk`|`not_recorded`), `source_ref` (max 512 or null)}), `export_sha256`}.
- `attestation.schema.json` -> `Attestation` {`schema_version`, `attestation_id`, `cloud`, `customer_id`, `domain_id`, `subject_id`, `attestation_kind` (`owner_recertification`|`agent_attestation`), `campaign_id` (or null), `statement_code` (`still_owned`|`still_needed`|`config_reviewed`|`retire_requested`, open-ended), `status` (`pending`|`attested`|`overdue`|`waived`), `due_at`, `attested_by`, `attested_at` (or null), `evidence_ids`}. No campaign schema: `campaign_id` is an opaque record id and PRP-130 keeps its `AttestationCampaign` model core-local (its own container from PRP-127), because no other PRP reads a campaign over the wire.
- `policy/v1/registration-check-request.schema.json` -> `RegistrationCheckRequest` {`schema_version`, `agent_id`, `agent_version_id` (one required), `semver` (or null), `config_hash` (or null), `environment`, `pipeline` ({`provider` (`github_actions`|`azure_devops`|`jenkins`|`other`), `run_ref` (`^[A-Za-z0-9._/-]{1,256}$`)})}; `registration-check-response.schema.json` -> `RegistrationCheckResponse` {`schema_version`, `check_id`, `result` (`pass`|`fail`|`warn`), `exit_code` (0 pass, 1 fail, 2 unknown or error), `checks` (max 16 of {`check` (`registered`|`approved`|`policy_clean`|`risk_assessed`|`safety_evaluated`), `status` (`pass`|`fail`|`warn`|`not_applicable`|`unknown`), `reason_code`, `evidence_ref` (or null)}), `decided_at`}.

Safety (`evaluation/v1/`):
- `safety-evaluation-record.schema.json` -> `SafetyEvaluationRecord` {`schema_version`, `record_id`, `cloud`, `customer_id`, `domain_id`, `subject_id` (agent_version or model_deployment), `method` (`red_team_manual`|`red_team_automated`|`benchmark`|`content_safety_eval`|`other`), `origin` (`imported`|`internal`), `tool_ref` (token or null), `attack_categories` (max 32 tokens), `performed_at`, `performed_by` (person id or null), `findings_by_severity` ({`critical`, `high`, `medium`, `low`, `info`}: int >= 0 or null), `passed` (bool or null), `evidence_refs` (max 50 pointers), `imported_artifact_sha256` (or null), `dataset` ({`dataset_id` (token), `dataset_version` (token)} or null; optional, default null: the evaluation dataset PRP-131 shows on the card), `recorded_by`, `recorded_at`}.

Alerts (new area `incidents/v1/`; containers `alert_rules`, `incidents` declared by PRP-127):
- `alert-rule.schema.json` -> `AlertRule` {`schema_version`, `alert_rule_id`, `version`, `cloud`, `customer_id`, `domain_id`, `display_name`, `source` (`policy_violation`|`budget_threshold`|`recommendation`|`control_failure`|`capture_failure`, open-ended), `conditions` ({`min_severity`, `policy_ids` (max 32), `recommendation_kinds` (max 16), `control_ids` (max 32), `count_threshold` (1-1000), `window_minutes` (1-10080)}), `on_match` (`notify`|`open_incident`|`notify_and_open_incident`), `enabled`}.
- `incident.schema.json` -> `Incident` {`schema_version`, `incident_id`, `version`, `cloud`, `customer_id`, `domain_id`, `title` (1-200), `severity` (`PolicySeverity`), `status` (`open`|`acknowledged`|`mitigated`|`resolved`|`closed`), `owner_id` (or null), `alert_rule_id` (or null), `opened_at`, `acknowledged_at`, `resolved_at`, `links` (max 100 of {`link_kind` (`policy_violation`|`recommendation`|`interaction_record`|`audit_record`|`map_node`|`action_intent`|`control`), `ref`}), `affected_entity_ids` (max 100), `ticket_refs` (max 8 `TicketRef`), `correlation_id`}.
- `incident-timeline-entry.schema.json` -> `IncidentTimelineEntry` {`schema_version`, `entry_id`, `incident_id`, `at`, `entry_kind` (`opened`|`status_changed`|`linked`|`owner_changed`|`note`|`ticket_created`|`notification_sent`|`action_proposed`|`action_executed`), `actor_id` (or null for workers), `status_from`, `status_to`, `ref` (or null), `note` (0-2000)}.
- `ticket-ref.schema.json` (fragment) -> `TicketRef` {`system` (`github_issues`|`servicenow`|`jira`), `ticket_key` (`^[A-Za-z0-9#._/-]{1,128}$`), `url` (`https_url`), `created_at`, `intent_id`, `audit_id`}.
- `notifications/v1` `NotificationEventClass` adds `incident_opened`, `incident_status_changed`, `attestation_due`, `attestation_overdue`, `ticket_created`, `shadow_ai_detected`, and for PRP-114 and PRP-115 (W26-W27, no contracts owner) `budget_projection_exceeds_limit`, `budget_not_evaluable`, `sdk_guard_fail_open_reported` (`budget_threshold_crossed` is PRP-99's).

### Patterns to match
- New entity and relation with tests: `tests/contracts/test_grant_and_mcp_server.py` (PRP-37); PRP-99 items 1-5 for areas, pins and the guard walk.
- Score exemption and pins: the PRP-70 change to `recommendation.schema.json` `/allOf`.
- Body pinned by kind: `admin/v1/admin-config-document.schema.json`.

### Gotchas
- `packages/core/tests/catalog/test_protocol_literals.py:33-42` pins the core literals to the contract and asserts the counts (14 and 10): update literals and counts in the same item.
- `EntityRevision.body` (PRP-70) is an anyOf of every entity schema pinned by `entity_type`; leaving `WorkloadIdentity` out makes revisions of the new entity invalid.
- `KIND_LABELS` in `frontend/src/features/recommendations/strings.ts` is exhaustive over the generated union; do not touch `types.ts` (PRP-61/126 own the filter list).
- New areas `estate`, `risk`, `incidents` go into `EXPECTED_AREAS` (`packages/contracts/scripts/test_generate.py`) and the ADR area list.
- Use generated identifiers only in examples: no real tenant, client, subscription or object ids; a GUID-shaped `client_id` example uses an obviously synthetic value.
- Titles checked against `ts/src/index.ts`: no collision with `Policy`, `Grant`, `Budget`, `Page`, `ApprovalDecision` or PRP-99 names.
Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - packages/contracts/**
  - tests/contracts/**
  - docs/adr/0004-contract-versioning.md
  - connectors/sdk-python/neurosphere_connector/manifest.py
  - frontend/src/features/recommendations/strings.ts
  - packages/core/tests/catalog/test_protocol_literals.py
tier1:
  - packages/contracts/schemas/**
tier2_appends:
  - packages/core/neurosphere_core/catalog/protocol.py
must_not_touch:
  - services/**
  - packages/core/neurosphere_core/catalog/repo/**
  - packages/core/neurosphere_core/compliance/**
  - connectors/reference/**
  - connectors/agent-sdk-python/**
  - infra/**
  - frontend/src/features/recommendations/types.ts
```

## Implementation blueprint

Parallelization: items 1 to 6 are serial (shared generated output and `ts/src/index.ts`); item 7 after 6; item 8 last.

### Item 1 - Identity: entity, relations, entitlement, rule kind
- Deliverable: `workload_identity`, `runs_as`, `entitled_to`, `Entitlement`; query entities and relations; `EntityRevision` pin; `identity_entitlement` with `IdentityEntitlementParams`; core literal mirrors; examples (managed identity; run-as edge; entitled edge with two entitlements; invalid: edge from a grounding source, entitlement with access `owner`, edge without entitlements).
- Owned files: `packages/contracts/schemas/{catalog,query,policy}/v1/**`, generated output, `packages/core/neurosphere_core/catalog/protocol.py` (two literal appends), `packages/core/tests/catalog/test_protocol_literals.py`, `tests/contracts/test_governance_b_identity.py` (new).
- Depends on: PRP-99 merged.
- Acceptance criteria: criteria 3, 4, 5.
- Tests: `tests/contracts/test_governance_b_identity.py`, `tests/contracts/test_grant_and_mcp_server.py`, `packages/core/tests/catalog/test_protocol_literals.py`.
- Pattern references: `catalog/v1/grant.schema.json`, `grants_access_to.schema.json`.

### Item 2 - Labels and lineage
- Deliverable: `ExternalLabel`, `GroundingSource.external_labels`, `LabelMapping` with `admin_kind: label_mapping` and its body pin, `LineageEdgeExport`, manifest `lineage_push`; examples.
- Owned files: `packages/contracts/schemas/{catalog,admin,connectors}/v1/**`, `connectors/sdk-python/neurosphere_connector/manifest.py`, generated output, `tests/contracts/test_governance_b_labels.py` (new).
- Depends on: item 1.
- Acceptance criteria: criterion 6; SDK literal test.
- Tests: that file, `connectors/sdk-python/tests`, `tests/contracts/test_connector_manifest.py`.

### Item 3 - Estate usage and finding kinds
- Deliverable: `estate/v1/usage-report.schema.json`; the three recommendation kinds and the extended score rule; `KIND_LABELS` ("Shadow AI finding", "Unused entitlement", "Write entitlement used read-only"); examples.
- Owned files: `packages/contracts/schemas/{estate,recommendations}/v1/**`, `packages/contracts/scripts/test_generate.py`, `frontend/src/features/recommendations/strings.ts`, generated output, `tests/contracts/test_governance_b_estate.py` (new).
- Depends on: item 2.
- Acceptance criteria: criterion 7.
- Tests: that file, `tests/contracts/test_recommendation_finding_kinds.py`.

### Item 4 - Risk register and registration check
- Deliverable: the five `risk/v1` schemas and the two `policy/v1` registration-check schemas; examples with paraphrased product wording only.
- Owned files: `packages/contracts/schemas/{risk,policy}/v1/**`, generated output, `tests/contracts/test_governance_b_risk.py` (new).
- Depends on: item 3.
- Acceptance criteria: criterion 8.
- Tests: that file; the PRP-56 claims scanner over the new examples.

### Item 5 - Safety evaluation record
- Deliverable: `evaluation/v1/safety-evaluation-record.schema.json` with an imported red-team record and an internal benchmark carrying a `dataset` reference; invalid: a `prompt` property, a negative count.
- Owned files: `packages/contracts/schemas/evaluation/v1/**`, generated output, `tests/contracts/test_governance_b_safety.py` (new).
- Depends on: item 4.
- Acceptance criteria: criterion 9 (safety part).

### Item 6 - Alerts, incidents and ticket references
- Deliverable: the four `incidents/v1` schemas, manifest `ticket_create`, the nine notification event classes; examples.
- Owned files: `packages/contracts/schemas/{incidents,notifications,connectors}/v1/**`, `connectors/sdk-python/neurosphere_connector/manifest.py`, generated output, `tests/contracts/test_governance_b_incidents.py` (new).
- Depends on: item 5.
- Acceptance criteria: criteria 10, 11.

### Item 7 - Guard walk and consumer sweep
- Deliverable: extend `tests/contracts/test_governance_a_guards.py` to the new areas (body-field names, credential segments, no `$ref` to the two content schemas); run the gate suites; record failures; fix only expectation updates in `tests/contracts/**`.
- Owned files: `tests/contracts/test_governance_a_guards.py`.
- Depends on: item 6.
- Acceptance criteria: criterion 9; gate suites pass or each failure is reported.

### Item 8 - Integration and close-out
- Deliverable: ADR-0004 amendment (PRP-110 areas, open-ended enums, the 10-to-12 traversal loosening); baseline refresh after review; Tier-3 regeneration; changelog fragment `changelog.d/PRP-110-governance-contracts-b.md`; completion note listing every provided name.
- Owned files: `docs/adr/0004-contract-versioning.md`, `tests/contracts/fixtures/v1-baseline/**`, this PRP file, Tier-3 files.
- Depends on: items 1-7.
- Acceptance criteria: validation gates pass; CI green including `contracts`.

## Cut line
If the session overruns, items 4 and 6 (risk register, registration check, incidents, `ticket_create`, the incident event classes) move to a serial first item of PRP-127 (W30; no other contracts owner in W30), which then also owns `packages/contracts/**` for that item. Consequence: PRP-132 (also W30) becomes `[serial-after: PRP-127]`, and PRP-129 and PRP-131 read the names from PRP-127's completion note. Items 1-3, 5, 7, 8 still merge as a unit; criteria 8 and 10 are recorded unmet here.

## Validation gates
```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
python packages/contracts/scripts/generate.py --check
uv run pytest -q tests/contracts packages/contracts/scripts connectors/sdk-python/tests packages/core/tests/catalog packages/core/tests/search packages/core/tests/recommendations_cosmos packages/core/tests/admin packages/core/tests/compliance_lib services/api/tests/catalog_api services/api/tests/test_openapi_drift.py
pnpm --filter ./packages/contracts/ts test
pnpm --filter ./packages/contracts/ts typecheck
pnpm --filter @neurosphere/frontend typecheck
pnpm --filter @neurosphere/frontend test
python scripts/validate_planning.py
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```

## Migration and rollback
Additive inside `v1`: new areas, files, optional properties with defaults, enum values on fields documented open-ended, appended `allOf` members, one loosened bound. No stored document changes; no container is created. Core refuses `workload_identity` documents and `label_mapping` configuration until PRP-118 and PRP-120 register them (fail closed). Revert is `git revert` plus regeneration while nothing persists the new shapes; afterwards a `v2` is required.

## Live and open gates
None. Contract work is provable offline. Every vendor field these shapes will hold is verified by the consuming connector PRP's first item (design section 9, U-7 to U-17).

## NOT building
Connectors, stores, routes, workers, UI and core catalog models. No legal risk classification, EU AI Act, ISO/IEC 42001 or NIST determination, certification or compliance claim (design section 8 item 10). No claim that entitlements are complete: data-plane permissions inside each data service are mostly out of reach (item 8). Entra Agent ID only if verified (item 9). Lineage push-back only where a verified API accepts it (item 11). No per-prompt SaaS content shape: `UsageReport` holds aggregates only (item 3). No parity claim with Microsoft Purview.

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [ ] All clarification questions are decided, not guessed (rows 3, 4 and the GD rows are ASSUMPTIONS for plan approval)

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
- Provided names (for PRP-117 to PRP-134 authors):
- Deviations:
- Descoped items:
- OPEN gates:
- Env vars for the operator: none expected.
- Follow-up issues:
- Product check (can an operator use it without editing files): no, by design; contracts only.
