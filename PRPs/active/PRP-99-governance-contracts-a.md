---
name: PRP-99-governance-contracts-a
status: active
started: 2026-11-22
priority: P0
order: 99
review: required
created: 2026-11-16
model: opus
orchestrator_model: opus
implementer_model: sonnet
phase: 9
ns: NS-01, NS-04, NS-06, NS-08
depends_on: [PRP-70-contracts-revision-restored-scope]
wave: W20
branch: prp-99-governance-contracts-a
allow_parallel: true
issues: []
---

# PRP-99: Governance contracts A (interaction audit, policy, notifications, approval)

## Goal
Ship, in one Tier-1 pass on `packages/contracts/**`, every additive `v1` contract the north-star governance chain (PRP-100 to PRP-109) codes against, and nothing above the wire layer except one inert core role member: the opt-in content channel (a transient `ContentEnvelope`, a secret-free `RedactedContent`, metadata-only `payload_ref` extensions), a new `interactions/v1` area (interaction record, detection finding, capture policy, access purpose, export manifest), a new `policy/v1` area (typed policy definitions, violations, exceptions, the decision request and response, enforcement bindings), a new `notifications/v1` area (channel, subscription, delivery record), `AgentVersion.approval`, six new action kinds, the estate connector kinds, three new system-setting members, three new admin config kinds and the privileged `interaction_investigator` role. It is for the nine writers and the implementers of PRP-100 to PRP-109 and PRP-110 to PRP-136, who are written against the names in "Interfaces provided" now. Opus with a required review (PRP-37 and PRP-70 precedent): a wrong name here is refactored in a dozen PRPs, and a loose shape here could open a content or secret path that six existing guards keep closed.

Out of scope: every store, container, route, worker, detector, encryption helper, UI and permission implementation (PRP-101 detectors, PRP-102 crypto and containers, PRP-103 capture edge, PRP-104 explorer and the role's permissions, PRP-105 policy engine and `govpolicy.*` permissions, PRP-107 notifications, PRP-108 platform-control actions and approval flow, PRP-109 trail); identity, labels, estate, risk, safety-evaluation and incident contracts (PRP-110); telemetry tool and service identity (folded into PRP-70 as F1); the `eu_ai_act` and `iso_42001` framework ids (PRP-70 F2).

## Why
- The owner asked on 2026-11-16 for "the ultimate team AI governance and auditing tool" and directed that every identified gap be planned (`temp/audit/governance-core-design.md` section 0). Every governance-core PRP needs shared wire names first; contracts have one owner per wave and W20's is this PRP (design section 3).
- Metadata-only by construction: `telemetry/v1/telemetry-event.schema.json` says "Prompt and response bodies are never carried here; see payload_ref" (`:5`), and `$defs/payload_ref` (`:287-312`) is only `{pointer, classification, redaction_state}`. The edge drops body keys (`services/api/neurosphere_api/ingest/service.py:124`, `drop_body_fields`), the worker quarantines survivors as `BODY_FIELD_PRESENT` (`services/workers/neurosphere_workers/ingestion/pipeline.py:145`), the archive re-checks (`services/workers/neurosphere_workers/archive/serialize.py:59-63`) and audit seals reject body and credential keys (`packages/core/neurosphere_core/audit/content_guard.py:20-45`). Interaction audit therefore needs a separate, opt-in channel whose contracts cannot carry content into any of those paths (design 2.1; GD-14 reverses the 2026-11-06 "keep metadata-only" decision, `docs/validation/PRODUCT-VALIDATION-2026-11-06.md:72`, for opt-in capture only).
- No policy contract can be evaluated: `catalog/v1/policy.schema.json` has `policy_kind`, `policy_version` and `enforcement`, and no Python outside the contracts reads them (design G-b). `docs/PRD.md:23` (NS-04) promises "policy exceptions" routed to scoped reviewers; HITL has the `policy_exception` kind (`packages/core/neurosphere_core/hitl/models.py:43`) and nothing opens one.
- No notification reaches a person: NS-04 promises "SLA timers, reassignment, notifications" (`docs/PRD.md:23`), and `hitl/notify.py:133-137` holds only `EmailNotifierStub` and `TeamsNotifierStub`.
- No approval state on agents: `catalog/v1/common.schema.json` `lifecycle_status` is `draft|active|deprecated|retired`; `AgentVersion` has no approval field (`catalog/v1/agent_version.schema.json:7-110`), so "the fix goes through approval" (design 2.4) has nothing to record.
- Closed enums block later PRPs: `connector_kind` is four values (`admin/v1/connector-config.schema.json:25`), `setting_key` six (`admin/v1/system-setting.schema.json:12-15`), manifest write actions fourteen (`connectors/v1/connector-manifest.schema.json:201-216`), roles five (`admin/v1/common.schema.json:97-101`).

## Acceptance criteria
- [ ] Every schema and `$defs` entry in "Interfaces provided" exists with the exact name and title, generates Python and TypeScript bindings, and has at least one valid and one invalid example in its area's manifest; `python packages/contracts/scripts/generate.py --check` passes.
- [ ] Additive only: `tests/contracts/test_additive_only.py` passes with an EMPTY `ALLOWED_TIGHTENINGS`; every existing example still validates; a `TelemetryEvent` written before this PRP validates unchanged; the baseline snapshot is refreshed only in the close-out commit.
- [ ] Guards not loosened by the schema change alone: `telemetry-event` keeps `additionalProperties: false` at every level and gains no property except inside `payload_ref`; no property name in `telemetry/v1`, `interactions/v1`, `policy/v1`, `notifications/v1`, `audit/v1` or the new `admin/v1` members satisfies `neurosphere_core.payload.is_body_field` or is in `content_guard.FORBIDDEN_KEYS`; no object in those areas declares both `key` and `value` (the OTLP attribute shape the guard drops whole); the six existing guard suites in "Validation gates" pass with no edit to them.
- [ ] Content is containable: only `ContentEnvelope` and `RedactedContent` declare a `text` property or any string longer than 1024 characters; no schema `$ref`s either of them (so content cannot be embedded in an event, audit record, interaction record, violation, notification, export manifest or setting); `InteractionRecord` has no content-bearing property at all.
- [ ] Secrets cannot be represented in what is stored: `RedactedContent.redaction_state` admits only `redacted` and `not_required`; every `text` is rejected by JSON Schema when it contains a private-key block, a JWT, a bearer credential, an AWS access key id, a GitHub token, an `sk-` key, an Azure storage or Service Bus key assignment, a SAS signature or a URL with userinfo (test strings assembled at runtime, never committed); a `DetectionFinding` whose category is a `CredentialCategory` with `action: kept` is rejected; a `CapturePolicy` whose `kept_categories` contains a credential category is rejected.
- [ ] No credential names: the PRP-37 walker (`tests/contracts/test_admin_no_credential_values.py`) passes on the extended `admin/v1` with no new `ALLOWED` entry, and the same walker run over `interactions/v1`, `policy/v1` and `notifications/v1` finds nothing; every credential is a `CredentialReference`; `kek_uri` accepts a Key Vault key identifier only and its host must match the document's cloud.
- [ ] `PolicyDefinition` accepts one rule of each of the nine kinds with its parameter object and rejects a rule whose `params` belong to another kind, an unknown key in `params`, more than 32 rules, and any string field that could hold an expression (there is none: the test walks the schema for `pattern`-free strings above 128 characters outside `display_name`).
- [ ] `PolicyDecisionRequest` rejects `domain_id`, `customer_id`, prompt or content keys and a request naming no subject; `PolicyDecisionResponse.cache_ttl_seconds` is 0 to 3600; `PolicyException` requires `expires_at`.
- [ ] `NotificationDelivery` has no recipient address field and no body: `title` is at most 160 characters, `link` is an application-relative path; `NotificationChannel` stores its endpoint only as a `CredentialReference` of kind `key_vault_secret` (or, with `local_sink: true`, a plain-HTTP loopback or compose-service `local_sink_url` with no query or userinfo) and its `allowed_host` as a bare hostname; `local_sink: true` without `local_sink_url`, or `local_sink_url` without `local_sink`, is rejected.
- [ ] `AgentVersion` with `approval: {state: approved, ...}` validates; an unknown state is rejected; a document without `approval` validates unchanged; `StructuredQuery` accepts `approval_state` on `agent_version` and `FIELD_APPLICABILITY` rejects it on other entities.
- [ ] `connectors/sdk-python/tests/test_connector_manifest_builder.py::test_write_action_literal_matches_the_contract_enum` passes with the six new kinds in the SDK `WriteAction` literal.
- PRP exit: touched suites, `generate.py --check`, ruff, pyright, contracts TS tests, frontend typecheck and `validate_planning.py` pass; PR open with CI green including `contracts`; Tier-3 files regenerated at merge.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| 1 | Where content travels | field on `telemetry-event`; separate channel | Separate: a transient `ContentEnvelope` accepted only at the edge, never persisted or published; events carry only `payload_ref` metadata (design 2.1) |
| 2 | How "secrets cannot be stored" is expressed | detector only; detector plus contract | Both: PRP-101 redacts; the stored form `RedactedContent` additionally rejects known credential formats by JSON Schema `not` patterns, and credential findings must be `replaced` |
| 3 | Where capture policies, channels, subscriptions and bindings are stored | new containers; `admin_config` kinds | Decided by the owner 2026-11-22 (plan approval): channels, subscriptions and enforcement bindings are `admin_config` documents (PRP-65 store: versioned, etag, retire, audited) with three new `admin_kind` values, as PRP-107 plans; capture policies are NOT an `admin_kind`: they live in PRP-102's own container `interaction_capture_policies` (PRP-102 clarification 5), so `CapturePolicy` carries its own `version`, PRP-103 builds `CapturePolicyStore` over that container and does not edit `admin/models.py`, and PRP-108 changes them only through PRP-103's functions |
| 4 | Policy rule language | expressions; closed typed kinds | Closed typed kinds with parameter objects, no expression or code field (design 2.3; `CLAUDE.md` no generated code) |
| 5 | New values on closed enums | `v2`; additive with open-ended wording | Additive (PRP-70 clarification 9 precedent): `admin_kind`, `role`, `connector_kind`, `setting_key`, `approver_permission`, manifest `actions` descriptions now say "open-ended: readers must tolerate unknown values" |
| 6 | Catalog `Policy` link to definitions | new field; projection by id | No catalog change: PRP-105 projects to `...:neurosphere:policy:<policy_id>` and maps mode `enforce`/`audit`/`off` to `enforced`/`advisory`/`disabled` |
| 7 | Access purpose on content reads | free text; code | Decided by the owner 2026-11-22 (plan approval): `InteractionAccessPurpose` code plus optional case reference (audit `content_guard` forbids prose); added beyond the design list because PRP-104 needs one shape for reads and exports |
| 8 | Capture default and who approves a `capture_policy_change` | (a) a second steward approves; (b) the maker-checker approver rule is relaxed for the governance action kinds so an admin approves | Decided by the owner 2026-11-16 (GD-1): capture is off everywhere and turned on per domain and source only by an approved `capture_policy_change`, proposed by a domain steward and never self-approved. Core requires a maker-checker approver to hold `action.approve` (`packages/core/neurosphere_core/admin/platform/review_policy.py:88-93`), which admin does not hold; decided: a second steward approves; no change to who holds `action.approve`. Admins do not approve these. Here: `CapturePolicy.state` starts `proposed`; `approver_permission` gains `config.manage` and `govpolicy.manage` (additive only, unused because option (b) was not chosen; see GD-20) |
| 9 | Who may read content | as design | Decided by the owner 2026-11-16 (GD-2): new privileged, time-bound role `interaction_investigator`; admin does not hold `interaction.read`; purpose required on every read. Here: role added to the contract role enums with the privileged `expires_at` rule; permissions are core names owned by PRP-104 |
| 10 | Content to the copilot or MCP | as design | Decided by the owner 2026-11-16 (GD-3): captured content is not shown to the copilot or MCP; tools see metadata and findings only; revisit after the north star. Here: no copilot or MCP contract references `ContentEnvelope` or `RedactedContent` (criterion 4) |
| 11 | What is never stored | as design | Decided by the owner 2026-11-16 (GD-4): credentials and secrets always redacted; payment card numbers redacted by default; other detected types redacted or kept per capture policy, default redact. Here: `redaction_mode` default `redact_all_detections`; credential categories can never be kept |
| 12 | Content retention | as design | Decided by the owner 2026-11-16 (GD-5): captured content is kept 90 days by default (the owner chose 90 over the recommended 30), no minimum, each deployment can set its own value, legal hold overrides; retaining bodies must be set explicitly in the retention policy. Here: `CapturePolicy.retention_days` default 90, bounds 1 to 365 |
| 13 | Detector set at launch | as design | Decided by the owner 2026-11-16 (GD-6): deterministic detector set (design section 2.2) plus customer dictionaries; no model detector. Here: no model-detector field; `detector_set_version` names the deterministic set |
| 14 | Enforcement default | as design | Decided by the owner 2026-11-16 (GD-7): `audit` for every policy and point; `enforce` only by an approved action, per point. Here: `EnforcementMode` default `audit` everywhere |
| 15 | SDK guard failure mode | as design | Decided by the owner 2026-11-16 (GD-8): the SDK guard fails open with a counter and an alert. Here: `EnforcementSetting.sdk_failure_mode` default `fail_open` |
| 16 | Notification channels first | as design | Decided by the owner 2026-11-16 (GD-10): generic webhook and Teams webhook first; email after the transport is verified. Here: `email` is a declared channel kind; PRP-107 may ship it `not_built` |
| 17 | Reverse the metadata-only decision | approved in principle 2026-11-16 | Decided by the owner 2026-11-16 (GD-14): the 2026-11-06 metadata-only decision is reversed for opt-in capture only; capture stays OFF by default and "bodies disabled by default" stays true; the orchestrator records it in the decision log |
| 18 | Decisions raised while planning PRP-100 to PRP-137 | ask in each PRP; one list | One list, decided 2026-11-16: "Owner decisions for the governance core" at the end of this file numbers them GD-16 onward; other PRPs cite the number |

## Context manifest

### Files to read first
- `PRPs/backlog/PRP-70-contracts-revision-restored-scope.md` - the names this PRP builds on (`sensitivity_category`, `environment`, `tags`) and its F1/F2 folds; its conventions are binding here.
- `docs/adr/0004-contract-versioning.md` - additive-only rules and the PRP-37 amendment (`ALLOWED_TIGHTENINGS`, baseline refresh).
- `temp/audit/governance-core-design.md` sections 2.1, 2.3, 2.4 and 3.2 - the design these contracts encode.
- `packages/contracts/schemas/telemetry/v1/telemetry-event.schema.json:5,154-158,287-312` - envelope and `payload_ref`.
- `packages/contracts/schemas/admin/v1/system-setting.schema.json` and `admin-config-document.schema.json` - member-per-key and body-per-kind `allOf` pins to extend.
- `packages/contracts/schemas/admin/v1/common.schema.json` - `role`, `admin_kind`, `principal_id`, `reason_code`, `https_url`, `slug`.
- `packages/contracts/schemas/scope/v1/identity-scope.schema.json:102-130` - `role_assignment` and its privileged rule.
- `packages/contracts/schemas/connectors/v1/connector-manifest.schema.json:189-223` and `connectors/sdk-python/neurosphere_connector/manifest.py:41-56` - action enum and its SDK mirror.
- `packages/core/neurosphere_core/payload/guard.py:21-55` and `packages/core/neurosphere_core/audit/content_guard.py:20-45` - the names the new schemas must never use.
- `tests/contracts/test_admin_no_credential_values.py`, `tests/contracts/contract_support.py:37-41`, `packages/contracts/scripts/test_generate.py:45-61`.

### Interfaces consumed
- PRP-70 (W19, must be merged first): `catalog/v1/common.schema.json` `$defs` `sensitivity_category`, `environment`, `tags`; the `map` area in `test_generate.py`; F1 telemetry `tool`/`service`/`mcp_server_ref` (this PRP bumps `schema_version` again after it).
- Shipped: PRP-01 conventions; PRP-37 `admin/v1` and the additive-only test; PRP-65 `admin_config` store and `ADMIN_KIND_MODELS`; `actions/v1/target-ref.schema.json`.

### Interfaces provided
Generated names follow ADR-0004: Python `neurosphere_contracts.<area>.v1.<file_with_underscores>`, TypeScript `packages/contracts/ts/src/<area>/v1/<file>.ts`, exported by title. Kebab-case files; fragments have no `schema_version` (the `actions/v1/target-ref` precedent). Shared `$ref` targets: catalog `common.schema.json` (`canonical_id`, `cloud`, `customer_id`, `domain_id`, `timestamp`, `person_id`, `token`), admin `common.schema.json` (`principal_id`, `reason_code`, `record_id`, `slug`, `display_name`, `https_url`), audit `$defs/uuid` (lowercase UUID). Every object `additionalProperties: false`.

Telemetry (`telemetry/v1/`):
- `telemetry-event.schema.json` `$defs/payload_ref` (`PayloadRef`) gains optional: `interaction_id` (UUID or null), `capture_policy_id` (slug or null), `capture_policy_version` (int >= 1 or null), `detector_set_version` (`^[a-z0-9][a-z0-9._-]{0,63}$` or null), `detected_categories` (unique `DetectedCategory` list, max 32, default []), `content_parts` (max 5 of `{part: ContentPartKind, char_count: int >= 0, truncated: bool}`, default []). `redaction_state` unchanged. No top-level property added.
- `content-envelope.schema.json` -> `ContentEnvelope` (transient opt-in push; never stored, published, logged or returned) {`schema_version`, `cloud`, `source_id`, `event_id` (pair joins it to its `TelemetryEvent`), `trace_id`, `span_id` (or null), `occurred_at`, `parts` (1-5 of `$defs/content_part` `ContentPart` {`part`, `text` (1-32768 chars, no control characters except tab, CR, LF), `truncated` (default false)})}. Python validator `check_content_envelope_parts`: one part per kind.

Interactions (new area `interactions/v1/`):
- `detection-finding.schema.json` (fragment) -> `DetectionFinding` {`category`, `part`, `detector_id` (slug), `detector_version` (`^[0-9]+\.[0-9]+\.[0-9]+$`), `count` (1-100000), `action` (`replaced`|`kept`), `confidence` (`high`|`medium`|`low`), `spans` (max 64 of {`start`, `end`} offsets into the redacted text, default [])}; `$defs/detected_category` -> `DetectedCategory` (open-ended): `private_key`, `jwt`, `bearer_token`, `cloud_access_key`, `vendor_api_key`, `connection_string`, `url_with_credentials`, `password_assignment`, `payment_card`, `iban`, `us_ssn`, `email_address`, `phone_number`, `ip_address`, `mac_address`, `guid`, `customer_dictionary_term`, `customer_identifier_pattern`, `other`; `$defs/credential_category` -> `CredentialCategory` (the first eight, closed); `$defs/part_kind` -> `ContentPartKind`: `prompt`, `response`, `tool_input`, `tool_output`, `system_instructions`. Rule: a credential category requires `action: replaced`.
- `redacted-content.schema.json` -> `RedactedContent` (the plaintext that PRP-102 encrypts; exists only in memory between redaction and encryption and after an audited decrypt) {`schema_version`, `interaction_id`, `redaction_state` (`redacted`|`not_required`), `detector_set_version`, `parts` (1-5 of `RedactedPart` {`part`, `text` (`$defs/secret_free_text`), `truncated`, `findings` (max 256 `DetectionFinding`)})}. Placeholder grammar written by redaction: `[[ns-redacted:<detected_category>]]`. `secret_free_text` = 0-32768 chars plus `not` patterns for the formats in criterion 5; mirrored by `tests/contracts/validators.py::check_secret_free_text`, which PRP-101 must keep a subset of its credential detectors.
- `interaction-record.schema.json` -> `InteractionRecord` (index document, metadata only; container `interaction_index`, declared by PRP-102) {`schema_version`, `interaction_id`, `cloud`, `customer_id`, `domain_id`, `source_id`, `event_id`, `trace_id`, `span_id`, `correlation_id`, `capture_source` (`edge_push`|`otlp_attributes`|`gateway_log`|`connector`, open-ended), `occurred_at`, `captured_at`, `agent_id`, `agent_version_id`, `tool_id`, `service_id`, `mcp_server_id` (canonical ids or null), `model` ({`provider`, `model_name`, `model_version`, `deployment_id`} or null), `principal_id` (pseudonym or null), `capture_policy_id`, `capture_policy_version`, `detector_set_version`, `redaction_state` (`redacted`|`not_required`|`redaction_failed`), `parts` (as `content_parts`), `content_ref` ({`pointer` (opaque, max 1024), `kek_uri`, `algorithm` const `aes_256_gcm`, `ciphertext_sha256`, `byte_length`} or null; null when nothing was stored), `findings_summary` (max 64 of {`category`, `count`, `action`}), `sensitivity_categories` (PRP-70 list), `data_asset_ids` (max 50), `retention_class` (slug, default `interaction_default`), `expires_at`, `legal_hold_ids` (max 16 record ids, default [])}. No hash of plaintext; the wrapped data key lives in the blob header (ASSUMPTION; PRP-102 decides).
- `capture-policy.schema.json` -> `CapturePolicy` (container `interaction_capture_policies`, declared by PRP-102) {`schema_version`, `capture_policy_id`, `version` (int >= 1), `previous_version` (int or null), `display_name`, `cloud`, `customer_id`, `domain_id`, `source_ids` (1-64 tokens), `parts` (1-5 `ContentPartKind`), `detector_set_version`, `customer_dictionary_ids` (max 16 slugs, default []), `redaction_mode` (`redact_all_detections`|`redact_listed`, default the first), `kept_categories` (`DetectedCategory` list, never a credential category, default []), `sampling` ({`rate` (0 exclusive to 1), `max_per_minute` (1-6000)}), `max_part_chars` (1-32768, default 8192), `retention_class`, `retention_days` (1-365, default 90), `state` (`proposed`|`active`|`suspended`|`retired`), `approved_intent_id`, `approved_audit_id` (UUIDs, required when `active`), `effective_from` (or null)}.
- `interaction-access-purpose.schema.json` (fragment) -> `InteractionAccessPurpose` {`purpose_code` (`incident_investigation`|`policy_violation_review`|`legal_hold_review`|`data_subject_request`|`security_review`|`quality_review`, open-ended), `case_ref` (record id or null)}.
- `interaction-export-manifest.schema.json` -> `InteractionExportManifest` {`schema_version`, `export_id`, `cloud`, `customer_id`, `domain_ids` (1-64), `requested_by` (principal id), `requested_at`, `purpose` (`InteractionAccessPurpose`), `filters` ({`from`, `to`, `agent_ids`, `detected_categories`}), `interaction_count`, `interaction_ids` (max 1000), `excluded_count`, `includes_held_content`, `bundle` ({`pointer`, `kek_uri`, `algorithm`, `ciphertext_sha256`, `byte_length`}), `audit_id`, `expires_at`}.

Policy (new area `policy/v1/`):
- `policy-definition.schema.json` -> `PolicyDefinition` {`schema_version`, `policy_id` (slug), `policy_version` (int >= 1), `previous_version` (int or null), `cloud`, `customer_id`, `domain_id`, `display_name`, `document_url` (`https_url` or null), `status` (`draft`|`published`|`retired`), `mode` (`EnforcementMode`), `severity` (`PolicySeverity`), `rules` (1-32 `PolicyRule`), `content_sha256`, `created_by`, `created_at`, `published_at`, `published_intent_id`, `published_audit_id` (or null)}. `$defs`: `enforcement_mode` -> `EnforcementMode` (`off`|`audit`|`enforce`, default `audit`); `severity` -> `PolicySeverity` (`low`|`medium`|`high`|`critical`); `rule_kind` -> `PolicyRuleKind` (open-ended; PRP-110 adds `identity_entitlement`): `model_allow_list`, `data_sensitivity_access`, `residency`, `budget`, `required_owner`, `required_attestation`, `required_approval`, `content_rule`, `registration_required`; `applies_to` -> `PolicyAppliesTo` {`entity_types` (max 8), `tags` (max 16), `environments` (max 6), `entity_ids` (max 64); all default [] = every entity in the domain}; `rule` -> `PolicyRule` {`rule_id` (slug), `kind`, `severity` (or null), `applies_to`, `params`} with `params` pinned by `kind` (anyOf plus `allOf` if/then, the AdminConfigDocument pattern). Params: `ModelAllowListParams` {`allowed_models` (max 64 of {`model_name`, `model_version` or null}), `allowed_deployment_ids` (max 64)}; `DataSensitivityAccessParams` {`sensitivity_categories` (1-10), `access` (`read`|`write`|`read_or_write`), `allowed_when` (`agent_version_approved`|`exception_only`)}; `ResidencyParams` {`allowed_geographies`, `allowed_regions` (tokens, max 64)}; `BudgetRuleParams` {`budget_record_id`, `threshold_percent` (1-1000), `on_breach` (`alert`|`propose_cap_change`)}; `RequiredOwnerParams` {`min_owners` (1-5), `require_active_owner` (default true)}; `RequiredAttestationParams` {`attestation_kind` (`owner_recertification`|`agent_attestation`), `max_age_days` (1-730)}; `RequiredApprovalParams` {`entity_types` (`agent_version`, open-ended), `block_activation` (default true)}; `ContentRuleParams` {`detected_categories` (1-16), `min_count` (default 1), `parts` (default []), `window_minutes` (1-10080, default 60)}; `RegistrationRequiredParams` {`entity_types` (subset of `agent`, `tool`, `model_deployment`, `mcp_server`, `service`), `grace_period_hours` (0-720, default 24)}.
- `policy-violation.schema.json` -> `PolicyViolation` (container `policy_violations`) {`schema_version`, `violation_id`, `cloud`, `customer_id`, `domain_id`, `policy_id`, `policy_version`, `rule_id`, `rule_kind`, `severity`, `subject` (`TargetRef`), `status` (`open`|`excepted`|`resolved`|`superseded`), `dedup_key` (`^sha256:[a-f0-9]{64}$`), `first_seen_at`, `last_seen_at`, `occurrence_count`, `evidence` (1-50 `PolicyViolationEvidence` {`evidence_kind` (`catalog_entity`|`relation`|`interaction_record`|`aggregate_window`|`audit_record`|`telemetry_event`|`budget_status`, open-ended), `ref` (1-512), `observed_at`}), `exception_id` (or null), `resolution` ({`resolved_at`, `reason_code`, `intent_id`, `audit_id`} or null), `correlation_id`, `evaluator_version`}.
- `policy-exception.schema.json` -> `PolicyException` (container `policy_exceptions`) {`schema_version`, `exception_id`, `cloud`, `customer_id`, `domain_id`, `policy_id`, `rule_id`, `subject`, `violation_id` (or null), `status` (`requested`|`approved`|`rejected`|`expired`|`revoked`), `reason_code`, `requested_by`, `requested_at`, `review_item_id` (HITL item id or null), `decided_by`, `decided_at`, `expires_at` (required; validator `check_policy_exception_window`: at most 365 days after `requested_at`), `audit_id`}.
- `policy-decision-request.schema.json` -> `PolicyDecisionRequest` {`schema_version`, `decision_point` (`EnforcementPoint`), `operation` (`model_call`|`tool_invoke`|`mcp_call`|`data_access`|`register`), `agent_id`, `agent_version_id`, `tool_id`, `mcp_server_id` (or null), `model` ({`model_name`, `model_version`, `deployment_id`} or null), `data_asset_ids` (max 20), `access` (`read`|`write`|null), `environment` (or null), `request_ref` (`^[A-Za-z0-9._-]{1,128}$` or null)}. No scope-shaped field; at least one subject (validator `check_decision_request_subject`).
- `policy-decision-response.schema.json` -> `PolicyDecisionResponse` {`schema_version`, `decision_id`, `decided_at`, `effect` (`allow`|`deny`|`audit`), `mode`, `matches` (max 20 `PolicyDecisionMatch` {`policy_id`, `policy_version`, `rule_id`, `rule_kind`, `effect`}), `reason_codes` (max 8), `cache_ttl_seconds` (0-3600), `policy_set_digest` (sha256), `degraded` (bool)}.
- `enforcement-binding.schema.json` -> `EnforcementBinding` (body of `admin_kind: enforcement_binding`) {`schema_version`, `binding_id`, `cloud`, `customer_id`, `domain_id`, `policy_id`, `point`, `target` (`TargetRef` or null = every target of that point in the domain), `mode` (default `audit`), `state` (`pending`|`applied`|`failed`|`drifted`|`not_supported`), `last_intent_id`, `last_audit_id`, `last_verified_at` (or null)}; `$defs/enforcement_point` -> `EnforcementPoint`: `gateway`, `tool_call`, `mcp_server`, `mcp_client`, `sdk`, `budget`, `registration`.

Notifications (new area `notifications/v1/`):
- `notification-channel.schema.json` -> `NotificationChannel` (body of `admin_kind: notification_channel`) {`schema_version`, `channel_id`, `cloud`, `customer_id`, `domain_id`, `display_name`, `kind` (`webhook`|`teams_webhook`|`email`, open-ended), `allowed_host` (lowercase hostname, max 253), `endpoint_credential` (`CredentialReference`, `key_vault_secret` only: the secret holds the URL or transport settings; null only with `local_sink`), `hmac_credential` (`CredentialReference` or null; required for `webhook` unless `local_sink`), `local_sink` (bool, default false; PRP-107 clarification 7: core refuses it unless `NS_ENV=local`), `local_sink_url` (`^http://(127\.0\.0\.1|localhost|[a-z][a-z0-9-]{0,62})(:[0-9]{1,5})?(/[A-Za-z0-9._~%-]{1,128})*/?$`, required when and only when `local_sink`), `enabled`}.
- `notification-subscription.schema.json` -> `NotificationSubscription` (body of `admin_kind: notification_subscription`) {`schema_version`, `subscription_id`, `cloud`, `customer_id`, `domain_id`, `channel_id`, `event_classes` (1-16 `NotificationEventClass`), `audience_roles` (1-6 roles), `min_severity` (default `medium`), `enabled`}; `$defs/event_class` -> `NotificationEventClass` (open-ended): `policy_violation_opened`, `policy_violation_escalated`, `policy_violation_resolved`, `policy_exception_requested`, `policy_exception_decided`, `hitl_item_assigned`, `hitl_item_escalated`, `hitl_item_expiring`, `approval_requested`, `approval_decided`, `action_executed`, `action_failed`, `capture_policy_changed`, `enforcement_mode_changed`, `budget_threshold_crossed`, `channel_delivery_failed`.
- `notification.schema.json` -> `NotificationDelivery` (container `notification_outbox`) {`schema_version`, `notification_id`, `cloud`, `customer_id`, `domain_id`, `channel_id`, `subscription_id`, `event_class`, `severity`, `subject` (`TargetRef`), `title` (1-160, no control characters), `link` (`^/[A-Za-z0-9/_.=?&%:-]{0,511}$`), `correlation_id`, `dedup_key`, `status` (`pending`|`sending`|`delivered`|`failed`|`dead_lettered`|`suppressed`), `attempts` (0-20), `next_attempt_at`, `last_error_code` (reason code or null), `created_at`, `delivered_at`, `source_audit_id`}. Recipients resolve inside the sender and are never stored.

Catalog, query, connectors, admin, scope:
- `catalog/v1/common.schema.json` `$defs/agent_version_approval` -> `AgentVersionApproval` {`state` (`$defs/approval_state` -> `AgentVersionApprovalState`: `not_required`, `pending`, `approved`, `rejected`, `suspended`), `requested_at`, `decided_at`, `decided_by` (`person_id`), `intent_id`, `audit_id`, `policy_id`, `policy_version`, `reason_code` (all nullable)}; `AgentVersion.approval` optional, default null (null = no approval recorded). `query/v1` `keyword_field` adds `approval_state` (agent_version only).
- `connectors/v1/connector-manifest.schema.json` `write_support.actions` adds `agent_version_approve`, `agent_version_suspend`, `capture_policy_change`, `governance_policy_publish`, `enforcement_mode_change`, `gateway_policy_apply`; the SDK `WriteAction` literal mirrors them.
- `admin/v1`: `connector_kind` adds `generic`, `entra_identity`, `purview`, `unity_catalog`, `m365_copilot`, `github_copilot`, `cursor`, `openai_enterprise`, `anthropic_claude`, `entra_shadow_ai`, `github_issues`; `admin_kind` adds `notification_channel`, `notification_subscription`, `enforcement_binding` (body pins appended to `admin-config-document`); `role` adds `interaction_investigator` (privileged: `expires_at` required, appended `allOf` in `role-assignment-change`, `principal-access-summary` and `scope/v1/identity-scope`); `review-policy-document` `approver_permission` adds `config.manage`, `govpolicy.manage`; `system-setting` `setting_key` adds `interaction_capture`, `notifications`, `enforcement` with members `InteractionCaptureSetting` {`kek_provider` (`key_vault_key`|`local_development`), `kek_uri` (`https://<vault>.vault.azure.net|usgovcloudapi.net/keys/<name>[/<32 hex>]` or null for `local_development`), `content_storage_account_resource_id`, `content_container` (`^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$`), `credential` (`CredentialReference`), `max_content_chars_per_interaction` (1-163840, default 65536), `shed_capture_at_queue_percent` (1-100, default 80)}, `NotificationsSetting` {`egress_allowed_hosts` (1-32 hostnames), `max_attempts` (1-20, default 8), `retry_base_seconds` (1-3600, default 30), `dedup_window_seconds` (0-86400, default 900)}, `EnforcementSetting` {`decision_cache_ttl_seconds` (0-3600, default 60), `sdk_failure_mode` (`fail_open`|`fail_closed`, default `fail_open`), `decide_rate_limit_per_minute` (1-60000, default 600)}. Validator `check_kek_uri_cloud` (vault suffix matches cloud).

Conventions fixed here for later PRPs (not contract enums): platform-control target ids `<cloud>:<customer>:neurosphere:<entity_type>:<id>` with `TargetRef.entity_type` `capture_policy`, `governance_policy`, `enforcement_binding` (agent versions use their catalog id); core permission names `interaction.read`, `interaction.export` (PRP-104) and `govpolicy.read`, `govpolicy.manage` (PRP-105; `policy.manage` already means identity policy); audit `operation` names `interaction.capture`, `interaction.capture_dropped`, `interaction.read`, `interaction.export`, `govpolicy.publish`, `govpolicy.violation_open`, `govpolicy.violation_resolve`, `govpolicy.exception_decide`, `govpolicy.decide`, `notification.delivery` (PRP-107's name), all carrying the triggering `correlation_id` so PRP-109 can assemble one trail; containers `interaction_index`, `interaction_capture_policies`, `policy_definitions`, `policy_violations`, `policy_exceptions`, `notification_outbox` (declared by PRP-102).

### Patterns to match
- Additive revision with tests: `tests/contracts/test_catalog_query_revisions.py`; PRP-70 items 1-4.
- Body or member pinned by kind: `admin/v1/admin-config-document.schema.json` `allOf`; `admin/v1/system-setting.schema.json:23-75`.
- Fragment schema: `actions/v1/target-ref.schema.json`; examples manifest with `derived_from`/`expected_error`: `recommendations/v1/examples/manifest.json`.
- Field walker: `tests/contracts/test_admin_no_credential_values.py`; cross-area relative `$ref`: `audit/v1/audit-record.schema.json` to `../../actions/v1/target-ref.schema.json`.

### Gotchas
- `connectors/sdk-python/tests/test_connector_manifest_builder.py:84-90` pins the SDK `WriteAction` literal to the contract enum; the literal changes in the same item or that suite fails.
- `packages/core/tests/auth/scope/test_roles.py:76-81` asserts the core `Role` set equals the contract role enum and has five members: item 5 adds `Role.INTERACTION_INVESTIGATOR` with an EMPTY permission set and puts it in `PRIVILEGED_ROLES` (it grants nothing until PRP-104 assigns `interaction.read`/`interaction.export`), and updates that test's expectations. This is the only core edit.
- The PRP-37 walker forbids property segments `key`, `token`, `secret` in `admin/v1`: hence `kek_uri`, `kek_provider`, `hmac_credential`, `endpoint_credential`. Do not add `ALLOWED` entries.
- Secret-shaped test strings must be built at runtime (concatenation); a committed fake JWT or `AKIA` string trips gitleaks in CI (`.gitleaksignore` is not the answer).
- `packages/contracts/scripts/test_generate.py` `EXPECTED_AREAS` and the ADR area list need `interactions`, `policy`, `notifications`; `contract_support.LIBRARY_SCHEMAS` is unchanged because no new library schema is added.
- Pydantic ignores `if/then/not` (ADR-0004): the credential-category rule, `secret_free_text` patterns and kind pins are JSON Schema tests; PRP-101/102 must validate `RedactedContent` against the JSON Schema before encryption.
- Core refuses unknown `admin_kind`, `setting_key` and `connector_kind` values until the consuming PRP registers them (`packages/core/neurosphere_core/admin/models.py:95,173-175`, `admin/connectors/service.py:53-57`, `workers/connector_config/validators.py:88-93`): fail closed, by design. PRP-105 (W21, the first writer of bindings) registers the `enforcement_binding` kind in `ADMIN_KIND_MODELS` and PRP-107 (W22) the two notification kinds; no two PRPs of one wave edit `admin/models.py`. Capture policies are not an admin kind: they live in PRP-102's container `interaction_capture_policies` (clarification 3).
- Avoid title collisions in `ts/src/index.ts`: `Policy` and `ApprovalDecision` exist, hence `PolicyDefinition`, `AgentVersionApproval`, `NotificationDelivery` (also avoids the DOM `Notification` type).
Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - packages/contracts/**
  - tests/contracts/**
  - docs/adr/0004-contract-versioning.md
  - connectors/sdk-python/neurosphere_connector/manifest.py
  - packages/core/tests/auth/scope/test_roles.py
tier1:
  - packages/contracts/schemas/**
tier2_appends:
  - packages/core/neurosphere_core/auth/scope/permissions.py
must_not_touch:
  - services/**
  - packages/core/neurosphere_core/payload/**
  - packages/core/neurosphere_core/audit/**
  - packages/core/neurosphere_core/admin/**
  - packages/core/neurosphere_core/catalog/**
  - sandbox/**
  - infra/**
  - frontend/src/**
  - connectors/reference/**
  - connectors/sdk-ts/**
```

## Implementation blueprint

Parallelization: items 1 to 5 are serial (shared generated output and `ts/src/index.ts`); item 6 after 5; items 7 and 8 last.

### Item 1 - Content channel: `payload_ref`, `ContentEnvelope`, detection and redacted content
- Deliverable: `payload_ref` additions; `telemetry/v1/content-envelope.schema.json`; `interactions/v1/detection-finding.schema.json` and `redacted-content.schema.json` with examples (envelope with prompt and response; redacted content with a `[[ns-redacted:jwt]]` placeholder; invalid: envelope with an `authorization` key, a credential finding `kept`, `redaction_state: pending`); `check_content_envelope_parts`, `check_secret_free_text`; `interactions` in `EXPECTED_AREAS`; bindings.
- Owned files: `packages/contracts/schemas/telemetry/v1/**`, `packages/contracts/schemas/interactions/v1/**` (new), `packages/contracts/scripts/test_generate.py`, generated output, `tests/contracts/validators.py`, `tests/contracts/test_governance_a_content.py` (new).
- Must NOT touch: `packages/core/neurosphere_core/payload/**`.
- Depends on: PRP-70 merged.
- Acceptance criteria: criteria 4 and 5; old telemetry examples validate.
- Tests: `tests/contracts/test_governance_a_content.py`, `test_schemas.py`, `test_roundtrip.py`, `test_additive_only.py`.
- Pattern references: `telemetry/v1/examples/expectations.json`, `actions/v1/target-ref.schema.json`.

### Item 2 - Interactions area: record, capture policy, access purpose, export manifest
- Deliverable: the four schemas with examples (record with findings and `content_ref`; record with `redaction_failed` and null `content_ref`; active capture policy at version 2; invalid: record with a `prompt` property, capture policy keeping `jwt`, active policy without `approved_audit_id`).
- Owned files: `packages/contracts/schemas/interactions/v1/**`, generated output, `tests/contracts/test_governance_a_interactions.py` (new).
- Must NOT touch: `telemetry/v1/**` (item 1 done).
- Depends on: item 1.
- Acceptance criteria: criterion 4 for `InteractionRecord`; capture-policy rules in criterion 5.
- Tests: `tests/contracts/test_governance_a_interactions.py`.
- Pattern references: `admin/v1/examples/manifest.json`.

### Item 3 - Policy area
- Deliverable: the six `policy/v1` schemas with one valid rule per kind, violation with evidence, exception, decision request and response, binding; invalid: kind/params mismatch, 33 rules, request with `domain_id`, request with no subject, exception without `expires_at`; `check_policy_exception_window`, `check_decision_request_subject`; `policy` in `EXPECTED_AREAS`.
- Owned files: `packages/contracts/schemas/policy/v1/**` (new), generated output, `tests/contracts/test_governance_a_policy.py` (new).
- Depends on: item 2.
- Acceptance criteria: criteria 7 and 8.
- Tests: `tests/contracts/test_governance_a_policy.py`, `tests/contracts/test_validators.py`.
- Pattern references: `admin/v1/admin-config-document.schema.json` (kind pins), PRP-70 `AgentMatchRequest` (no scope-shaped field).

### Item 4 - Notifications area
- Deliverable: the three `notifications/v1` schemas with examples (webhook channel with HMAC reference, Teams channel, subscription by role, delivered record); invalid: channel with a URL property, delivery with a `recipient` field, title of 161 characters; `notifications` in `EXPECTED_AREAS`.
- Owned files: `packages/contracts/schemas/notifications/v1/**` (new), generated output, `tests/contracts/test_governance_a_notifications.py` (new).
- Depends on: item 3.
- Acceptance criteria: criterion 9.
- Tests: `tests/contracts/test_governance_a_notifications.py`.
- Pattern references: `admin/v1/credential-reference.schema.json`.

### Item 5 - Catalog approval, query field, manifest actions, admin and scope enums
- Deliverable: `AgentVersionApproval` and `AgentVersion.approval`; `approval_state` query field and `FIELD_APPLICABILITY` row; six manifest actions and the SDK literal; `connector_kind`, `admin_kind` with body pins, `role` with privileged rules, `approver_permission`, `setting_key` with three members and pins; `check_kek_uri_cloud`; open-ended wording on each enum touched; examples per change; the core `Role.INTERACTION_INVESTIGATOR` (empty permission set, privileged) and the six-role expectations in `test_roles.py`.
- Owned files: `packages/contracts/schemas/{catalog,query,connectors,admin,scope}/v1/**`, `connectors/sdk-python/neurosphere_connector/manifest.py`, `packages/core/neurosphere_core/auth/scope/permissions.py` (Tier-2 append: one enum member, one empty map entry, one `PRIVILEGED_ROLES` member), `packages/core/tests/auth/scope/test_roles.py`, generated output, `tests/contracts/validators.py`, `tests/contracts/test_governance_a_enums.py` (new).
- Must NOT touch: `catalog/v1/canonical_id.schema.json`, `id-corpus.json`, relation schemas.
- Depends on: item 4.
- Acceptance criteria: criteria 6 (admin part), 10, 11.
- Tests: `tests/contracts/test_governance_a_enums.py`, `test_admin_identity_schemas.py`, `test_admin_platform_schemas.py`, `test_admin_no_credential_values.py`, `test_connector_manifest.py`, `connectors/sdk-python/tests`.
- Pattern references: PRP-70 item 1; `tests/contracts/test_admin_identity_schemas.py`.

### Item 6 - Guard and secrecy suite
- Deliverable: `tests/contracts/test_governance_a_guards.py` (new): the property-name walk against `is_body_field` and `FORBIDDEN_KEYS`; no `key`+`value` objects; only the two content schemas carry `text` or long strings; neither is `$ref`'d; the credential walker over the three new areas; `telemetry-event` closed at every level.
- Owned files: `tests/contracts/test_governance_a_guards.py`.
- Depends on: item 5.
- Acceptance criteria: criteria 3, 4, 6.
- Tests: that file plus the six guard suites in the gates, unedited.
- Pattern references: `tests/contracts/test_admin_no_credential_values.py`.

### Item 7 - Consumer sweep
- Deliverable: run the gate suites; record every failure caused by the new optional fields. Allowed fixes are expectation updates in `tests/contracts/**`; anything else is reported with file and cause and not fixed here.
- Owned files: none new. Depends on: item 6.
- Acceptance criteria: gate suites pass, or each failure is reported.
- Tests: the `uv run pytest` line in "Validation gates".

### Item 8 - Integration and close-out
- Deliverable: ADR-0004 amendment (PRP-99: the areas, the open-ended enums, the secret-free stored-content rule, empty `ALLOWED_TIGHTENINGS`); baseline refresh after review; rebase; Tier-3 regeneration per reference section 6; changelog fragment `changelog.d/PRP-99-governance-contracts-a.md`; completion note repeating every provided name for PRP-100 to PRP-136 authors.
- Owned files: `docs/adr/0004-contract-versioning.md`, `tests/contracts/fixtures/v1-baseline/**`, this PRP file, Tier-3 files.
- Depends on: items 1-7.
- Acceptance criteria: validation gates pass; CI green including `contracts`.

## Cut line
If context runs low, item 4 (notifications) moves to a serial first item of PRP-107 (W22 has no other contracts owner); PRP-107 then also owns `notifications/v1/**`. Items 1-3, 5-8 still merge as a unit; the north-star chain is unaffected except that PRP-107 grows by one item. Criterion 9 is then recorded unmet here.

## Validation gates
```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
python packages/contracts/scripts/generate.py --check
uv run pytest -q tests/contracts packages/contracts/scripts connectors/sdk-python/tests packages/core/tests/payload packages/core/tests/audit packages/core/tests/admin packages/core/tests/admin_runtime packages/core/tests/auth packages/core/tests/hitl services/api/tests/ingest services/workers/tests/ingestion services/workers/tests/quarantine services/workers/tests/archive services/api/tests/test_openapi_drift.py
pnpm --filter ./packages/contracts/ts test
pnpm --filter ./packages/contracts/ts typecheck
pnpm --filter @neurosphere/frontend typecheck
python scripts/validate_planning.py
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```

## Migration and rollback
All changes are additive inside `v1`: new areas and files, new optional properties with defaults, new enum values on fields now documented open-ended, appended `allOf` members that constrain only the new values. No stored document changes and no container is created here. Nothing writes the new fields until PRP-101 to PRP-109 ship; core refuses the new kinds and keys until then (fail closed). Revert is `git revert` plus regeneration while no later PRP has persisted the new shapes; after that a `v2` is required (ADR-0004).

## Live and open gates
None. Contract work is provable offline.

## NOT building
Stores, containers, routes, workers, detectors, encryption, UI, permissions in core, the trail. No content field on `TelemetryEvent`, `InteractionRecord`, `AuditRecord`, notifications or violations. No expression language or user code in policies. No model-based detector field (GD-6). No claim of parity with Microsoft Purview or any product; no compliance claim in examples. No blocking inside third-party SaaS and no endpoint or browser DLP is implied by any contract (design section 8).

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [x] All clarification questions are decided, not guessed (rows 3 and 7 approved by the owner at plan approval 2026-11-22; the GD rows were decided 2026-11-16)

## Execution state
| Item | Status | Branch/worktree | Notes |
|---|---|---|---|
| 1 | merged | worktree-agent-a96adb3e589139b84 (sonnet) | 76e2976b merged c041412b; gen --check OK, 3614 passed (contracts+sdk+payload+audit+ingest+archive+quarantine), ruff/format/pyright clean, openapi drift 3 passed; deviation: PRP-70 test_payload_ref_untouched relaxed to pin original members (baseline-diff trap); 2026-11-23 |
| 2 | in-progress | worktree (implementer, sonnet) | dispatched 2026-11-23 |
| 3 | todo | | |
| 4 | todo | | |
| 5 | todo | | |
| 6 | todo | | |
| 7 | todo | | |
| 8 | todo | | |

## Owner decisions for the governance core (decided 2026-11-16)
Decided by the owner on 2026-11-16 (decision D19 in docs/DECISIONS-LOG.md): the recommended defaults were accepted, except GD-5, where the owner chose 90 days.

One list for PRP-99 to PRP-137. Each PRP that relies on a decision writes a Clarifications row whose decision cell starts with `Decided by the owner 2026-11-16 (GD-n): ...`, followed by "Here: ..." for what that PRP does about it; it cites the number and does not restate the question.

GD-1 to GD-15 are the design's decisions, all decided (`temp/audit/governance-core-design.md` section 7, there D-1 to D-15). Decisions:
- GD-1: capture is off everywhere and turned on per domain and source only by an approved `capture_policy_change`, proposed by a domain steward and never self-approved. Core requires a maker-checker approver to hold `action.approve` (`packages/core/neurosphere_core/admin/platform/review_policy.py:88-93`), which admin does not hold; DECIDED: a second steward approves (a different steward holding `action.approve` approves; self-approval is blocked; admins do not approve these); no change to who holds `action.approve`. Rejected: relaxing the approver rule so an admin approves. PRPs 99, 103, 108, 109, 111.
- GD-2 (decided): new privileged, time-bound role `interaction_investigator`; admin does not hold `interaction.read`; purpose required on every read. PRPs 99, 104.
- GD-3 (decided): captured content is not shown to the copilot or MCP; tools see metadata and findings only; revisit after the north star. PRPs 99, 103, 104, 109, 111, 116, 122 to 126.
- GD-4 (decided): credentials and secrets always redacted; payment card numbers redacted by default; other detected types redacted or kept per capture policy, default redact. PRPs 99, 101, 103, 111, 122 to 124.
- GD-5: DECIDED 90 days by default for captured content (the owner chose 90; the recommended default was 30), no minimum, each deployment can set its own value, legal hold overrides; retaining bodies must be set explicitly in the retention policy. PRPs 99, 102.
- GD-6 (decided): deterministic detector set (design section 2.2) plus customer dictionaries; no model detector. PRPs 99, 101.
- GD-7 (decided): `audit` for every policy and point; `enforce` only by an approved action, per point. PRPs 99, 105, 106, 108, 112 to 114, 116.
- GD-8 (decided): the SDK guard fails open with a counter and an alert. PRPs 99, 114.
- GD-9 (decided): estate connector order M365 Copilot and Copilot Studio, GitHub Copilot, ChatGPT Enterprise, Anthropic, Cursor; Entra shadow AI last. PRPs 110, 117, 122 to 126.
- GD-10 (decided): generic webhook and Teams webhook first; email after the transport is verified. PRPs 99, 107.
- GD-11 (decided): steward-curated value (locked) over customer label over NeuroSphere inference. PRPs 110, 120, 121.
- GD-12 (decided): keep the north star at W24; PRP-75 and PRP-76 slip to W24. PRP-109.
- GD-13 (decided): the program as listed (PRP-99 to PRP-137), not merged to fewer PRPs. No PRP row needed.
- GD-14 (decided 2026-11-16): the 2026-11-06 metadata-only decision is reversed for opt-in capture only; capture stays OFF by default and "bodies disabled by default" stays true; the orchestrator records it in the decision log. PRPs 99, 101 to 104.
- GD-15 (decided): the risk tier is the customer's recorded determination with the questionnaire as evidence; the product never states a legal classification. PRPs 110, 127, 128.

Decisions raised while planning (GD-16 onward), all decided:

| GD | Decision (decided 2026-11-16; the sentence to cite, first letter lowercased after the colon) | Alternative not chosen | PRPs |
|---|---|---|---|
| GD-16 | An `interaction_investigator` assignment longer than 7 days is refused (`role_assignment_too_long`). | Only the existing privileged `expires_at` rule | 104 |
| GD-17 | An interaction export holds at most 500 interactions from one domain, its bundle expires after 24 hours, and an investigator has at most 5 open exports. | Other limits | 104 |
| GD-18 | If Key Vault key wrap is unavailable in a cloud, content capture is disabled there (`key_wrap_unavailable`); no weaker fallback (such as a Key Vault secret as the key-encryption key) is built. | Build the secret-as-KEK fallback | 102, 136 |
| GD-19 | Only the credential detectors and Luhn-valid payment cards are gated at recall 1.0 on the synthetic corpus; the other detectors report measured recall without a gate. | Gate more detectors | 101 |
| GD-20 | Every governance action kind (`agent_version_approve`, `agent_version_suspend`, `capture_policy_change`, `governance_policy_publish`, `enforcement_mode_change`) is approved by a second person holding `action.approve` in the target's domain (a domain steward), never the maker; no built-in approver-permission override is shipped (GD-1 chose a second steward). | Per-kind approvers (`config.manage` for capture, `govpolicy.manage` for publish and mode change), which would have needed GD-1 option (b) | 99, 105, 108, 112 |
| GD-21 | `govpolicy.read` is held by viewer, analyst, domain_steward, admin and security_auditor; `govpolicy.manage` (drafting and recording) by domain_steward and admin. | Stewards only; auditors excluded | 105, 106, 112, 116 |
| GD-22 | In `enforce` mode the tool-call guard blocks (`policy_unavailable`) when the policy engine is unreachable; in `audit` mode it fails open with a counter. | Fail open in both modes | 113 |
| GD-23 | Gateway enforcement needs two approved intents: `enforcement_mode_change` (NeuroSphere state) and then `gateway_policy_apply` (the external change), with a canary on one product first. | One combined intent | 112 |
| GD-24 | `incident.manage` is held by domain_steward only; admin does not hold it. | Admin also holds it | 132 |
| GD-25 | Every MCP tool call is audited (`mcp.tool_call`), not only the governance tools. | Governance tools only | 116 |
| GD-26 | A producer may ask the decision API only about catalog agents whose `source_id` is one of its own sources; others are 403 `subject_not_permitted`. | Any agent of its customer | 114 |
| GD-27 | Two new producer routes, `POST /api/v1/ingest/interactions` and `POST /api/v1/ingest/capture-scope`, and the worker switch `NS_GATEWAY_POLL_CAPTURE_ENABLED` (default false), which must also be true before the gateway poller captures. | Content inside OTLP attributes; policy only | 111 |
| GD-28 | Shadow-AI findings report counts only, never person ids (not even pseudonyms), and groups smaller than 5 are suppressed. | Pseudonymous per-person findings | 126 |
| GD-29 | Rolling back a `ticket_create` closes the ticket with a note; it never deletes it. | Delete on rollback | 133 |
| GD-30 | Embedding spend is capped by default at 2000 embeddings per refresh and 20000 per day. | Other caps | 135 |
| GD-31 | Label mapping edits are an audited admin-config mutation by a domain steward, not an executor action. | An executor action with approval | 120 |
| GD-32 | "Who could" answers are readable with `data.read`, like PRP-73's "who did" answers. | A stricter permission | 119 |
| GD-33 | A directory role or permission with no mapping is counted as `admin` access (over-report rather than under-report). | Count it as unknown | 118 |
| GD-34 | "Never used" is claimed only with activity evidence covering the window, default 30 days. | Another window | 119 |
| GD-35 | Lineage push-back is enabled per system only where create, read-back and delete were all verified; otherwise `lineage_push` stays advisory. | Enable where create alone is verified | 121 |
| GD-36 | No risk tier requires an approved impact assessment by default (`NS_RISK_ASSESSMENT_REQUIRED_TIERS` empty); the customer sets the list. | `high` requires one by default | 127, 129 |
| GD-37 | Waiving an attestation records the gap and keeps the related policy violation open unless a PRP-105 exception covers it. | A waiver resolves the violation | 130 |
| GD-38 | Re-resolution after an alias change is an operator job (`python -m neurosphere_workers.agent_identity reresolve`); an automatic trigger is a follow-up. | Automatic trigger on alias write | 137 |
| GD-39 | Recording a safety evaluation reuses `catalog.curate`; no `safety.record` permission. | A new `safety.record` permission | 131 |
| GD-40 | Showback counts any authoritative amount, each total labelled estimated or invoiced; chargeback counts invoiced amounts of ended periods only. | Another close rule set by the finance owner | 134 |
| GD-41 | No cost-center by agent cross-tab; two separate views (the ledger has no agent id, the aggregates no cost center). | A cross-tab, which needs a contract and ingest change | 134 |
| GD-42 | PRP-120 (Purview) and PRP-121 (Unity Catalog) are P1, because the original product description named both. | P2 with the other estate connectors | 120, 121 |
| GD-43 | The hosted north-star run is operator-attended: the operator supplies two steward identities, an auditor and a webhook endpoint stored in Key Vault; the deploy pipeline runs only a non-interactive readiness check. | The pipeline signs in (needs session tokens in CI, refused) | 109, 136 |
| GD-44 | `enforcement_mode_change` is drafted through the generic `POST /api/v1/actions/domains/{domain}/intents` with PRP-105's `mode_change_diff` grammar; no dedicated route. | PRP-105 adds `POST .../bindings/{id}/mode-change` | 105, 106, 116 |
| GD-45 | No dedicated CI role: `registration.check` is granted to the read-class roles (viewer, analyst, domain_steward, admin). | A `ci` role value in the contract role enum (next contracts owner) | 110, 129 |
| GD-46 | The payload `domain_id` is trusted for capture only together with the registered source; an event with no domain is never captured. | Trust the source alone | 103, 111 |
| GD-47 | Impact-assessment review and attestation non-response use the existing HITL `recommendation` kind with action kinds `impact_assessment_review` and `attestation_overdue_review`; no new HITL kind. | A dedicated HITL kind (contract and `hitl/models.py` change) | 127, 130 |
| GD-48 | One active estate connector config per vendor kind (one tenant per vendor); multi-tenant is a follow-up. | Several configs per kind | 117, 122 to 126 |
| GD-49 | Without a field-level lock in the contracts, GD-11's "steward-curated value (locked)" is implemented as: the asset's own declared sensitivity wins whole. | A lock field from the next contracts owner | 120, 121 |

## Completion note (filled at ship)
- Date and PR:
- Provided names (for PRP-100 to PRP-136 authors):
- Deviations:
- Descoped items:
- OPEN gates:
- Env vars for the operator: none expected.
- Follow-up issues:
- Product check (can an operator use it without editing files): no, by design; contracts only.
