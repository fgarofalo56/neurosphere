---
name: PRP-131-model-and-agent-cards-and-safety-evaluation-records
status: backlog
priority: P2
order: 131
review: required
created: 2026-11-16
model: sonnet
orchestrator_model: sonnet
implementer_model: sonnet
phase: 9
ns: NS-03, NS-08
depends_on: [PRP-110-governance-contracts-b, PRP-127-ai-system-register-tiering-and-impact-assessments, PRP-105-policy-engine-core, PRP-108-agent-approval-gate-and-platform-control-actions]
wave: W32
branch: prp-131-cards-safety-records
allow_parallel: true
issues: []
---

# PRP-131: Model and agent cards, and safety-evaluation records

## Goal
Give every agent version and model deployment a card generated from facts the platform already holds, and give red-team and safety results a place to be recorded against the exact agent version they were run on. A card has one row per field, and every row shows where its value came from (catalog, evaluation, safety record, policy, risk register) or says "not recorded"; nobody types a free-text claim into a card. A safety record says who ran what, when, with which method and on which dataset, how many findings of each severity, and where the evidence lives; it is either imported from a tool the customer ran or derived from an internal evaluation result. It is for the steward who has to answer "what do we know about this agent" for an auditor, the reviewer in the approval flow, and the CI gate (PRP-129) that asks whether a safety evaluation exists. The product records results; it does not run attacks, grade them or certify that anything is safe. It runs in W32 on the contracts of PRP-110 and the register of PRP-127.

Out of scope: contracts (`SystemCard`, `SafetyEvaluationRecord` are PRP-110's); the AI-system register, risk tier and impact assessments (PRP-127); running red-team or safety tests (the customer's tooling does; the internal evaluation worker is unchanged); the CI check itself (PRP-129 reads `SafetyEvaluationReader`); policy rules about safety evidence (a rule kind would be a PRP-99/110 contract change, not built); per-person display of who ran a test beyond the pseudonymous principal the platform already stores; PostgreSQL implementation of the new store (PRP-90/PRP-91).

## Why
- The original ask names it: owner direction of 2026-11-16 is "the ultimate team AI governance and auditing tool" with all identified gaps planned. The design lists "model card", "agent card", "risk tier", "EU AI Act", "42001" as having no hits in code (`temp/audit/governance-core-design.md`, G-f), and `docs/PRD.md` NS-03 (recommendations and quality evaluation) and NS-08 (compliance alignment) carry no card or safety-result promise at all; this closes a gap, it does not restore a quoted line.
- Evaluation results attach to an AgentVersion or ModelDeployment (`packages/contracts/schemas/evaluation/v1/evaluation-result.schema.json`, `subject_id`), but `safety` is only one score dimension of a judged run (same file, the dimension enum) and there is no red-team or safety-result type; the evaluation API is read-only (`services/api/neurosphere_api/evaluation/router.py:61-110`, two `GET` routes and the quality read).
- The store port that results go through is `EvaluationStore` (`packages/core/neurosphere_core/evaluation/store.py:109-190`); it holds judged results, calibrations, drift alerts and sampling coverage, nothing about an externally run attack suite.
- The data a card needs already exists in separate places: catalog entities and edges, `AgentVersion.approval` (PRP-99), evaluation results, policy violations (PRP-105), the AI-system register and its determinations (PRP-127). Nothing assembles them for one subject, and PRP-110 already defines the shape (`SystemCard` with per-field `source_kind` and `source_ref`, `SafetyEvaluationRecord`).
- A card with free-text claims would repeat the demo-material trap `CLAUDE.md` warns about: the platform must not assert safety, compliance or authorization it has not measured ("Do not claim FedRAMP authorization, ATO, compliance parity").

## Acceptance criteria
- [ ] Given an agent version with an owner, a semver, linked model deployments and tools, data sources and an approval state, When `GET /api/v1/cards/domains/{domain}/agent-versions/{id}` runs, Then it returns a `SystemCard` whose every field carries `source_kind` and `source_ref` (an entity id, an evaluation id, a record id or a determination id), and a field with no source is `value: null` with `source_kind: not_recorded`.
- [ ] Given the same subject and the same stored facts, Then two calls return identical `fields` and the same `export_sha256`; given a changed fact (a new approval, a new safety record) the hash changes.
- [ ] Given a reader whose scope excludes a source (an evaluation in another domain, a risk system they cannot read), Then that field shows `not_recorded` and the card carries a `scope_note`; no field reveals that an out-of-scope fact exists.
- [ ] A card never states a verdict: the risk-tier field reads "recorded by <pseudonymous person> on <date> against questionnaire <template> <version>: <tier as recorded>"; evaluation fields show the judge version, calibration state and uncertainty exactly as the quality API does; the page and export carry the line "This card lists recorded facts. NeuroSphere does not assess, certify or guarantee safety, compliance or fitness for use."
- [ ] Given a steward holding `catalog.curate` in the domain, When they `POST /api/v1/evaluation/safety/domains/{domain}/subjects/{subject_id}/records` with a method, attack categories, performance time, findings by severity (counts or unknown), a pass flag or unknown, evidence pointers and an optional artifact SHA-256, Then a `SafetyEvaluationRecord` is stored with server-set `recorded_by` and `recorded_at`, an audit record is written, and the record appears on the subject's card; a second post with the same idempotency key is a no-op.
- [ ] Unknown stays unknown: a severity count the importer did not supply is `null`, never 0; `passed` is `null` unless the tool reported it; a card shows "not reported" for them.
- [ ] No attack prompt, model output or other content is accepted or stored: the request has no text field, evidence is pointers only (a URL on an allowed scheme or an artifact id), a pointer containing a secret-shaped string or a control character is refused, and the stored record, audit payload and card export contain no free text beyond the bounded tokens of the contract.
- [ ] Given an internal evaluation result with a `safety` score dimension, When a steward calls `POST .../records/from-evaluation/{evaluation_id}`, Then a record with `origin: internal`, the method `content_safety_eval`, the dataset id and version and a pointer to that evaluation id is created from stored facts only (no copy of scores that could drift).
- [ ] Given a safety record for subject S, Then `SafetyEvaluationReader.latest_for(scope, S)` returns it (and `None` plus a reason when none exist) for PRP-129 and PRP-108; this PRP does not edit either.
- [ ] Reading a card needs `data.read` in the domain; exporting it (JSON or Markdown) needs `data.export` and writes an `card.export` audit record carrying ids and the hash only; recording needs `catalog.curate`; viewers, auditors, other-domain stewards and expired users are refused with a denial record.
- [ ] The card page shows a source link per field, the "recorded, not assessed" line, the safety table with who, when, method and dataset, and passes axe in light, dark and high contrast; no string says "safe", "compliant" or "certified".
- PRP exit: touched suites, `tests/security/authz`, ruff, pyright, `validate_planning.py` and the frontend tests pass; PR open with CI green; `services/api/openapi.json` regenerated.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|---|---|---|
| 1 | Store cards or generate them | Stored documents; generated on demand | Generated on demand from current facts; the export carries a hash so a later difference is detectable. Nothing is stored except safety records |
| 2 | Free-text sections ("limitations", "intended use") | Editable on the card; only from recorded facts | Only recorded facts. `intended_use` comes from the AI-system register entry (PRP-127) and the catalog `description`, both customer-authored and shown as such |
| 3 | Safety record contract | New contract here; PRP-110's `SafetyEvaluationRecord` | PRP-110's. PRP-110 adds an optional `dataset` {id, version} to `SafetyEvaluationRecord` (it is PRP-110 Interfaces provided); this PRP uses it. Fallback only if the merged contract lacks it: an `evidence_refs` pointer `dataset:<id>@<version>` that the card reads too, and the correction request to PRP-110 is recorded |
| 4 | Who may record | New permission; `catalog.curate` | Decided by the owner 2026-11-16 (GD-39): recording a safety evaluation reuses `catalog.curate`; no `safety.record` permission. Here: in the domain (stewards), so no new permission or role test change; the owner may want a separate `safety.record` later |
| 5 | Import format | Parse vendor report formats; structured JSON only | Structured JSON in the request body only. No vendor report parser (formats are UNVERIFIED and would need a verification file per tool) |
| 6 | What a record may contain | Findings text; counts and pointers | Counts, categories (tokens), evidence pointers and an artifact hash only; red-team text can contain harmful or personal content |
| 7 | Cards for non-versions | Agent only; agent version, agent and model deployment | AgentVersion and ModelDeployment cards; an `Agent` id resolves to its current version (`current_version_id`) and says so on the card |
| 8 | Safety evidence in the approval gate | Edit PRP-108; expose a reader | Expose `SafetyEvaluationReader`; PRP-108 and PRP-129 consume it. This PRP does not make safety evidence mandatory anywhere |
| 9 | Where the store lives | Reuse `evaluation_results`; new container | New container `safety_evaluation_records` (partition customer and domain), Tier-1 stores files, because the shapes differ and the evaluation store has no record-type field |

## Context manifest

### Files to read first
- `packages/core/neurosphere_core/evaluation/store.py:58-110,217-260` - `EvaluationStore`, in-memory twin, conflict error, page types (the pattern for the new store).
- `packages/core/neurosphere_core/evaluation/cosmos_store.py` - Cosmos twin and idempotent put.
- `packages/contracts/schemas/evaluation/v1/evaluation-result.schema.json` - `subject_id`, `dataset`, `judge`, `scores`, `calibration`, the `safety` dimension.
- `services/api/neurosphere_api/evaluation/router.py`, `models.py`, `quality.py` - how scores are shown with uncertainty; the audited read and scope rules to copy.
- `packages/core/neurosphere_core/catalog/protocol.py` - `get_entity`, `list_edges`, `CatalogRepository` for the facts.
- `PRPs/backlog/PRP-110-governance-contracts-b.md` ("Interfaces provided": `SafetyEvaluationRecord`, `SystemCard`) and `PRP-99-governance-contracts-a.md` (`AgentVersionApproval`).
- `PRPs/backlog/PRP-127-ai-system-register-tiering-and-impact-assessments.md` - `RiskRegisterReader`.
- `PRPs/backlog/PRP-105-policy-engine-core.md` - `ViolationStore.list` (open violation counts on the card).
- `services/api/neurosphere_api/authz/read_audit.py:176-195` - `audited_read` for the export.
- `packages/core/neurosphere_core/stores/containers.py:138-150` - how a container is declared.

### Interfaces consumed
- PRP-110: `neurosphere_contracts.evaluation.v1.safety_evaluation_record.SafetyEvaluationRecord`, `neurosphere_contracts.risk.v1.system_card.SystemCard` (field names read from the generated bindings first), `RegistrationCheckResponse` check name `safety_evaluated` (consumed by PRP-129, not here).
- PRP-99: `AgentVersion.approval` (`AgentVersionApproval`).
- PRP-127: `RiskRegisterReader.systems_containing(entity_id, scope)`, `.latest_determination(system_id)`, `.latest_assessment(system_id)`.
- PRP-105: `ViolationStore.list(filters, page)` scoped by domain.
- PRP-108: approval state is read from the entity (`AgentVersion.approval`); no call into its handlers.
- Shipped: `EvaluationStore.results`, `CatalogRepository`, `run_audited_mutation`, `audited_read`, `RouterRegistry`, the optional-component builder pattern (`runtime/builders/__init__.py`).

### Interfaces provided
- Core `neurosphere_core.evaluation.safety` (new): `SafetyEvaluationStore` protocol with `InMemorySafetyEvaluationStore` and `CosmosSafetyEvaluationStore`; `SafetyEvaluationReader.latest_for(scope, subject_id)` and `.list_for(scope, subject_id, page)`; `record_from_evaluation_result(result, recorded_by, now)`.
- Core `neurosphere_core.cards` (new): `CardBuilder.build(scope, domain, subject_id) -> SystemCard`, `CARD_TEMPLATE_VERSION`, field catalogues for agent version and model deployment, `render_markdown(card)`.
- Container `safety_evaluation_records`; app state `app.state.safety_evaluations` and `app.state.card_builder`; optional components `safety_evaluations` and `cards`.
- Routes: `/api/v1/evaluation/safety/domains/{domain}/subjects/{subject_id}/records` (`GET` list, `POST` record), `.../records/from-evaluation/{evaluation_id}` (`POST`); `/api/v1/cards/domains/{domain}/agent-versions/{id}`, `/model-deployments/{id}` (`GET`), each with `?format=json|markdown` for export.
- Audit operations `safety.record`, `safety.record_from_evaluation`, `card.export`.
- Frontend `frontend/src/features/cards/` (`CardPage`, `SafetyRecordsTable`, `RecordSafetyDialog`), routes under `/cards/...`; mock handlers `frontend/tests/mock-api/features/cards.ts`.

### Patterns to match
- Idempotent in-memory and Cosmos store pair: `evaluation/store.py:217-260` and `evaluation/cosmos_store.py`.
- Scope-filtered read route that never distinguishes absent from out of scope: `services/api/neurosphere_api/evaluation/router.py:61-110`.
- Audited mutation: `packages/core/neurosphere_core/audit/repository.py:247-270` (`run_audited_mutation`), PRP-41's admin routes.
- Uncertainty display: `services/api/neurosphere_api/evaluation/quality.py`.
- Container declaration: `stores/containers.py:138-150`; compose and Bicep mirrors, as PRP-72 does for `recommendation_feedback`.

### Gotchas
- Cards read many sources; each read must use the caller's `IdentityScope`, never a worker scope. A broad scan is bounded (edge counts, result counts) and the card says `truncated` when a bound is hit.
- `EvaluationResult` scores are never shown without judge version, calibration state and uncertainty (`evaluation/__init__.py` docstring); copy that rule into the card field values rather than a bare number.
- Unknown is null, never 0 (telemetry and ledger rule); a missing severity count renders "not reported".
- Evidence pointers are the only free-ish strings: validate scheme (`https`, or an opaque artifact id token), length and no secret shapes (`tests/contracts/validators.py::check_secret_free_text` is the pattern from PRP-99).
- The PRP-110 contract names are from planning text; read the generated bindings and use the real names. If `SafetyEvaluationRecord` or `SystemCard` lack a needed field, stop and report; this PRP may not edit contracts.
- Adding a builder module can break tests that pin `default_builders` order (`services/api/tests/runtime_api/test_readiness.py`, `runtime_gateway_builder/test_gateway_builder.py`, `runtime_data/data_helpers.py`): list the line changes in the completion note and apply them.
- New test directories get unique names: `packages/core/tests/safety_records`, `packages/core/tests/system_cards`, `services/api/tests/cards_api`.
Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - packages/core/neurosphere_core/cards/**
  - packages/core/neurosphere_core/evaluation/safety/**
  - packages/core/tests/safety_records/**
  - packages/core/tests/system_cards/**
  - services/api/neurosphere_api/cards/**
  - services/api/neurosphere_api/evaluation/safety/**
  - services/api/neurosphere_api/runtime/builders/cards.py
  - services/api/tests/cards_api/**
  - tests/security/authz/test_cards_and_safety.py
  - frontend/src/features/cards/**
  - frontend/tests/mock-api/features/cards.ts
  - frontend/tests/e2e/cards/**
  - docs/runbooks/cards-and-safety-records.md
tier1:
  - packages/core/neurosphere_core/stores/containers.py
  - infra/compose/cosmos-containers.json
  - infra/demo/modules/cosmos-data.bicep
tier2_appends:
  - services/api/neurosphere_api/routers.py
  - services/api/neurosphere_api/runtime/builders/__init__.py
  - services/api/neurosphere_api/runtime/status.py
  - services/api/neurosphere_api/authz/routes.py
  - services/api/tests/authz/test_route_inventory.py
  - services/api/tests/authz/test_startup_route_check.py
  - services/api/tests/runtime_routes/manifest_calls.py
  - services/api/tests/runtime_api/test_readiness.py
  - tests/integration/real_stack/test_manifest_routes.py
  - frontend/src/app/appRoutes.ts
  - frontend/src/app/route-manifest.json
  - frontend/tests/mock-api/features/index.ts
  - frontend/tests/e2e/a11y/route-samples.ts
  - mkdocs.yml
must_not_touch:
  - packages/contracts/**
  - packages/core/neurosphere_core/evaluation/store.py
  - packages/core/neurosphere_core/evaluation/cosmos_store.py
  - packages/core/neurosphere_core/risk/**
  - packages/core/neurosphere_core/governance/**
  - packages/core/neurosphere_core/catalog/**
  - services/api/neurosphere_api/evaluation/router.py
  - services/api/neurosphere_api/runtime/builders/data.py
  - services/workers/**
```

## Implementation blueprint

Parallelization: items 1 and 3 [P] share no file; item 2 needs 1; item 4 needs 1 to 3; item 5 needs 4; item 6 last.

### Item 1 - Safety record store  [P]
- Deliverable: `evaluation/safety/` with `models.py` (re-export of the generated `SafetyEvaluationRecord`, request model without any text field, idempotency key), `store.py` (`SafetyEvaluationStore`, in-memory twin), `cosmos_store.py`, `reader.py` (`SafetyEvaluationReader`), `from_evaluation.py` (`record_from_evaluation_result`); containers `safety_evaluation_records` and, for PRP-134, `product_usage` (partition `/customer_id`, per-document TTL) in the three Tier-1 files, because this PRP is the only W32 stores owner.
- Owned files: `packages/core/neurosphere_core/evaluation/safety/**`, `packages/core/tests/safety_records/**`, the three Tier-1 files.
- Must NOT touch: `evaluation/store.py`, contracts.
- Depends on: PRP-110 merged.
- Acceptance criteria: put is idempotent by record id and a differing re-put is a conflict; scope filtering by customer and domain; `latest_for` orders by `performed_at`; unknown counts stay null; a record built from an evaluation result carries a pointer, not copied scores; the container exists in compose and Bicep.
- Tests: `packages/core/tests/safety_records/test_store.py`, `test_reader.py`, `test_from_evaluation.py`, and the container-declaration test that already compares `containers.py` with compose and Bicep.
- Pattern references: `evaluation/store.py:217-260`, `evaluation/cosmos_store.py`.

### Item 2 - Recording API
- Deliverable: `services/api/neurosphere_api/evaluation/safety/{router,models,service,dependencies}.py` implementing the three routes with `catalog.curate` for writes and `data.read` for reads, server-set `recorded_by` and `recorded_at`, evidence pointer validation, `run_audited_mutation` for writes.
- Owned files: `services/api/neurosphere_api/evaluation/safety/**`, `services/api/tests/cards_api/test_safety_routes.py`.
- Must NOT touch: `evaluation/router.py`, `evaluation/dependencies.py`.
- Depends on: item 1.
- Acceptance criteria: the record, unknown, no-content and from-evaluation criteria; a subject in another domain or an unknown subject is 404 with no distinction; audit payloads hold ids and reason codes only.
- Tests: `services/api/tests/cards_api/test_safety_routes.py`, `test_evidence_pointers.py`.
- Pattern references: `evaluation/router.py:61-110`, PRP-41 admin routes.

### Item 3 - Card builder  [P]
- Deliverable: `cards/` with `fields.py` (closed field catalogues for agent version and model deployment, each field naming its source function and `source_kind`), `sources.py` (small read ports over `CatalogRepository`, `EvaluationStore`, `SafetyEvaluationReader`, `ViolationStore`, `RiskRegisterReader`, all optional so a missing plane yields `not_recorded`), `builder.py` (`CardBuilder.build`, deterministic ordering, `export_sha256` over canonical JSON, `scope_note`, `truncated`), `markdown.py` (`render_markdown`), the disclaimer constant.
- Owned files: `packages/core/neurosphere_core/cards/**`, `packages/core/tests/system_cards/**`.
- Must NOT touch: `catalog/**`, `risk/**`, `governance/**` (read through their ports only).
- Depends on: PRP-110, PRP-127, PRP-105 merged (ports and names).
- Acceptance criteria: the card, hash, scope and no-verdict criteria; with every source absent the card has only `not_recorded` fields and still builds; the risk-tier wording is exactly the recorded determination.
- Tests: `packages/core/tests/system_cards/test_builder.py`, `test_scope_and_unknown.py`, `test_markdown_export.py`, `test_no_verdict_words.py` (a fixed word list over every rendered string).
- Pattern references: `evaluation/quality.py` (uncertainty text), `catalog/protocol.py` read methods.

### Item 4 - Card API and composition
- Deliverable: `services/api/neurosphere_api/cards/` router for the two card routes and the export (`data.export`, `audited_read`-style audit `card.export`); builder module `runtime/builders/cards.py` (`BUILDER`, optional components `safety_evaluations` and `cards`, backend `cosmos|memory` with memory only under `NS_ENV=local`) binding `app.state.safety_evaluations` and `app.state.card_builder` from the catalog, evaluation, risk and policy planes already on `app.state` (absent plane means that source is `not_recorded`).
- Owned files: `services/api/neurosphere_api/cards/**`, `runtime/builders/cards.py`, `services/api/tests/cards_api/{test_card_routes,test_cards_builder}.py`, the pinned-order tests listed in Gotchas (Tier-2 lines).
- Must NOT touch: `runtime/builders/data.py`.
- Depends on: items 1 to 3.
- Acceptance criteria: the permission and export criteria; the readiness status shows both components; with Cosmos unavailable they report disabled with a reason code and the rest of the app boots.
- Tests: the two files above plus `services/api/tests/runtime_api`, `runtime_routes`, `runtime_data`.
- Pattern references: `runtime/builders/edge.py:17-27`, PRP-127's `runtime/builders/risk.py`.

### Item 5 - Authorization and no-content negative suite
- Deliverable: ABAC cases for every route and denial dimension (viewer, auditor, other-domain steward, expired user, wrong customer) and a leak test that records safety data with canary strings in every field a client could abuse and greps stored documents, audit records, logs and exports for them.
- Owned files: `tests/security/authz/test_cards_and_safety.py`.
- Must NOT touch: shared harness files except additive helpers.
- Depends on: item 4.
- Acceptance criteria: every route has a deny case per dimension; no canary reaches any output.
- Tests: `tests/security/authz`.
- Pattern references: `tests/security/authz/test_api_paths.py`, PRP-41's secrecy suite.

### Item 6 - Frontend
- Deliverable: card page (field table with source links and the recorded-not-assessed line), safety table (who, when, method, dataset, counts), record dialog and from-evaluation action for stewards, export buttons, strings in one `strings.ts`, mock handlers, Playwright and axe samples.
- Owned files: `frontend/src/features/cards/**`, `frontend/tests/mock-api/features/cards.ts`, `frontend/tests/e2e/cards/**`.
- Must NOT touch: other features.
- Depends on: item 4 (OpenAPI types).
- Acceptance criteria: the page criterion; keyboard-complete dialog; a banned-word test over the strings file.
- Tests: `pnpm --filter frontend test`, `pnpm --filter frontend lint`, `pnpm --filter frontend typecheck`, the cards e2e.
- Pattern references: `frontend/src/features/finops/` (feature layout), `frontend/src/features/evaluations/`.

### Item 7 - Integration and close-out
- Deliverable: Tier-2 appends, runbook (what a card is and is not, recording and importing, evidence pointer rules, the dataset convention), `openapi.json` and docs regeneration, changelog fragment `changelog.d/PRP-131-model-and-agent-cards-and-safety-evaluation-records.md`, completion note including the PostgreSQL follow-up for PRP-90/91 and, only if the fallback was used, the correction request to PRP-110 (dataset field).
- Owned files: Tier-2 lines, the runbook, this PRP file, Tier-3 files per reference section 6.
- Depends on: items 1 to 6.
- Acceptance criteria: gates pass; CI green.

## Validation gates
```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q packages/core/tests/safety_records packages/core/tests/system_cards services/api/tests/cards_api services/api/tests/runtime_api services/api/tests/runtime_routes services/api/tests/runtime_data services/api/tests/authz tests/security/authz services/api/tests/test_openapi_drift.py tests/docs/test_reference_coverage.py tests/docs/test_nav_allowlist.py
pnpm --filter frontend test
pnpm --filter frontend lint
pnpm --filter frontend typecheck
python scripts/prp_status.py --check
python scripts/validate_planning.py
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```

## Migration and rollback
New container only; no data migration. Rollback: disable the two optional components (`NS_CARDS_ENABLED=false`, default true, reports disabled) or revert; stored safety records are inert documents. The container must exist in IaC before hosted use (Bicep mirror in item 1).

## Live and open gates
None run here: in-memory twins and, locally, the Cosmos emulator. The hosted card page is covered by PRP-82's signed-in smoke once the nav entry exists; nothing live is required. No paid call.

## NOT building
Running red-team or safety tests; grading, scoring or certifying safety; a "safe" or "compliant" label anywhere; free-text card sections; storing attack prompts, model outputs or findings text; vendor report parsers; a safety evidence requirement in the approval gate or the CI check (they may read the reader); a per-person ranking of who recorded results; PDF export; EU AI Act or ISO conformity statements (PRP-128 maps identifiers as an evidence aid only).

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [ ] All clarification questions are decided, not guessed (rows 3 and 4 are ASSUMPTIONS for plan approval)

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
- Date, PR:
- Deviations:
- Descoped items:
- OPEN gates:
- Env vars for the operator:
- Follow-up issues:
