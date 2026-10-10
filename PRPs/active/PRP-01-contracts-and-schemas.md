---
name: prp-01-contracts-and-schemas
status: active
review: required
created: 2026-10-08
model: opus
phase: 0
ns: NS-01, NS-02, NS-03, NS-04, NS-05, NS-06, NS-07, NS-08, NS-09, NS-10
depends_on: PRP-00
wave: W1
absorbs: P0.2 contracts
---

# PRP-01: Contracts and schemas

## Goal

Ship the versioned JSON Schema contracts that every later PRP imports: telemetry envelope, cost record, catalog entities and relations, canonical IDs, action intent and approval, audit record, identity scope, structured query, chart plan, recommendation, evaluation result, deployment manifest, capability matrix entry, connector manifest and the error taxonomy. JSON Schema (draft 2020-12) under `packages/contracts/schemas/` is the source of truth; Pydantic v2 and TypeScript types are generated from it, committed, and drift-checked in CI. The audience is every implementer of PRP-02 onward, who must build against these types rather than invent shapes. It runs now because PRP.md section 3 says "Contracts before implementations", and because a wrong field here forces refactoring in all 26 downstream PRPs; that risk is why this PRP uses Opus and requires review.

Requirement text fulfilled, quoted from `docs/PRD.md`:

> Event envelope: event_id, schema_version, event_time, ingestion_time, cloud, customer_id, domain_id, source_id, external_agent_id, canonical_agent_id when resolved, request_id, trace_id, span_id, parent_span_id, provider, model/version, environment, outcome, duration, token breakdown, data-source references, classification and sampling metadata. Missing fields remain null/unknown, never zero by default. (NS-01)

> Cost records distinguish estimated vs invoiced spend, currency, price version/effective date, cached tokens, retries, compute/PTU/reservation allocation and license/seat costs. (NS-01)

> Versioned entities: Person/pseudonymous principal, Agent, AgentVersion, ModelDeployment, GroundingSource/DataAsset, Tool, Service, Domain, Owner, Policy, Recommendation and RunReference. Stable cloud/customer/source-qualified IDs resolve collisions and agent aliases. (NS-02)

> Relations include INVOKES, DELEGATES_TO, USES_MODEL, READS, WRITES, GROUNDED_BY, OWNED_BY, DEPENDS_ON and SUPERSEDES. Every edge has provenance, evidence IDs, confidence, first/last observation, validity interval and asserted/inferred/curated status. (NS-02)

> Action states: drafted -> validated -> awaiting_confirmation -> awaiting_approval -> executing -> succeeded/failed/rolled_back/expired. Intent contains actor, target/version, proposed diff, prerequisite results, evidence, confirmation hash/expiry and idempotency key. (PRP.md section 3)

> Error taxonomy includes unauthorized/forbidden, unavailable capability, stale version, rate limit, invalid schema and transient dependency failure. All APIs include correlation ID, pagination and bounded budgets. (PRP.md section 3)

Also binding from PRP.md section 3: IdentityScope is derived server-side; chart plans are "a validated Vega-Lite subset with no expressions, signals or external data"; query builders accept "structured allowlisted filters, not model-generated executable query text". NS-03 (Recommendation, EvaluationResult), NS-04 (approval states: pending, assigned, approved, rejected, expired, escalated, executed, failed), NS-05 (viewport budgets), NS-06 (chart and query plans), NS-07 (DeploymentManifest, CapabilityMatrixEntry), NS-08 (roles, scope), NS-09 (ConnectorManifest) and NS-10 (schema docs) are covered at schema level only; behaviour belongs to the later PRPs.

## Acceptance criteria

- [ ] Item 1: Given a telemetry event missing `token breakdown`, `duration` or `model/version`, when deserialized, then the field is null or `unknown`, never 0; `schema_version` is required; a CostRecord with `kind` `estimated` and no `price_version` is rejected.
- [ ] Item 2: Every relation schema requires `provenance`, `evidence_ids`, `confidence`, `first_observed`, `last_observed`, `validity`, `status` (asserted|inferred|curated); a canonical-ID corpus of at least 30 valid and 30 invalid strings passes the `cloud:customer:source:type:id` grammar test.
- [ ] Item 3: The action state machine is an allowlist of (from, to) pairs; a schema test shows every pair not on the list is rejected (for example `drafted -> executing`, `succeeded -> executing`, `expired -> awaiting_approval`).
- [ ] Item 4: `ChartPlan` rejects any `expr`, `signals`, `params`, data `url` or `values` from a non-inline source, and any mark outside the allowlist; `IdentityScope` has no field populated from request input; `StructuredQuery` carries mandatory budgets.
- [ ] Item 5: Each of the seven error codes (`unauthorized`, `forbidden`, `capability_unavailable`, `stale_version`, `rate_limited`, `invalid_schema`, `dependency_transient`) has an HTTP status and a `retryable` flag; `capability_unavailable` carries a `reason`.
- [ ] Item 6: Running the codegen script twice yields no diff; CI fails when regenerated output differs from the committed output; ADR-0004 states the `v1` directory layout and the additive-only rule.
- [ ] Item 7: `NO_NETWORK=1 uv run pytest tests/contracts -q` passes with no credentials; each schema has at least one valid and one invalid golden fixture and a Python and TS round trip.
- [ ] PRP exit: `verify-gates -Mode full` green; `python scripts/validate_planning.py` shows nothing for this file; the review pass confirms every field in the NS-01 envelope and every NS-02 entity and relation name above exists exactly once.

## Clarifications (decided)

| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| 1 | Model for this PRP (D6) | Sonnet; Opus | Opus. Risk is concentrated in contracts; review required. |
| 2 | Source of truth | JSON Schema; Pydantic first | JSON Schema 2020-12 under `packages/contracts/schemas/<area>/v1/*.schema.json`; Pydantic v2 (datamodel-code-generator) and TS (json-schema-to-typescript) are generated and committed. Nobody hand-edits generated files. |
| 3 | Where do generated files live | in-package; contracts dirs | `packages/contracts/python/` and `packages/contracts/ts/`, consumed through the uv and pnpm workspace members created by PRP-00. |
| 4 | Versioning policy | semver per schema; directory per major | `v1` directory per major. Within `v1` only additive, optional changes; removals or type changes need `v2`. `schema_version` is a required field on persisted and wire documents. Written down in ADR-0004. |
| 5 | Unknown versus zero | null; sentinel; 0 | Nullable fields default to null; enumerated `unknown` where a category is needed. Numeric 0 is only ever a measured zero. |
| 6 | Unknown extra properties | allow; forbid | `additionalProperties: false` on every object; generated Pydantic models set `extra="forbid"`. Extension points are explicit `attributes` maps limited to scalar values. |
| 7 | Canonical ID grammar | free text; structured | `cloud:customer:source:type:id` with `cloud` in {commercial, government}; segments lowercase `[a-z0-9._-]`, `id` may additionally contain `/` and `=`; no segment may contain `:`. Aliases are separate documents mapping alias to canonical ID. |
| 8 | Person representation | real identifiers; pseudonymous | Pseudonymous principal only: stable `principal_pseudonym`, no email or name fields in the Person schema. Re-identification is a policy-store concern, not a contract field. |
| 9 | Prompt and response bodies | field present; absent | Not in the base envelope. A separate optional `payload_ref` (pointer, classification, redaction state) exists; bodies are off by default (NS-01). |
| 10 | Edge `status` values | free; fixed | `asserted`, `inferred`, `curated`; plus `lock` object (locked, reason, expiry, actor). |
| 11 | Action state machine location | code; schema | Allowlist encoded as data in `packages/contracts/schemas/actions/v1/transitions.json` and tested; PRP-17 implements enforcement from it. |
| 12 | HITL states | reuse action states; separate | Separate enum for review items (pending, assigned, approved, rejected, expired, escalated, executed, failed) from NS-04; the action enum is the PRP.md section 3 list. |
| 13 | Chart plan grammar | full Vega-Lite; subset | Subset: allowlisted marks (bar, line, area, point, rect, text), encodings, inline `data.values` only with a row cap, no `expr`, `signals`, `params`, `datasets` by URL, transforms limited to an allowlist. Allowlist lives in the schema, not in prose. |
| 14 | Error envelope | RFC 9457 only; custom | RFC 9457 problem details plus `code` (taxonomy), `retryable`, `correlation_id`, optional `reason`, optional `retry_after_seconds`. |
| 15 | Pagination and budgets | per endpoint; shared | Shared `Page` and `Budget` definitions in `schemas/query/v1/`: cursor-based, `limit` max, `max_nodes`, `max_edges`, `max_depth`, `timeout_ms`. |
| 16 | Live gates | per PRP | None here. Offline only (D7 does not apply). |
| 17 | Capability matrix entry fields | decide in PRP-02; decide now | Contract fixed here, data in PRP-02: service, feature, cloud, region, sku, availability, ga_status, authorization_scope, source_url, observed_on, notes. Availability, GA and authorization are three separate fields. |

## Context manifest

### Files that matter

- `PRP.md` - section 3 is the contract text (action states, error taxonomy, scope, chart rule). Binding.
- `docs/PRD.md` - NS-01 envelope, NS-02 entity and relation lists, NS-03 recommendation and evaluation, NS-04 states, NS-06 plan rules, NS-07 deployment, NS-09 connectors.
- `docs/ARCHITECTURE.md` section 6 (data model and query safety) and the action and deployment diagrams.
- `docs/RESEARCH-AND-GATES.md` - G03, G08, G12 constraints on catalog design.
- `docs/DECISIONS-LOG.md` - D4, D6, D11.
- `docs/adr/0002-stack-pins.md` - jsonschema 4.26 (draft 2020-12), Pydantic 2.14, TypeScript 6.0.x.
- `pyproject.toml` (root) - ruff, pyright, pytest markers.
- `packages/contracts/python/pyproject.toml` and `packages/contracts/ts/package.json` - created by PRP-00 (items 1 and 2); this PRP fills them.
- `.claude/hooks/config.ps1` - gate commands; build gate is required after PRP-00.
- `scripts/validate_planning.py` - planning validator.
- `.env.example` - never read `.env`.

### Patterns to match

No product code exists yet, so these are rules, not file references.

- Pydantic v2 models with `model_config = ConfigDict(extra="forbid")`.
- FastAPI routers per module under `services/api/neurosphere_api/<module>/router.py`.
- Async Azure SDK clients from `packages/core/neurosphere_core/clients`.
- Error taxonomy exceptions from `neurosphere_core.errors` (PRP-05 implements them from the schema in item 5).
- Tests beside packages plus cross-package suites in `tests/` (contract tests live in `tests/contracts/`).
- `pytest.mark.live` and `pytest.mark.integration` markers (declared in root `pyproject.toml`).
- TypeScript strict with `@fluentui/react-components`; Vitest + Testing Library; Playwright under `frontend/tests/e2e`.

### Conventions

- ruff config in root `pyproject.toml`: line length 100, py312, `S` rules on; pyright standard.
- Conventional commits; owned-file discipline; schema file names `<name>.schema.json`; `$id` is a relative URI `https://neurosphere.invalid/schemas/<area>/v1/<name>.schema.json` (reserved-domain placeholder, never resolved).
- Evidence under `docs/evidence/<gate>/`; live scripts under `scripts/gates/` refuse without `NS_LIVE_APPROVED=1`.
- Field names are `snake_case`; enums are lowercase `snake_case` strings; timestamps are RFC 3339 UTC strings; durations are integer milliseconds; money is a decimal string plus ISO 4217 currency code (no floats).
- Forward slashes in every command.

### Gotchas

- Event Hubs has no DLQ: quarantine is an explicit container + replay CLI; checkpoints advance only after durable accept or quarantine. Metadata geo-DR copies neither payloads nor RBAC.
- `IdentityScope` is derived server-side; caller- or model-supplied `domain_id`/`customer_id` is ignored. Same scope object on REST, search, cache keys, exports, WebSocket, copilot tools, MCP.
- No LLM-generated SQL/Cypher/KQL/JS. Charts are a Vega-Lite subset (no `expr`, signals, external `url` data) rendered with `vega-interpreter` in a sandboxed iframe.
- Government is gated, not banned: disabled-with-reason from the capability matrix; separate endpoints (`login.microsoftonline.us`, `*.documents.azure.us`, `*.servicebus.usgovcloudapi.net`, `*.search.azure.us`). Never route Government data to Commercial.
- Fail closed: policy store outage returns 503. Privileged roles are scoped; no bypass.
- One action executor for button/chat/REST/MCP; same intent hash; permission and target version rechecked at execution; read-only connectors are advisory; no catalog-only pretend swaps.
- Costs: null/unknown never 0; estimated vs invoiced always distinct; projections cite price version. Provider billing freshness is not sub-10s.
- Catalog: raw events outside the graph; locks affect presented lineage not observations; traversals budgeted; ETag mismatch returns `stale_version`. Outbox is the projection baseline, not emulator change feed.
- Emulators: Event Hubs emulator lacks Entra, so producer identity is enforced at the ingest edge; Cosmos vNext emulator has no RU accounting, no sprocs/triggers/UDF, no range/composite/spatial indexes, so G03 emulator evidence is "bounded feasibility" only.
- `scripts/gates/*` refuse without `NS_LIVE_APPROVED=1`; missing live evidence is an open gate, never a skipped green test. No paid model calls in CI.
- No FedRAMP/ATO/parity claims. Availability, GA and authorization are separate matrix columns.
- Secrets via vault references; dev issuer only when `NS_ENV=local`; never read `.env`. Pseudonymize people; prompt/response bodies off by default; redact before archive and before any external transmission (judges, connectors).
- Hidden navigation is not authorization; the API must deny.
- Versions: Python 3.12, Node 24, TypeScript 6.0.x (not 7), Helm 4, MkDocs Material 9.7 (EOL 2026-11-05, evaluate Zensical), sigma 4 + graphology (never @cosmograph, CC-BY-NC), MCP SDK 2.x (spec 2026-07-28). See docs/adr/0002-stack-pins.md.
- CI contains no `|| true`; `scripts/validate_planning.py` fails if it does. Python is `python`, not `python3`.
- PRP-01 specific: JSON Schema cannot express every rule. Cross-field rules (estimated requires price version; edge requires evidence) use `if/then/required` or `allOf`; where a rule cannot be expressed, add a Python validator in the contract test suite and name it in the schema `description`. Do not silently drop the rule.
- PRP-01 specific: generators disagree on `oneOf` and `const`. Pin generator versions in `packages/contracts/scripts/` and test the generated Python and TS against the same golden fixtures; do not trust codegen output by inspection.
- PRP-01 specific: the Cosmos partition-key shape (domain plus shard) is not a contract concern here; do not encode storage layout in schemas. PRP-10 owns it after the G03 live run.
- PRP-01 specific: `IdentityScope` in the schema is output-only (a server-derived shape). There must be no request schema that accepts it. The schema test asserts no request body schema references it.
- PRP-01 specific: no `format: uri` fetching or `$ref` to remote URLs; all `$ref` are relative file refs so the suite runs with `NO_NETWORK=1`.

### External references

- JSON Schema 2020-12: https://json-schema.org/draft/2020-12 (not yet observed; verify at implementation). `jsonschema` 4.26 supports it (ADR-0002, 2026-10-08).
- Pydantic 2.14 and datamodel-code-generator: versions per ADR-0002 table (2026-10-08); record the generator pin in ADR-0004.
- json-schema-to-typescript: https://www.npmjs.com/package/json-schema-to-typescript (pin recorded in ADR-0004 once chosen).
- Vega CSP and `Function` constructor risk, basis for the chart subset: https://vega.github.io/vega/usage/#csp (retrieved 2026-10-08, `docs/RESEARCH-AND-GATES.md`).
- MCP spec 2026-07-28, relevant to `ConnectorManifest` interoperability and tool manifests: https://modelcontextprotocol.io/specification/versioning (2026-10-08).
- Event Hubs geo-DR caveats informing the quarantine fields: https://learn.microsoft.com/azure/event-hubs/event-hubs-geo-dr (2026-10-06).
- Azure Government endpoint suffixes used in `CapabilityMatrixEntry` examples: https://learn.microsoft.com/azure/foundry/concepts/foundry-azure-government (2026-10-06).
- RFC 9457 problem details: https://www.rfc-editor.org/rfc/rfc9457 (not yet observed; verify at implementation).

## Implementation blueprint

### Item 1 — telemetry-and-cost-schemas  [P]
- Deliverable: `TelemetryEvent` envelope with every NS-01 field (event_id, schema_version, event_time, ingestion_time, cloud, customer_id, domain_id, source_id, external_agent_id, canonical_agent_id nullable, request_id, trace_id, span_id, parent_span_id, provider, model and version, environment, outcome, duration_ms, token breakdown {input, output, cached, reasoning}, data_source_refs, classification, sampling metadata {rate, method, reason}); delegation, tool-call, retry, error and cancellation span kinds; optional `payload_ref`. `CostRecord` with `kind` (estimated|invoiced), `amount` and `currency`, `price_version`, `price_effective_date`, cached tokens, retries, allocation {compute, ptu, reservation, license_seat}, `dedupe_key`, `observation_source` (gateway|application|billing), `reconciliation` {coverage, variance}.
- Owned files (may edit): `packages/contracts/schemas/telemetry/`, `packages/contracts/schemas/cost/`.
- Must NOT touch: `packages/contracts/schemas/catalog/`, `actions/`, `audit/`, `scope/`, `query/`, `chart/`, `recommendations/`, `evaluation/`, `deployment/`, `connectors/`, `errors/` (sibling items 2 to 5); `packages/contracts/python/`, `packages/contracts/ts/`, `packages/contracts/scripts/` (item 6); `tests/contracts/` (item 7); root `pyproject.toml`; `docs/RESEARCH-AND-GATES.md`.
- Depends on: none
- Acceptance criteria:
  - Missing optional fields deserialize to null or `unknown`, never 0 (golden fixtures prove it for tokens, duration and cost).
  - `schema_version` is required on envelope and cost record.
  - Estimated cost without `price_version` is invalid; invoiced cost without a billing period is invalid.
  - `observation_source` and `dedupe_key` exist so PRP-07 can avoid double counting.
- Pattern references: PRD NS-01 text; conventions (money as decimal string, durations in ms).
- Tests to write: golden fixtures under `tests/contracts/fixtures/telemetry/` and `.../cost/` are written by item 7; this item adds in-folder `examples/` valid and invalid JSON for item 7 to consume.

### Item 2 — catalog-schemas  [P]
- Deliverable: entity schemas Person (pseudonymous principal), Agent, AgentVersion, ModelDeployment, GroundingSource/DataAsset, Tool, Service, Domain, Owner, Policy, Recommendation (reference form) and RunReference, each with canonical `id`, `version`, `etag`, lifecycle status, timestamps; relation schemas INVOKES, DELEGATES_TO, USES_MODEL, READS, WRITES, GROUNDED_BY, OWNED_BY, DEPENDS_ON, SUPERSEDES with provenance, evidence_ids, confidence, first_observed, last_observed, validity interval, status (asserted|inferred|curated) and lock; alias document; canonical ID grammar `cloud:customer:source:type:id` with a regex and corpus.
- Owned files (may edit): `packages/contracts/schemas/catalog/`.
- Must NOT touch: `schemas/telemetry/`, `cost/` (item 1); `actions/`, `audit/` (item 3); `scope/`, `query/`, `chart/`, `recommendations/`, `evaluation/` (item 4); `deployment/`, `connectors/`, `errors/` (item 5); generated dirs; `tests/contracts/`.
- Depends on: none
- Acceptance criteria:
  - Every edge requires provenance, evidence_ids (non-empty for inferred), status and confidence in [0,1]; an edge without them is invalid.
  - A curated lock requires reason and expiry; an override schema cannot remove a security-evidence reference.
  - The ID regex corpus (at least 30 valid, 30 invalid including colon injection and uppercase) passes.
  - Person schema has no email, name or free-text identity field.
- Pattern references: PRD NS-02; ARCHITECTURE section 6.
- Tests to write: `examples/` for item 7; the ID corpus file `packages/contracts/schemas/catalog/v1/id-corpus.json` is consumed by `tests/contracts/test_canonical_ids.py` (item 7).

### Item 3 — action-and-approval-schemas  [P]
- Deliverable: `ActionIntent` (actor, target and target_version, proposed_diff, prerequisite_results, evidence, confirmation_hash, confirmation_expires_at, idempotency_key, channel button|chat|rest|mcp, state), the state enum (drafted, validated, awaiting_confirmation, awaiting_approval, executing, succeeded, failed, rolled_back, expired), `transitions.json` allowlist, `ApprovalDecision` (reviewer, decision, reason, immutable timestamp, maker-checker fields), review-item state enum (pending, assigned, approved, rejected, expired, escalated, executed, failed), `AuditRecord` (before/after/denied kinds, actor, scope hash, correlation_id, previous_hash for chaining).
- Owned files (may edit): `packages/contracts/schemas/actions/`, `packages/contracts/schemas/audit/`.
- Must NOT touch: telemetry, cost (item 1); catalog (item 2); scope, query, chart, recommendations, evaluation (item 4); deployment, connectors, errors (item 5); generated dirs; `tests/contracts/`.
- Depends on: none
- Acceptance criteria:
  - Transitions are an allowlist of (from, to); every non-listed pair is rejected by a test that enumerates the full 9x9 matrix.
  - The confirmation hash definition lists exactly which fields are hashed (target, target_version, diff, expiry, actor) so button, REST and MCP can produce the same value.
  - `AuditRecord` has no update-capable field; `previous_hash` is required except for the chain head.
  - `idempotency_key` is required on every intent.
- Pattern references: PRP.md section 3 action states; PRD NS-04 and NS-06.
- Tests to write: `examples/` for item 7; the 9x9 matrix test lives in `tests/contracts/test_action_transitions.py` (item 7).

### Item 4 — query-chart-and-scope-schemas  [P]
- Deliverable: `IdentityScope` (output-only: principal, roles, allowed domains and resources, policy_version, derived_at, scope_hash), `StructuredQuery` (entity, allowlisted filters with typed operators, sort, time range, budgets, no free-text field), shared `Page` and `Budget` defs, `ChartPlan` as a Vega-Lite subset (see Clarification 13), `Recommendation` (kind, evidence window, coverage, uncertainty, prerequisites, projected estimate with price_version, owner, advisory flag), `EvaluationResult` (dataset, rubric and judge versions, scores with uncertainty, sampling coverage, calibration reference).
- Owned files (may edit): `packages/contracts/schemas/scope/`, `packages/contracts/schemas/query/`, `packages/contracts/schemas/chart/`, `packages/contracts/schemas/recommendations/`, `packages/contracts/schemas/evaluation/`.
- Must NOT touch: telemetry, cost (item 1); catalog (item 2); actions, audit (item 3); deployment, connectors, errors (item 5); generated dirs; `tests/contracts/`.
- Depends on: none
- Acceptance criteria:
  - `ChartPlan` rejects any `expr`, `signals`, `params`, `url` data, remote `$ref` or non-allowlisted mark or transform (negative fixtures for each).
  - No request schema in the whole contract set references `IdentityScope` (a test walks every schema).
  - `StructuredQuery` has mandatory `timeout_ms`, `limit` and `max_depth` or equivalent budget; no string field can carry query text.
  - `Recommendation` with a projected estimate and no `price_version` is invalid; a cold-start recommendation may omit score but must state `insufficient_evidence`.
- Pattern references: PRP.md section 3 (scope, chart plan); PRD NS-03, NS-06.
- Tests to write: `examples/` for item 7; the no-request-references-scope walker in `tests/contracts/test_scope_isolation.py` (item 7).

### Item 5 — deployment-and-error-schemas  [P]
- Deliverable: `DeploymentManifest` (cloud, regions, hosting profile aks|appservice, analytics backend fabric|synapse|databricks, per-service reuse|create|skip with owner consent flag and cost implication), `CapabilityMatrixEntry` (fields in Clarification 17), `ConnectorManifest` (name, version, capabilities, scopes, granularity, freshness, rate limits, credential refs by vault reference only, advisory flag, write support), error taxonomy schema with the seven codes.
- Owned files (may edit): `packages/contracts/schemas/deployment/`, `packages/contracts/schemas/connectors/`, `packages/contracts/schemas/errors/`.
- Must NOT touch: telemetry, cost (item 1); catalog (item 2); actions, audit (item 3); scope, query, chart, recommendations, evaluation (item 4); generated dirs; `tests/contracts/`; `packages/core/neurosphere_core/capabilities/` (PRP-02).
- Depends on: none
- Acceptance criteria:
  - Every error code has `http_status` and `retryable`: unauthorized 401, forbidden 403, capability_unavailable (4xx, not retryable, requires `reason`), stale_version 409, rate_limited 429 (retryable, `retry_after_seconds`), invalid_schema 422, dependency_transient 503 or 502 (retryable). Exact statuses are fixed in the schema and tested.
  - `ConnectorManifest` has no field that can hold a secret value; credentials are `vault_ref` strings only, validated by pattern.
  - `CapabilityMatrixEntry` keeps `availability`, `ga_status` and `authorization_scope` as three separate fields; a test rejects an entry that merges them.
  - `DeploymentManifest` cannot express routing Government data to Commercial (cloud is a single value per manifest; test).
- Pattern references: PRD NS-07, NS-09; PRP.md section 3 error taxonomy.
- Tests to write: `examples/` for item 7; error table test in `tests/contracts/test_error_taxonomy.py` (item 7).

### Item 6 — codegen-pipeline
- Deliverable: generation of Pydantic v2 models (datamodel-code-generator) into `packages/contracts/python/` and TypeScript types (json-schema-to-typescript) into `packages/contracts/ts/`; `packages/contracts/scripts/generate.py` driving both with pinned generator versions; a CI drift check that regenerates and fails on diff; ADR-0004 with the versioning policy.
- Owned files (may edit): `packages/contracts/python/` (except `pyproject.toml` fields owned by PRP-00 beyond adding the generated package), `packages/contracts/ts/`, `packages/contracts/scripts/`, `docs/adr/0004-contract-versioning.md`.
- Must NOT touch: any `packages/contracts/schemas/` file (items 1 to 5; report schema defects to their owner, do not patch); `tests/contracts/` (item 7); `.github/workflows/ci.yml` (add the drift check by invoking the script from an existing job only via a follow-up note to the PRP-00 owner, or add `.github/workflows/contracts.yml` as a new file if no existing job fits; record the choice); root `pyproject.toml`; `docs/RESEARCH-AND-GATES.md`.
- Depends on: items 1, 2, 3, 4, 5
- Acceptance criteria:
  - Generated Python models use `extra="forbid"` and import under `uv run python -c "import neurosphere_contracts"` (package name fixed in the stub by PRP-00).
  - `pnpm --filter ./packages/contracts/ts typecheck` passes under TypeScript 6.0.x strict.
  - Second run of `python packages/contracts/scripts/generate.py` produces an empty `git diff`.
  - ADR-0004 states: `v1` directories, additive-only within a major, how deprecation works, generator pins.
- Pattern references: ADR-0002 backend and frontend tables; conventions.
- Tests to write: `packages/contracts/scripts/test_generate.py` (idempotence and generator-pin check).

### Item 7 — contract-test-suite
- Deliverable: golden valid and invalid fixtures per schema, JSON Schema validation tests, Pydantic and TS round-trip tests, cross-schema walkers (scope isolation, no remote refs, every object forbids additional properties), ID corpus test, action transition matrix test, error taxonomy test.
- Owned files (may edit): `tests/contracts/`.
- Must NOT touch: anything under `packages/contracts/` (items 1 to 6); other `tests/` subfolders; CI workflows.
- Depends on: item 6
- Acceptance criteria:
  - `NO_NETWORK=1 uv run pytest tests/contracts -q` passes with no credentials and no sockets opened (socket-blocking fixture proves it).
  - Every schema has at least one valid and one invalid fixture; a walker fails if a schema lacks either.
  - TS round trip runs under `pnpm --filter ./packages/contracts/ts test`.
  - Adding a property to a schema without regenerating fails the suite (drift test).
- Pattern references: conventions; `pytest` markers (no `live` or `integration` here).
- Tests to write: `tests/contracts/test_schemas.py`, `test_roundtrip.py`, `test_canonical_ids.py`, `test_action_transitions.py`, `test_scope_isolation.py`, `test_error_taxonomy.py`, `test_no_remote_refs.py`, and fixtures under `tests/contracts/fixtures/`.

## Validation gates

```
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode fast    # per item
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full    # before merge
python scripts/validate_planning.py
```

Feature-specific commands:

```
python packages/contracts/scripts/generate.py
git diff --exit-code -- packages/contracts/python packages/contracts/ts
NO_NETWORK=1 uv run pytest tests/contracts -q
pnpm --filter ./packages/contracts/ts typecheck
pnpm --filter ./packages/contracts/ts test
```

No command here needs `NS_LIVE_APPROVED=1`; contracts are offline by definition.

## Live and open gates

| Gate | Effect of this PRP |
|---|---|
| G03 graph benchmark | Contracts avoid encoding storage layout; PRP-02 supplies emulator evidence, PRP-10 the live run. |
| G08 dependency and licence versions | Generator tools and their licences are added to ADR-0004 and picked up by the PRP-00 register. |
| G12 emulator parity | Not closed; no emulator behaviour is encoded in contracts. |

If a live item did not run, record it OPEN in the completion note and in docs/RESEARCH-AND-GATES.md; never report it as a skipped green test.

## NOT building

- Any API endpoint, repository, worker or UI that uses these schemas (PRP-05 onward).
- The capability matrix data and validator (PRP-02); only the entry contract is defined here.
- Cosmos container layout, partition keys, indexes (PRP-10 after the G03 live gate).
- Enforcement of the action state machine or confirmation hashing (PRP-17); only the allowlist and hash field list are defined.
- Chart rendering or server-side chart validation code (PRP-19); only the schema.
- GraphQL schemas (deferred by NS-09).
- Any claim of schema stability beyond `v1` rules in ADR-0004; "no future refactoring" is not promised.

## Definition of Ready check

- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [x] All clarification questions are decided, not guessed

## Completion note (filled at ship)

- Date:
- Merged commits:
- Deviations from blueprint and why:
- Descoped items:
- Schema list shipped (area, name, version):
- Open gates and follow-ups:
