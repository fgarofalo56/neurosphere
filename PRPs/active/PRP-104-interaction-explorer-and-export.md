---
name: PRP-104-interaction-explorer-and-export
status: active
started: 2026-11-27
execution: session
max_lanes: 2
priority: P0
order: 104
review: required
created: 2026-11-16
model: opus
orchestrator_model: opus
implementer_model: opus
phase: 9
ns: NS-05, NS-08
depends_on: [PRP-99-governance-contracts-a, PRP-102-encrypted-interaction-store-and-retention, PRP-103-interaction-capture-policy-and-edge, PRP-105-policy-engine-core]
wave: W23
branch: prp-104-interaction-explorer
allow_parallel: true
issues: []
---

# PRP-104: Interaction explorer, audited content reads and export

## Goal
Let an investigator find captured interactions and, with a dedicated permission and a stated purpose, read or export their redacted content, with every content read and every export audited before anything is returned. It adds the permissions `interaction.read` and `interaction.export`, held by no existing role (admin included), and a new privileged, time-bound, domain-bound role `interaction_investigator` that holds only those two; a metadata explorer API (search by agent, principal pseudonym, time, tool, data asset and detected category; findings and redaction state without content) that needs only `data.read`; a content-read route that requires `interaction.read`, a purpose code and a fail-closed audit record; a bounded export that writes an encrypted bundle with a manifest and its own audit record; replay integration so the existing payload branch of the trace route obeys the same rule; and the explorer UI. It is for security investigators, legal-hold reviewers and the people answering data-subject requests, and runs in W23 after PRP-102 and PRP-103. Opus: this is the only path by which a person sees captured content.

Out of scope: capture and storage (PRP-103, PRP-102); copilot or MCP access to content, which is refused by decision GD-3 (PRP-116 adds metadata-only tools); DSR erase and export orchestration over `interaction_content` (PRP-83); the governance trail page (PRP-109); policy violations that cite interactions (PRP-105, PRP-106); changes to the replay page UI (follow-up).

## Why
- The owner asked on 2026-11-16 for "the ultimate team AI governance and auditing tool" with every gap planned; `docs/PRD.md:26` (NS-05) promises "Payload access, retention, export and legal hold follow policy", and `docs/PRD.md:37` (NS-08) "Privileged access remains scoped, time-bound and auditable; no unrestricted 'God' bypass."
- The replay payload branch exists and is guarded only by `data.read`: `services/api/neurosphere_api/replay/router.py:40` (`require(Permission.DATA_READ, ...)`), `:81,95-107` (`include_payload` and `PayloadPolicy.allow_bodies`), with `PayloadPolicy(allow_bodies=False)` (`replay/dependencies.py:21-25`, set at `runtime/builders/data.py:576`) and `ArchiveTraceReader.read_payload` returning None (`replay/reader.py:282-286`). Flipping `allow_bodies` today would hand content to every viewer, unaudited.
- `audited_read` is fail-open by design ("a failed or unconfigured audit write is logged ... it never blocks or alters the read", `services/api/neurosphere_api/authz/read_audit.py:22-25`, `ReadAudit.allowed` `:137-173`), and the audit record has no purpose field (`audit/v1/audit-record.schema.json` properties end at `subject`, `outcome`, `denial`). Content reads need a fail-closed record and a purpose bound into it.
- The role set is closed and five strong (`packages/core/neurosphere_core/auth/scope/permissions.py:1-17,73-78`); privileged roles must carry `expires_at` (`PRIVILEGED_ROLES` `:143`, enforced at `auth/scope/policy.py:76`); admin holds `data.read` but not audit or evidence permissions (`permissions.py:105-117`), the separation-of-duties precedent GD-2 follows. A duplicate privileged set lives at `services/api/neurosphere_api/admin/identity/service.py:97`; self-assignment is already refused there (`self_modification_forbidden`, `:232`). The UI role list is hard-coded at `frontend/src/features/admin/identity/types.ts:2-9`.
- Audit export precedent: `services/api/neurosphere_api/audit/export.py:45-50,167-169` (row cap, `audit.export`).

## Acceptance criteria
- [ ] `interaction_investigator` exists in core with exactly `interaction.read` and `interaction.export`; no other role holds either (test over `ROLE_PERMISSIONS`); it is privileged (an assignment without `expires_at` is refused) and assignable by `policy.manage`; an admin cannot assign it to themselves (`self_modification_forbidden`).
- [ ] Given a caller with `data.read` in domain D, When they search interactions in D, Then they get metadata, findings summary and redaction state, never content, with an allowed-read record; a caller without `data.read` in D gets 403 and a denial record.
- [ ] Given an unexpired investigator in D, When they `POST .../interactions/{id}/content-reads` with a valid `InteractionAccessPurpose`, Then one `interaction.read` audit record (actor, interaction target, purpose code and case reference bound into `state_digest`, correlation id) is appended BEFORE the blob is decrypted, and the response is the stored `RedactedContent` with `Cache-Control: no-store`; if the audit write fails, the answer is 503 and nothing is decrypted.
- [ ] Admin, security auditor, steward, analyst, viewer, an expired investigator, an investigator of another domain, another customer or another cloud all get 403 on content reads and exports, each with a denial record; a missing or unknown purpose code is 422 before any read.
- [ ] Given an export request with a purpose and filters, Then at most 500 interactions are bundled (excess counted in `excluded_count`), the bundle is sealed with PRP-102's envelope under the content key, the `InteractionExportManifest` lists ids, counts, `includes_held_content` and the `interaction.export` audit id, the bundle expires after 24 hours, and the download writes its own fail-closed audit record. Held content is exportable; nothing in this PRP deletes content.
- [ ] Exports and reads contain only stored redacted content: a redacted-away value (generated secret, card) never appears in a response or bundle.
- [ ] The replay route returns a span payload only when `include_payload` is true, the deployment has the explorer configured, the caller holds `interaction.read` in the domain and supplies a purpose; it goes through the same audited read; otherwise behaviour is exactly as today (`services/api/tests/replay` passes).
- [ ] Content is never returned to the copilot or MCP: no copilot tool or MCP server tool depends on the content reader (structural import test plus a tool-list test), and captured canaries never appear in copilot or MCP responses, logs, audit records, SIEM events or `services/api/openapi.json` examples.
- [ ] The explorer UI lists and filters interactions, shows findings with the "structured identifiers only" coverage label, asks for a purpose before revealing content, and offers export; every new route is in the inventories and boots under `verify_route_permissions`.
- PRP exit: touched suites, `tests/security/authz`, `tests/security/interaction_access`, ruff, pyright, frontend gates, `validate_planning.py` pass; PR open with CI green; `openapi.json` regenerated.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| 1 | Reverse metadata-only | keep; reverse for opt-in | Decided by the owner 2026-11-16 (GD-14): the 2026-11-06 metadata-only decision is reversed for opt-in capture only; capture stays OFF by default and "bodies disabled by default" stays true; the orchestrator records it in the decision log |
| 2 | Who may read content | security auditor; admin; new role | Decided by the owner 2026-11-16 (GD-2): new privileged, time-bound role `interaction_investigator`; admin does not hold `interaction.read`; purpose required on every read. Here: admin can assign the role (PRP-99 added it, empty) but holds neither permission |
| 3 | Content to copilot or MCP | allowed for investigators; no | Decided by the owner 2026-11-16 (GD-3): captured content is not shown to the copilot or MCP; tools see metadata and findings only; revisit after the north star |
| 4 | How the purpose is audited | free text; code | PRP-99 `InteractionAccessPurpose` code plus optional case reference; bound into the record's `state_digest` (the audit contract has no purpose field) and repeated in a metadata access entry on the interaction index |
| 5 | Audit failure on a content read | fail open like `audited_read`; fail closed | Fail closed: append the record first through the audit repository, decrypt only after it succeeds (`run_audited_mutation` style, `audit/repository.py:247-270`) |
| 6 | Metadata permission | `interaction.read`; `data.read` | `data.read` in the domain (design: "metadata listing without the content permission"); an investigator who needs the list also holds a viewer assignment there |
| 7 | Export limits | other limits | Decided by the owner 2026-11-16 (GD-17): an interaction export holds at most 500 interactions from one domain, its bundle expires after 24 hours, and an investigator has at most 5 open exports. Here: 500 follows the lifecycle `MAX_EXPORT_RECORDS` precedent (`lifecycle/models.py:21`) |
| 8 | Maximum investigator assignment | existing privileged rule only; a cap | Decided by the owner 2026-11-16 (GD-16): an `interaction_investigator` assignment longer than 7 days is refused (`role_assignment_too_long`) |
| 10 | Who binds PRP-105's `InteractionFindingReader` | PRP-103; this PRP; PRP-109 | This PRP, item 8, and nobody else: PRP-105 (W21) left the port unbound and named binding functions for it; this is the first wave where both PRP-105 and the index query (PRP-102) exist next to the explorer that owns read semantics |
| 9 | Replay switch | edit `builders/data.py:576`; derive | `get_payload_policy` derives `allow_bodies` from the presence of the explorer on `app.state`; `builders/data.py` is not edited |

## Context manifest

### Files to read first
- `services/api/neurosphere_api/replay/{router,dependencies,reader}.py` - the payload branch, `PayloadPolicy`, `read_payload`.
- `services/api/neurosphere_api/authz/read_audit.py` - allowed-read records (metadata routes) and why content needs more.
- `packages/core/neurosphere_core/audit/repository.py:247-270` and `audit/builders.py` - fail-closed append, `build_allowed`, `make_subject`.
- `packages/core/neurosphere_core/auth/scope/permissions.py` and `auth/scope/policy.py:60-80` - roles, privileged rule.
- `services/api/neurosphere_api/admin/identity/service.py:90-110,225-240` - privileged set, self-modification refusal.
- `services/api/neurosphere_api/audit/export.py` - bounded export shape.
- `frontend/src/features/replay/` and `frontend/src/features/admin/identity/types.ts` - UI patterns and the role list.
- PRP-99, PRP-102, PRP-103 "Interfaces provided".

### Interfaces consumed
- PRP-99: `InteractionRecord`, `RedactedContent`, `DetectionFinding`, `InteractionAccessPurpose` (`incident_investigation`, `policy_violation_review`, `legal_hold_review`, `data_subject_request`, `security_review`, `quality_review`, open-ended; `case_ref`), `InteractionExportManifest`; role enum value `interaction_investigator` with the privileged `expires_at` rule in `scope/v1/identity-scope` and `admin/v1`; audit operation names `interaction.read`, `interaction.export`; permission names `interaction.read`, `interaction.export` (core names, defined here).
- PRP-102: `InteractionStore` (`query_index`, `get_metadata`, `read_content`), `seal`, `open_envelope`, `KeyWrapper`, export blob prefix under the content container.
- PRP-103: component `interaction_capture`, pointer scheme `interaction:<interaction_id>`, `runtime/builders/interactions.py` (store and wrapper construction to reuse, not edit).
- Shipped: `require`, `domain_from_path`, `audited_read`, `AuditRepository.append`, `make_subject`, `domain_audit_chain_id`, `TraceReader`.

### Interfaces provided
- Core: `Permission.INTERACTION_READ = "interaction.read"`, `Permission.INTERACTION_EXPORT = "interaction.export"`, assigned to the existing `Role.INTERACTION_INVESTIGATOR` (PRP-99 adds the member with an empty permission set; this PRP only fills it).
- `InteractionFindingReaderAdapter` (new, `packages/core/neurosphere_core/governance/policy/readers/interactions.py`): PRP-105's `InteractionFindingReader` over PRP-102's `InteractionStore.query_index`, returning per-subject category counts and interaction ids only, bounded by window and page; bound in PRP-105's two binding functions by item 8, so PRP-105's `content_rule` becomes available.
- Routes: `GET /api/v1/domains/{domain_id}/interactions` (`data.read`; filters `agent_id`, `principal_id`, `from`, `to`, `tool_id`, `data_asset_id`, `detected_category`; bounded page), `GET /api/v1/domains/{domain_id}/interactions/{interaction_id}` (`data.read`, metadata), `POST /api/v1/domains/{domain_id}/interactions/{interaction_id}/content-reads` (`interaction.read`), `POST /api/v1/domains/{domain_id}/interaction-exports` and `GET .../interaction-exports/{export_id}` (`interaction.export`, manifest), `GET .../interaction-exports/{export_id}/bundle` (`interaction.export`, audited download).
- `InteractionContentReader` (the one code path that decrypts for a person) in `neurosphere_api.interactions`; `app.state.interaction_explorer`.
- Replay: `trace` route query parameters `purpose_code`, `case_ref` used only with `include_payload=true`.
- Frontend route `/interactions` and nav entry "Interactions".

### Patterns to match
- Domain-scoped read routes: `replay/router.py:36-72`; allowed-read audit: `authz/read_audit.py:176-195`.
- Fail-closed audit before effect: `audit/repository.py:247-270`.
- Bounded export: `audit/export.py:45-50,138-170`.
- Privileged role tests: `tests/security/authz/test_privileged_roles.py`, `packages/core/tests/auth/scope/test_roles.py`.
- Frontend feature with mock API and e2e: `frontend/src/features/replay/`, `frontend/tests/mock-api/features/index.ts`.

### Gotchas
- `domains_with_permission` intersects with `allowed_domains` only for `data.read` (`permissions.py:183-185`); the content service must intersect the investigator's domains with `allowed_domains` itself (do not change that function).
- Adding the role changes one existing line (`PRIVILEGED_ROLES`, `permissions.py:143`) in a Tier-2 file; keep it a one-line change and resolve at rebase. The docstring table (`permissions.py:7-17`) and "Five roles" text must be updated in the same commit.
- Audit records must stay content-free: `assert_metadata_only` refuses `prompt`, `response`, `messages`, `body` keys and e-mail-shaped strings (`content_guard.py:21-45,87-131`); the case reference is a record id, never prose.
- A contract model as `response_model` renames `openapi.json` components; OpenAPI examples must use the PRP-99 placeholder text only, never realistic content.
- Same-named test directories shadow: use `services/api/tests/interaction_explorer_api/` and `tests/security/interaction_access/`.
- If PRP-99 shipped without the role enum change, contracts are not owned by any W23 PRP: add a first `[serial-after: none]` contracts item only with orchestrator approval and report it; do not edit `packages/contracts/**` otherwise.
Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - services/api/neurosphere_api/interactions/**
  - services/api/neurosphere_api/replay/router.py
  - services/api/neurosphere_api/replay/dependencies.py
  - services/api/neurosphere_api/replay/reader.py
  - services/api/neurosphere_api/runtime/builders/interaction_explorer.py
  - services/api/neurosphere_api/runtime/builders/interactions.py  # item 2 only: one additive public store factory (approved 2026-11-27)
  - packages/core/neurosphere_core/governance/policy/readers/**
  - packages/core/tests/governance_policy_readers/**
  - services/workers/neurosphere_workers/policy_eval/assembly.py
  - services/workers/tests/policy_eval_worker/test_finding_reader_binding.py
  - services/api/neurosphere_api/runtime/builders/governance.py
  - services/api/neurosphere_api/admin/identity/service.py
  - services/api/tests/interaction_explorer_api/**
  - tests/security/interaction_access/**
  - tests/security/authz/test_interaction_access.py
  - frontend/src/features/interactions/**
  - frontend/src/features/admin/identity/types.ts
  - frontend/tests/mock-api/features/interactions.ts
  - frontend/tests/e2e/interactions/**
  - docs/runbooks/interaction-audit.md
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
  - frontend/src/app/appRoutes.ts
  - frontend/src/app/route-manifest.json
  - frontend/src/app/workspaceNav.ts
  - frontend/tests/mock-api/features/index.ts
  - frontend/tests/e2e/a11y/route-samples.ts
  - frontend/tests/real-stack/routes.spec.ts
  - mkdocs.yml
must_not_touch:
  - packages/contracts/**
  - packages/core/neurosphere_core/interactions/**
  - packages/core/neurosphere_core/crypto/**
  - packages/core/neurosphere_core/audit/**
  - packages/core/neurosphere_core/copilot/**
  - services/api/neurosphere_api/copilot/**
  - services/api/neurosphere_api/mcp/**
  - services/api/neurosphere_api/runtime/builders/data.py
  - services/api/neurosphere_api/ingest/**
  - frontend/src/app/Shell.tsx
  - frontend/tests/mock-api/server.ts
```

## Implementation blueprint

Approved plan (2026-11-27, session s-902135): 1 -> 2 -> {3, 8} -> {4, 5} -> {6, 7} -> 9, at most 2 lanes; item 5 waits for item 3 so it calls the real `InteractionContentReader` (no stub). Original blueprint: item 1 first; items 2 and 5 [P] after 1 (separate files); item 3 after 2; item 4 after 3; item 6 after 2-4; item 7 after 3-5; item 8 after 2; item 9 last.

### Item 1 - Role and permissions
- Deliverable: `Permission.INTERACTION_READ`, `INTERACTION_EXPORT`, granted to the existing `Role.INTERACTION_INVESTIGATOR` (PRP-99 added the member, empty and already in `PRIVILEGED_ROLES`) and to no other role; docstring table updated; `admin/identity/service.py:97` privileged set and the 7-day cap (row 8); `types.ts` role list; role and privileged-role tests extended.
- Owned files: the Tier-2 lines in `permissions.py`, `test_roles.py`, `test_privileged_roles.py`; `admin/identity/service.py`; `frontend/src/features/admin/identity/types.ts`.
- Must NOT touch: `domains_with_permission`, `permits`.
- Depends on: PRP-99 (role enum) merged.
- Acceptance criteria: criterion 1; existing `packages/core/tests/auth`, `services/api/tests/admin_identity_api` and `tests/security/authz/test_admin_identity.py` pass.
- Tests: `packages/core/tests/auth/scope/test_roles.py`, `tests/security/authz/test_privileged_roles.py`, `services/api/tests/interaction_explorer_api/test_role_assignment.py`.
- Pattern references: `permissions.py:100-143`.

### Item 2 - Metadata explorer API  [P]
- Deliverable: `interactions/{router,service,models}.py` list and detail routes over `InteractionStore.query_index` and `get_metadata`, scope-filtered, page-bounded, `audited_read(Permission.DATA_READ, "interaction.search")`; builder `runtime/builders/interaction_explorer.py` (reuses PRP-103's store construction through its exported factory; reports `interaction_explorer` optional) and its `default_builders` line.
- Owned files: `services/api/neurosphere_api/interactions/{__init__,router,service,models}.py`, the builder, `services/api/tests/interaction_explorer_api/test_search.py`; in `runtime/builders/interactions.py` one additive public store factory only (plan delta 2026-11-27: PRP-103 exported no factory).
- Must NOT touch: any existing function or behaviour of `runtime/builders/interactions.py`.
- Depends on: item 1.
- Acceptance criteria: criterion 2; responses validate against `InteractionRecord` minus nothing (no content field exists); pinned builder-order tests updated.
- Tests: `services/api/tests/interaction_explorer_api/test_search.py`; re-run `services/api/tests/runtime_api`, `runtime_data`, `runtime_gateway_builder`.
- Pattern references: `replay/router.py:36-72`.

### Item 3 - Audited content read
- Deliverable: `interactions/content.py` `InteractionContentReader`: permission and domain check (`interaction.read`, domains intersected with `allowed_domains`), purpose validation, cloud and customer match, fail-closed `interaction.read` record (purpose and case ref bound into `state_digest`, correlation id), then `read_content`; metadata access entry on the index; route with `Cache-Control: no-store`.
- Owned files: `interactions/content.py`, route additions in `interactions/router.py`, `services/api/tests/interaction_explorer_api/test_content_read.py`.
- Must NOT touch: core interactions modules.
- Depends on: item 2.
- Acceptance criteria: criteria 3, 4, 6.
- Tests: `services/api/tests/interaction_explorer_api/test_content_read.py`, `test_audit_fail_closed.py`.
- Pattern references: `audit/repository.py:247-270`.

### Item 4 - Export bundle and manifest
- Deliverable: `interactions/export.py`: create (bounded per row 7, purpose required, `interaction.export` record), bundle sealed with PRP-102's envelope into the content container's export prefix, manifest as `InteractionExportManifest`, download that re-checks permission, writes its own record, decrypts and streams; expired bundles refused and deleted.
- Owned files: `interactions/export.py`, route additions, `services/api/tests/interaction_explorer_api/test_export.py`.
- Must NOT touch: lifecycle code.
- Depends on: item 3.
- Acceptance criteria: criteria 5 and 6.
- Tests: `services/api/tests/interaction_explorer_api/test_export.py`, `test_export_held_content.py`.
- Pattern references: `audit/export.py:138-170`.

### Item 5 - Replay integration  [P]
- Deliverable: `replay/dependencies.py` derives `allow_bodies` from `app.state.interaction_explorer` (row 9); `replay/router.py` payload branch requires `interaction.read` and a purpose and calls `InteractionContentReader` (one record per trace read, listing the interaction ids); `replay/reader.py` `ArchiveTraceReader.read_payload` resolves `interaction:` pointers through the reader seam and returns None for any other pointer.
- Owned files: `services/api/neurosphere_api/replay/{router,dependencies,reader}.py`, `services/api/tests/interaction_explorer_api/test_replay_payload.py`.
- Must NOT touch: `replay/assemble.py`, `replay/models.py`.
- Depends on: item 1 (the reader interface; stub until item 3 merges).
- Acceptance criteria: criterion 7; existing replay suites pass unchanged.
- Tests: `services/api/tests/interaction_explorer_api/test_replay_payload.py`, plus every `services/api/tests` directory that imports `neurosphere_api.replay` (grep before pushing).
- Pattern references: `replay/router.py:74-110`.

### Item 6 - Explorer UI
- Deliverable: `frontend/src/features/interactions/`: list with filters, detail with findings and the coverage label, "Reveal content" dialog that requires a purpose code and shows the case reference, export flow with manifest view; mock-api feature; e2e and a11y samples; nav and route lines.
- Owned files: `frontend/src/features/interactions/**`, `frontend/tests/mock-api/features/interactions.ts`, `frontend/tests/e2e/interactions/**`, Tier-2 frontend lines.
- Must NOT touch: `Shell.tsx`, `mock-api/server.ts`.
- Depends on: items 2-4 (routes).
- Acceptance criteria: criterion 9; mock fixtures are synthetic.
- Tests: `frontend/src/features/interactions/*.test.tsx`, `frontend/tests/e2e/interactions/interactions.spec.ts`.
- Pattern references: `frontend/src/features/replay/`.

### Item 7 - Access and leakage negative suite
- Deliverable: `tests/security/authz/test_interaction_access.py` (deny per dimension in criterion 4, each with a denial record) and `tests/security/interaction_access/` (canaries absent from logs, audit, SIEM, OpenAPI, copilot and MCP; structural test that `neurosphere_api.copilot`, `neurosphere_core.copilot` and `neurosphere_api.mcp` import nothing that reaches `InteractionContentReader` or `InteractionStore.read_content`; cross-cloud refusal).
- Owned files: those test files.
- Must NOT touch: shared harness beyond additive helpers.
- Depends on: items 3-5.
- Acceptance criteria: criteria 4, 6, 8.
- Tests: `tests/security/authz/test_interaction_access.py`, `tests/security/interaction_access/test_no_content_to_models.py`, `test_no_content_in_sinks.py`.
- Pattern references: `tests/security/authz/test_admin_producers_secrecy.py`, `test_api_paths.py`.

### Item 8 - Bind PRP-105's `InteractionFindingReader`
- Deliverable: the one binding of PRP-105's `InteractionFindingReader` port (PRP-105 clarification 12): `InteractionFindingReaderAdapter` over PRP-102's `InteractionStore.query_index` (category counts per subject and window, interaction ids, never content, never a decrypt), and the bodies of PRP-105's binding functions `interaction_finding_reader` in `services/workers/neurosphere_workers/policy_eval/assembly.py` and in `services/api/neurosphere_api/runtime/builders/governance.py`, returning the adapter when the interaction store is configured and `None` otherwise.
- Owned files: `packages/core/neurosphere_core/governance/policy/readers/**` (new), `packages/core/tests/governance_policy_readers/**` (new), the `interaction_finding_reader` function in the two files above.
- Must NOT touch: any other PRP-105 file or function; `packages/core/neurosphere_core/interactions/**`.
- Depends on: item 2; PRP-105 merged (W21).
- Acceptance criteria: with the store configured, PRP-105's `GET /status` no longer lists `content_rule` as `evaluator_unavailable`, and a published `content_rule` policy opens a violation on fakes whose evidence is `interaction_record` ids only; with capture off, `content_rule` stays unavailable; the adapter never calls `read_content`.
- Tests: `packages/core/tests/governance_policy_readers/test_interaction_findings.py`, `services/workers/tests/policy_eval_worker/test_finding_reader_binding.py`.
- Pattern references: PRP-105 `rules/content_rule` evaluator; PRP-102 `CosmosInteractionIndex.query_index`.

### Item 9 - Integration and close-out
- Deliverable: runbook sections (assigning the role, purposes, reading, exporting, what the audit records show, why admin cannot read); Tier-2 lines; Tier-3 regeneration; changelog fragment; completion note with the product check and the follow-up for the replay page UI.
- Owned files: runbook, Tier-2 lines, this PRP file, changelog fragment, Tier-3 files.
- Depends on: items 1-8.
- Acceptance criteria: validation gates pass; CI green.

## How the hard constraints are kept
- Authorization at every path: separate permissions for metadata, content and export; scope server-derived; no bypass, admin excluded; denials recorded.
- Every read audited with a purpose, fail closed; the record carries no content.
- No content to the copilot or MCP (GD-3), proven structurally.
- Never across the cloud boundary: records of another cloud are refused; bundles stay in the deployment's own storage and key.
- Synthetic data only in tests, mocks and demos.

## Validation gates
```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q services/api/tests/interaction_explorer_api packages/core/tests/governance_policy_readers services/workers/tests/policy_eval_worker tests/security/interaction_access tests/security/authz packages/core/tests/auth services/api/tests/authz services/api/tests/runtime_api services/api/tests/runtime_routes services/api/tests/runtime_data services/api/tests/runtime_gateway_builder services/api/tests/test_openapi_drift.py tests/docs/test_reference_coverage.py tests/docs/test_nav_allowlist.py
pnpm --filter @neurosphere/frontend lint
pnpm --filter @neurosphere/frontend typecheck
pnpm --filter @neurosphere/frontend test
pnpm --filter @neurosphere/frontend test:e2e
python scripts/prp_status.py --check
python scripts/validate_planning.py
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```

## Migration and rollback
No data migration. The new role has no assignments until an admin creates one. Export bundles expire after 24 hours. Rollback: remove the explorer builder from the deployment (replay returns to `allow_bodies=False`, content routes answer 503) or revert the PR; existing role assignments of `interaction_investigator` must be removed first through the identity admin API, because core would refuse an unknown role.

## Live and open gates
None run here. Reading content on the hosted app (synthetic domain) is part of PRP-109's north-star run and PRP-136's evidence, both operator-approved with `NS_LIVE_APPROVED=1`; OPEN until then.

## NOT building
- Any copilot or MCP tool that returns captured content (GD-3); PRP-116 ships metadata-only tools.
- Recovering redacted-away values: they were never stored.
- Deletion of content from the explorer (lifecycle and PRP-83 own erasure; holds win).
- A claim that the explorer is a DLP, e-discovery or compliance product, or parity with any vendor product (design section 8 items 2 and 5).
- Detection coverage beyond "structured identifiers only" (design section 8 item 4).

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [x] All clarification questions are decided, not guessed (rows 1-3, 7 and 8 are GD decisions made 2026-11-16)

## Execution state
| Item | Status | Branch/worktree | Notes |
|---|---|---|---|
| 1 | merged | worktree-agent-aed46cb947c743860 (opus) | 2026-11-27: verified ruff/format/pyright + 536 pytest passed; Snyk 0; review APPROVED; merged 0bc2dad2. Follow-ups: core-level 7-day cap (sandbox grant script bypasses API), stale contract docstring on privileged roles |
| 2 | merged | worktree-agent-ae3f89cff92c30a5c (opus) | 2026-11-27: verified ruff/format/pyright + 380 pytest passed; Snyk 0; review APPROVED; merged d4c46c74. Follow-up: explorer turns off with retention_not_enabled although held content may exist |
| 3 | merged | worktree-agent-af320c0eb7875a2f6 (opus) | 2026-11-27: verified ruff/format/pyright + 203 pytest passed; Snyk 0; review APPROVED (3/4 mutations killed; survivor is defence in depth); merged fcc0849d, post-merge 134 passed. Content read also needs data.read in the domain (Gotchas + row 6); GUID-shaped case_ref is 422 (audit guard). Follow-ups: _visible-only domain test; unauthorized + invalid purpose gives 403 not 422. Plan delta (owner, 2026-11-27): clarification row 4's index access entry descoped (no contract field, no store API); the fail-closed audit record is the access trail; follow-up issue at close-out |
| 4 | merged | worktree-agent-a20d93be38d3e32fb (opus) | 2026-11-28: verified ruff/format/pyright + 391 pytest passed; Snyk 0; review APPROVED (3/3 mutations killed); merged af7d3eb1 (openapi/docs regenerated on the merged tree), post-merge 397 passed. 6th open export = 429 + Retry-After; manifest/bundle creator-only; expired = 404 + delete; state in blobs. Follow-ups: cross-replica race past the 5 cap; audit ids vs manifest ids after a mid-export purge; orphan bundle if cleanup fails; cap scan 503s past 2,000 manifests per customer; non-creator on expired export gets 403. Delta: PRP-102 defines no export prefix and keeps the content container + key wrapper private; item 4 adds memoized public accessors in runtime/builders/interactions.py (same rationale as item 2's factory) and stores bundles + manifests under exports/ in the content container |
| 5 | merged | worktree-agent-af9f0924e885769bc (opus) | 2026-11-28: verified ruff/format/pyright + 478 pytest passed; Snyk 0; review APPROVED (2/2 mutations killed); merged 20822618. >100 pointers per trace = 422 interaction_batch_too_large; legacy per-span loop kept (test-override only). Fix in item 9: _domain_pointers must filter trace_id and keep the first duplicate span like assemble_trace. Follow-up: tenancy-mismatched investigator gets 403 not payload-free |
| 6 | merged | worktree-agent-a78b3b30ab005dd05 (opus) | 2026-11-28: verified lint/typecheck + vitest 171 + playwright 12 + runtime_routes 6 passed (implementer: playwright 744 incl. a11y/demo-audit, Docker visual 90 with 4 new baselines); Snyk 0; review APPROVED; merged 5598fc0b. Nav: Governance group. /interactions shell-only in manifest_calls (composed app 503s without explorer). Follow-ups: shared client retries a retryable 429 for ~1 min; export dialog lacks from<to check; mock search ignores from/to. Real-stack browser run pending in item 9 |
| 7 | merged | worktree-agent-a8a56f6a953e18fc5 (opus) | 2026-11-28: verified on a clean tree ruff/format/pyright + 264 pytest passed; Snyk 0; review APPROVED (no vacuous scans); 5/5 mutations killed; merged f7377760. Follow-ups: runtime.builders barrier hides re-exported names; importlib/__import__ not followed; pin exact outcomes on auditor-replay and Government-deployment rows after the row-5 tenancy follow-up |
| 8 | merged | worktree-agent-a1a7e19d214226f26 (opus) | 2026-11-27: verified ruff/format/pyright + 519 pytest passed; Snyk 0; review APPROVED; merged 9b30571b. Follow-ups: API vs worker binding signals can disagree; scan-cap truncation has no distinct reason; binding resolved at build time (restart needed); PRP-105 module docstrings still say "unbound" |
| 9 | in-progress | orchestrator + implementer (opus) | 2026-11-28: replay _domain_pointers fix, runbook sections, changelog, real-stack browser run, follow-up issues, Tier-3 regen |

## Completion note (filled at ship)
- Date and PR:
- Deviations:
- Descoped items:
- OPEN gates:
- Env vars for the operator:
- Follow-up issues:
- Product check (can an operator use it without editing files):
