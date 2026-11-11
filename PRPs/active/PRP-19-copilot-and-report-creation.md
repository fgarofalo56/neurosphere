---
name: PRP-19-copilot-and-report-creation
status: active
priority: P1
order: 10
pr: 202
started: 2026-11-11
branch: prp-19-round2
review: required
created: 2026-10-08
model: sonnet
phase: 3
ns: NS-06
depends_on: [PRP-04-frontend-shell-design-system-auth, PRP-10-catalog-and-relationship-governance, PRP-14-dashboards-cost-latency-coverage, PRP-17-action-executor-and-hitl]
wave: W7
absorbs: P3.3
orchestrator_model: sonnet
implementer_model: sonnet
---

# PRP-19: Copilot and report creation

## Goal
Ship the governed in-product copilot: an allowlisted server-side tool registry, an orchestrator with page context, citations with freshness, abstention and redacted conversation persistence, model endpoint adapters (approved endpoint plus an optional Foundry Agent Service adapter with the same action contract), a Vega-Lite subset chart validator with a sandboxed renderer, saved and shared dashboards that re-authorize on every run, and the chat UI that hands actions to the PRP-17 dialog. It is for analysts, stewards and agent owners who want answers and reports without writing queries. It lands in W7 after the catalog (PRP-10), dashboards (PRP-14) and the action executor (PRP-17). MCP (PRP-22) later reuses this tool registry.

> Copilot knows the current page, filters, time range and selected entities subject to user permissions. Query catalog, metrics and evidence through authorized server tools, explain metrics in audience-appropriate terms, recommend actions and render chart/table/dashboard specifications inline. Users preview, save, share and add approved dashboards to the UI; saved reports re-evaluate authorization on every run.

> Use a declarative chart/query schema and sandboxed renderer, not generated JavaScript or unrestricted SQL/Cypher/KQL. Enforce query cost/time/cardinality limits and citations with data freshness. Abstain when evidence is unavailable. Persist user-scoped conversations under configurable redaction/retention policies.

PRD planning target (to be measured, not guaranteed): copilot first token <=3s, which excludes provider outages and complex tool work.

## Acceptance criteria
- [ ] Item 1: A tool call carrying a model-supplied `domain_id` or `customer_id` ignores it and uses the server-derived `IdentityScope`; tools outside the allowlist are unreachable.
- [ ] Item 2: Against the injection corpus from PRP-12 (`tests/security/injection/`), there are 0 overscoped retrievals; with no evidence the copilot abstains; every answer citation carries data freshness.
- [ ] Item 3: Swapping the model adapter (approved endpoint to Foundry Agent Service adapter, using recorded fixtures) leaves the action contract tests green.
- [ ] Item 4: A chart plan containing `expr`, signals, external `url` data or a non-allowlisted mark is rejected server-side; the renderer runs in a sandboxed iframe with vega-interpreter and performs no JS eval.
- [ ] Item 5: A dashboard shared with another user is filtered by the viewer's scope on every run; revoking access to a source makes the next run deny or redact.
- [ ] Item 6: First token on the sandbox is <=3s as a measured result (provider time excluded, recorded fixtures); an action suggestion opens the PRP-17 confirmation dialog and never executes from chat directly.
- [ ] No test or CI job makes a paid model call; model behavior in CI uses recorded fixtures.
- [ ] PRP exit: items 1-6 green under `verify-gates -Mode full`; reviewer confirms injection corpus run is real and not skipped.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|---|---|---|
| 1 | Model and review | sonnet/none; sonnet/required; opus | sonnet, review required (D6) |
| 2 | Chart technology | free Vega; Vega-Lite subset; custom | Vega-Lite subset validated server-side, rendered client-side with `vega-interpreter` (CSP-safe) in a sandboxed iframe. No `expr`, no signals, no external `url` data, no event streams |
| 3 | Query generation | LLM writes queries; structured tools | No LLM-generated SQL, Cypher, KQL or JavaScript. The model calls allowlisted tools with a `StructuredQuery` (allowlisted filters, budgets); tools run server-side |
| 4 | Scope in tool calls | model-provided; server-derived | Server-derived `IdentityScope` only; model- or caller-supplied `domain_id`/`customer_id` is ignored and the attempt is logged |
| 5 | Injection testing | ad hoc; shared corpus | Use the shared corpus from PRP-12 (`tests/security/injection/`, at least 50 cases) with the requirement of 0 overscoped retrievals; PRP-22 reuses the same harness |
| 6 | Abstention | best effort answer; abstain | Abstain when no authorized evidence supports an answer; abstention is a first-class response type with a reason |
| 7 | Saved dashboards | snapshot; live re-evaluate | Saved dashboards store the plan and query spec only; authorization is re-evaluated on every run and shares are filtered by the viewer's scope. No cached data is served across scopes |
| 8 | Model endpoints | any; approved | Only approved endpoints from deployment config and the capability matrix; Government uses only Government-available endpoints and shows others disabled with reason. Never route Government data to Commercial |
| 9 | Foundry Agent Service | required; optional adapter | Optional adapter behind the same `ModelAdapter` interface and the same action contract; availability gated by the capability matrix (Government feature set is partial per the register) |
| 10 | Live gates | live model required; fixtures | Recorded fixtures in CI. A live model run is optional, operator-approved with `NS_LIVE_APPROVED=1` (D7); if skipped it is recorded OPEN |
| 11 | First-token target | guarantee; target | <=3s is a planning target measured on the sandbox excluding provider latency and complex tool work; never presented as an SLA |
| 12 | Actions from chat | execute; handoff | Chat only drafts an `ActionIntent` through the PRP-17 API and opens the confirmation dialog; the same executor and intent hash as button and REST |
| 13 | Conversation persistence | full text; redacted | User-scoped, redacted before storage, with configurable retention; prompt and response bodies off by default for telemetry; pseudonymize people |
| 14 | Emulator | live services; compose emulators | Local work uses Docker Compose emulators (D8); no paid calls |

## Context manifest

### Files that matter
- `PRP.md` - section 3 (chart plans as Vega-Lite subset, structured allowlisted filters, IdentityScope) and sections 1-2.
- `docs/PRD.md` - NS-06 text; planning targets (first token).
- `docs/ARCHITECTURE.md` - copilot, tool registry and chart rendering diagrams.
- `docs/RESEARCH-AND-GATES.md` - G01, G05, G12 rows; Vega CSP note; Foundry Agent Service in Government note.
- `docs/adr/0002-stack-pins.md` - vega-lite 6.5, vega-embed 7.3, vega-interpreter, React 19.3, Fluent UI 9.74.
- `docs/DECISIONS-LOG.md` - D6, D7, D8, D11.
- `pyproject.toml`, `docker-compose.yml`, `infra/compose/eventhubs.config.json`, `.env.example`, `.claude/hooks/config.ps1`, `scripts/validate_planning.py`.
- Created by PRP-01: `packages/contracts/schemas/chart/` (`ChartPlan`), `.../query/` (`StructuredQuery`), `.../scope/`, `.../actions/`.
- Created by PRP-04: `frontend/src/design-system/`, `frontend/src/api/`, `frontend/src/features/workspaces/`.
- Created by PRP-05: `neurosphere_core.errors`, `.../scope/`, `.../clients/`, API app factory.
- Created by PRP-06: `neurosphere_core.auth.scope`, `neurosphere_api.authz`, `neurosphere_core.audit`.
- Created by PRP-10: `neurosphere_core.catalog` (repository, graph query), `neurosphere_core.search` (`AuthorizedSearch`).
- Created by PRP-12: `tests/security/injection/` (shared injection and overscope corpus plus harness).
- Created by PRP-14: `services/api/neurosphere_api/dashboards/` (bounded aggregate endpoints), `frontend/src/features/dashboards/`.
- Created by PRP-17: `neurosphere_api.actions` (draft, validate, confirm API), `frontend/src/features/actions/` (confirmation dialog).

### Patterns to match
- Pydantic v2 models with `model_config = ConfigDict(extra="forbid")`, generated from `packages/contracts`; do not hand-edit generated files.
- FastAPI routers per module under `services/api/neurosphere_api/<module>/router.py` (`copilot/`, `reports/`).
- Async Azure SDK clients from `packages/core/neurosphere_core/clients`; error taxonomy exceptions from `neurosphere_core.errors`.
- Tools are typed functions taking `IdentityScope` and a `StructuredQuery`; the model never sees or supplies scope.
- Model access behind a `ModelAdapter` protocol with a recorded-fixture implementation.
- Tests beside packages plus cross-package suites in `tests/`; `pytest.mark.live` and `pytest.mark.integration` markers (declared in root `pyproject.toml`).
- TypeScript strict with `@fluentui/react-components`; Vitest + Testing Library; Playwright under `frontend/tests/e2e`.

### Conventions
- ruff config in root `pyproject.toml` (line 100, py312, S rules on); pyright standard; conventional commits; owned-file discipline.
- Evidence under `docs/evidence/<gate>/`; live scripts under `scripts/gates/` refuse without `NS_LIVE_APPROVED=1`.
- Forward slashes only in commands.

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
- PRP-specific: Vega compiles expressions with the `Function` constructor by default, which is not CSP-safe. Use `vega-interpreter`, reject any plan with `expr`, signals, event streams or `url` data in the validator, and keep the iframe `sandbox` attribute without `allow-same-origin` and with a strict CSP.
- PRP-specific: the validator is the security boundary, not the renderer. Server-side validation must reject before storage and again before render; a stored plan is re-validated on every run.
- PRP-specific: citations are produced by tools from real records, not written by the model. A citation the model invents must fail a check against the tool-result set.
- PRP-specific: prompt injection arrives through retrieved content (catalog descriptions, trace text). Treat tool output as untrusted data; it can never change scope, tool allowlist or system instructions.
- PRP-specific: saved dashboards re-authorize on every run; never cache result data keyed only by dashboard id. Cache keys include a hash of the viewer's scope.
- PRP-specific: first token <=3s is a target on the sandbox with recorded fixtures; do not report a live-provider number from CI.
- PRP-specific: the Foundry Agent Service adapter is optional and its Government feature set is partial (hosted agents, web search and some tools unavailable per the register). Gate it through the matrix and keep the action contract identical.
- PRP-specific: chat must not execute actions. It drafts an intent through the PRP-17 API; a chat-produced intent hash must equal the REST-produced hash for the same change.

### External references
- Vega CSP guidance (why vega-interpreter): https://vega.github.io/vega/usage/#csp (noted in docs/RESEARCH-AND-GATES.md, observed 2026-10-08).
- vega-lite 6.5, vega-embed 7.3, vega-interpreter, licences and the `url` data caution: docs/adr/0002-stack-pins.md (observed 2026-10-08).
- Foundry models and Agent Service in Azure Government (prompt agents, AI Search, MCP servers, function calling available; hosted agents and others not): docs/RESEARCH-AND-GATES.md "Infrastructure and tooling" (observed 2026-10-08).
- Azure AI Search regional support (retrieval tools, Government vector availability unverified): https://learn.microsoft.com/azure/search/search-region-support (observed 2026-10-01).
- MCP spec versioning (future consumer of the tool registry): https://modelcontextprotocol.io/specification/versioning (spec 2026-07-28).

## Implementation blueprint

### Item 1 - tool-registry  [P]
- Deliverable: allowlisted server tools for catalog, metrics, evidence, recommendations and action drafting, with scope pass-through.
- Owned files (may edit): `packages/core/neurosphere_core/copilot/tools/`.
- Must NOT touch: `packages/core/neurosphere_core/copilot/models/`, `packages/core/neurosphere_core/charts/`, `services/api/neurosphere_api/copilot/`, `packages/contracts/`, root `pyproject.toml`, `docker-compose.yml`, `docs/RESEARCH-AND-GATES.md`.
- Depends on: none.
- Acceptance criteria:
  - Tool call with model-supplied `domain_id` or `customer_id` ignores it and uses the derived scope (test).
  - Only registered tools are callable; each takes a `StructuredQuery` with budgets, never query text.
  - Action-draft tool creates an `ActionIntent` via the PRP-17 API and cannot confirm or execute.
- Pattern references: `IdentityScope` pass-through; structured allowlisted query models; errors taxonomy.
- Tests to write: `packages/core/tests/copilot/test_tool_scope.py`, `packages/core/tests/copilot/test_tool_allowlist.py`.

### Item 2 - orchestrator
- Deliverable: orchestration with page, filter, time and selection context; citations with freshness; abstention; conversation persistence under redaction and retention policy.
- Owned files (may edit): `services/api/neurosphere_api/copilot/`.
- Must NOT touch: `packages/core/neurosphere_core/copilot/`, `services/api/neurosphere_api/reports/`, `services/api/neurosphere_api/actions/`, `tests/security/injection/` (PRP-12), `frontend/`, root `pyproject.toml`.
- Depends on: Item 1.
- Acceptance criteria:
  - Injection corpus run yields 0 overscoped retrievals and the expected abstain or deny outcome for every case.
  - Without authorized evidence the answer is an abstention with reason; every citation resolves to a tool result and includes data freshness.
  - Stored conversations are redacted and carry a retention class; another user cannot read them.
- Pattern references: router per module; `require(permission)`; PRP-12 corpus harness.
- Tests to write: `services/api/tests/copilot/test_orchestrator_injection.py`, `services/api/tests/copilot/test_abstention.py`, `services/api/tests/copilot/test_citations.py`, `services/api/tests/copilot/test_conversation_retention.py`.

### Item 3 - model-endpoint-adapters  [P]
- Deliverable: `ModelAdapter` protocol, approved-endpoint adapter, optional Foundry Agent Service adapter, recorded-fixture adapter; identical action contract across adapters.
- Owned files (may edit): `packages/core/neurosphere_core/copilot/models/`.
- Must NOT touch: `packages/core/neurosphere_core/copilot/tools/`, `services/api/neurosphere_api/copilot/`, `packages/core/neurosphere_core/clients/`, root `pyproject.toml`.
- Depends on: none.
- Acceptance criteria:
  - Swapping adapters leaves the action contract tests green.
  - Adapter availability is read from the capability matrix; unavailable adapters are disabled with reason.
  - Prompts are redacted before leaving the boundary; no paid calls in CI (fixtures only).
- Pattern references: protocol plus fixture implementation; vault references for credentials.
- Tests to write: `packages/core/tests/copilot/test_adapter_contract.py`, `packages/core/tests/copilot/test_adapter_gating.py`.

### Item 4 - chart-plan-validator-and-renderer  [P]
- Deliverable: server-side Vega-Lite subset validator and a sandboxed iframe renderer using vega-interpreter.
- Owned files (may edit): `packages/core/neurosphere_core/charts/`, `frontend/src/features/charts/`.
- Must NOT touch: `packages/contracts/schemas/chart/` (PRP-01), `frontend/src/features/copilot/`, `frontend/src/features/reports/`, `services/api/`, root `pyproject.toml`.
- Depends on: none.
- Acceptance criteria:
  - Plans with `expr`, signals, event streams, external `url` data or non-allowlisted marks are rejected (parametrized corpus test).
  - Renderer uses vega-interpreter in an iframe with `sandbox` lacking `allow-same-origin` and a strict CSP; a test asserts no `eval` or `Function` use at render.
  - Valid plans render bar, line, area and table from inline data supplied by server tools.
- Pattern references: generated `ChartPlan`; Fluent UI v9 wrapper.
- Tests to write: `packages/core/tests/charts/test_plan_validator.py`, `frontend/src/features/charts/charts.test.tsx`, `frontend/tests/e2e/chart-sandbox.spec.ts`.

### Item 5 - saved-dashboards
- Deliverable: save, share and add-to-UI flows for approved dashboards with re-authorization on every run.
- Owned files (may edit): `services/api/neurosphere_api/reports/`, `frontend/src/features/reports/`.
- Must NOT touch: `services/api/neurosphere_api/copilot/`, `services/api/neurosphere_api/dashboards/` (PRP-14), `packages/core/neurosphere_core/charts/`, `frontend/src/features/charts/`, root `pyproject.toml`.
- Depends on: Item 4.
- Acceptance criteria:
  - Shared dashboard is filtered by the viewer's scope; owner scope never leaks to the viewer.
  - Stored plan is re-validated and authorization re-evaluated on every run; revoked source access denies or redacts.
  - Add-to-UI requires an approval step and a scoped permission; cache keys include a scope hash.
- Pattern references: router per module; `require(permission)`; chart validator.
- Tests to write: `services/api/tests/reports/test_reports_reauthorize.py`, `services/api/tests/reports/test_share_scope.py`, `frontend/src/features/reports/reports.test.tsx`.

### Item 6 - chat-ui
- Deliverable: chat panel with context chip, citations, inline charts and action handoff to the PRP-17 dialog.
- Owned files (may edit): `frontend/src/features/copilot/`, `tests/e2e/copilot/`.
- Must NOT touch: `frontend/src/features/charts/`, `frontend/src/features/reports/`, `frontend/src/features/actions/` (PRP-17), `frontend/src/design-system/`, `frontend/src/api/`, `services/api/`, root `pyproject.toml`.
- Depends on: Items 2, 4.
- Acceptance criteria:
  - First token <=3s on the sandbox with recorded fixtures (provider time excluded); measured value recorded, target not asserted as guarantee.
  - Context chip shows the page, filters, time range and selection the copilot received; abstentions and citations with freshness render.
  - Action suggestion opens the PRP-17 confirmation dialog; chat has no execute control.
- Pattern references: Fluent UI v9; typed API client; streaming handling with typed errors.
- Tests to write: `frontend/src/features/copilot/copilot.test.tsx`, `frontend/tests/e2e/copilot.spec.ts`, `tests/e2e/copilot/test_first_token.py`.

### Round 2: audit gap closure (items 8-15, added 2026-11-11)
Reopened by the 2026-11-04 audit (section at the end). Rechecked 2026-11-11 against main 6d93f15:
- `NS_COPILOT_MODE` defaults to `disabled` in compose (`docker-compose.yml:147`), in `infra/demo/main.bicepparam` and in `runtime/builders/copilot.py`.
- `foundry.yaml` has only Government `foundry.model_*` rows, so a Commercial copilot (hosted: centralus, `model_gpt_4_1_mini`, `Global Standard`) resolves disabled.
- `EmptyEvidenceReader` is wired in `runtime/builders/planes.py:333` and is the `copilot/dependencies.py:114` default.
- The `chart` SSE event never carries `query_spec`; the frontend `stream.ts` already handles it.
- Reports `If-Match` is optional on share, unshare and request-publication, and `reports/service.py` emits no audit events.
- `copilot/models/redaction.py` has no phone, address or "password is" patterns.
- The chat shows "unavailable right now, try again" for a deployment that is simply unconfigured.
- No real-stack copilot test exists.

Learn, observed 2026-11-11 (https://learn.microsoft.com/azure/foundry/foundry-models/concepts/models-sold-directly-by-azure-region-availability): gpt-4.1-mini 2025-04-14 is available on Global Standard in brazilsouth, canadaeast, centralus, eastus, eastus2, northcentralus, southcentralus, westus and westus3 (not canadacentral), and on Data Zone Standard in centralus, eastus, eastus2, northcentralus, southcentralus, westus and westus3.

User decisions 2026-11-11:
- A real endpoint plus Commercial matrix rows. No fake or sandbox model mode.
- The default stays `disabled`, with a clear reason and a runbook.
- The live model run stays OPEN.
- Include save-from-chat, reports hardening, redaction hardening, and the chat UI and tool fixes.

### Item 8 - commercial-copilot-config  [P]
- Deliverable:
  - Commercial `foundry.model_gpt_4_1_mini` matrix rows:
    - `Global Standard` in the nine regions above;
    - `Data Zone Standard` in the seven US regions above;
    - each row `availability: available`, `ga_status: ga`, `authorization_scope: none_claimed`, `observed_on: '2026-11-11'`, `source_url` = the page above.
  - `docker-compose.yml` passes `NS_COPILOT_MODE` (default `disabled`), `_ENDPOINT`, `_DEPLOYMENT`, `_API_VERSION`, `_REGION`, `_MODEL_FEATURE`, `_SKU` and `_OAUTH_SCOPE` through from the operator environment. There are no credential variables (the builder refuses them).
  - New runbook `docs/runbooks/copilot.md`:
    - choosing a model and region from the matrix;
    - creating the deployment;
    - granting the API identity `Cognitive Services OpenAI User`;
    - the env vars;
    - running the API on the host with `az login` for local real-model use;
    - every readiness reason code and its fix.
  - Update the `docs/deploy/hosted-demo.md` "Copilot shows disabled" paragraph and the G01 row note in `docs/RESEARCH-AND-GATES.md`.
- Owned files: `packages/core/neurosphere_core/capabilities/data/foundry.yaml` (new rows only), the tests that pin "Commercial copilot disabled", `docker-compose.yml` (API copilot env only), `docs/runbooks/copilot.md` (new), `docs/deploy/hosted-demo.md` (copilot paragraph), the `docs/RESEARCH-AND-GATES.md` G01 note.
- Must NOT touch: other matrix rows, product code, `infra/`.
- Acceptance criteria:
  - Matrix validation passes.
  - `resolve_adapters(cloud=commercial, region=centralus, model_gpt_4_1_mini, Global Standard)` enables `approved_endpoint`.
  - canadacentral and a Government region with a Commercial endpoint stay disabled with a reason.
  - `docker compose config -q` passes and compose still defaults to `disabled`.

### Item 9 - evidence-reader  [P] (review: required)
- Deliverable: a production `EvidenceReader` that resolves ids over existing scope-filtered stores: recommendations, evaluation results and catalog entities.
  - Lookups are point reads restricted to the server-derived domain ids.
  - An unknown, unreadable or out-of-domain id is omitted; existence is never leaked.
  - `observed_at` comes from the record, so citations carry real freshness.
  - Kinds without a store are omitted and documented.
  - Wire it in the copilot builder by setting `app.state.copilot_evidence_reader`.
- Owned files: `services/api/neurosphere_api/copilot/evidence.py` (new), `services/api/neurosphere_api/runtime/builders/copilot.py`, `services/api/tests/copilot_api/test_evidence_reader.py` (new), the copilot builder tests.
- Must NOT touch: other files in `services/api/neurosphere_api/copilot/` (item 10), `runtime/builders/planes.py` (the orchestrator wires it after items 9 and 11), `packages/core/`.
- Acceptance criteria:
  - Cross-domain and unknown ids are omitted.
  - Each kind resolves from a real in-memory store, not a mock.
  - Freshness is populated.
  - An evidence question through the engine with a seeded recommendation answers with a citation instead of abstaining.

### Item 10 - save-from-chat-and-status  [P] (review: required)
- Deliverable:
  - The `chart` SSE event carries `query_spec`: the exact `StructuredQuery` of the tool call whose records filled the chart. It is attached only when the reports service's query validation accepts that query; otherwise it is omitted. The model never authors `query_spec`.
  - `GET /api/v1/copilot/status` returns `{state: ready|disabled|failed, reason_code}`. It requires authentication, has no permission beyond sign-in, and never exposes the endpoint URL.
  - A mock-api chart fixture with `query_spec`.
- Owned files: `services/api/neurosphere_api/copilot/` (except `evidence.py`), `services/api/tests/copilot_api/` (except `test_evidence_reader.py`), copilot fixtures in `frontend/tests/mock-api/`.
- Must NOT touch: `reports/`, `packages/core/`, `frontend/src/`, `openapi.json` (the orchestrator regenerates it).
- Acceptance criteria:
  - The emitted `query_spec` is accepted by `POST .../reports` and runs under the viewer's scope.
  - A chart built from several tool calls, or from no tool call, carries none.
  - The injection corpus stays 78/78 with 0 overscoped.
  - The status route covers disabled, failed and ready.

### Item 11 - reports-hardening  [P] (review: required)
- Deliverable:
  - `If-Match` is required on share, unshare and request-publication. Missing returns 422 and stale returns 409 `stale_version`, matching decision.
  - Audit events through `neurosphere_core.audit` for run, share, unshare, publication request and decision, including denials.
  - Principal ids are normalized (strip, casefold) before the share and self-approval comparisons.
  - A RunCache scope-hash test.
  - The reports UI sends the viewed ETag on those calls.
- Owned files: `services/api/neurosphere_api/reports/`, `services/api/tests/reports/`, `frontend/src/features/reports/`, `services/api/neurosphere_api/runtime/builders/planes.py` (`_reports` only: pass the audit repository).
- Must NOT touch: `copilot/`, `charts/`, `openapi.json`.
- Acceptance criteria:
  - Missing and stale ETag tests pass for all three routes.
  - Audit rows are asserted per action, including a denied one.
  - A mixed-case self-approval is refused.
  - The same dashboard with two viewer scopes yields two cache keys.
  - Vitest for the reports feature passes.

### Item 12 - redaction-hardening  [P]
- Deliverable: `copilot/models/redaction.py` masks:
  - phone numbers (US and E.164);
  - street addresses (house number plus street suffix);
  - "password is/:", "pwd", "passcode" and similar phrasing;
  - `key=value` secrets.

  Ids and dates must not be over-redacted. `tool_call_id` is shape-validated (an opaque token, otherwise refused). `tool_name` stays allowlist-checked, not redacted, because redacting it breaks function calling. Person names remain a documented limit (no NER).
- Owned files: `packages/core/neurosphere_core/copilot/models/redaction.py`, `packages/core/tests/copilot/test_redaction*.py`.
- Must NOT touch: `copilot/tools/`, adapter files other than a call-site line if `tool_call_id` validation needs one (report it).
- Acceptance criteria: positive and negative cases for each pattern; the adapter contract tests stay green.

### Item 13 - chat-ui-fixes
- Deliverable:
  - Discard streamed text on an `error` terminal.
  - The first-token clock starts after conversation creation.
  - The module-level `useCopilotSelection` store becomes a provider, so nothing leaks across sessions or tests.
  - The dock reads `/copilot/status` and shows "The assistant is not configured in this deployment" with the reason code when disabled or failed (an operator hint, never "try again"), and hides the composer.
- Owned files: `frontend/src/features/copilot/`.
- Must NOT touch: `frontend/src/api/`, `features/actions/`, `features/reports/`, `services/`.
- Depends on: Item 10.
- Acceptance criteria: Vitest covers each fix; tsc and eslint are clean; the copilot Playwright spec passes against the mock API.

### Item 14 - tool-fixes  [P] (review: required)
- Deliverable:
  - `propose_action` refuses evidence refs that the `EvidenceReader` cannot resolve in scope (deny, logged).
  - `lifecycle_status in []`, and any empty `in` list, is refused, not treated as no filter.
  - A contract test that the real catalog repository's `get_entity` hides unreadable entities.
- Owned files: `packages/core/neurosphere_core/copilot/tools/`, `packages/core/tests/copilot/test_tool_*.py`.
- Must NOT touch: `copilot/models/`, `services/`.
- Acceptance criteria: the tests above pass; the core copilot suite and the injection corpus stay green.

### Item 15 - copilot-real-stack-loop
- Deliverable: `tests/integration/real_stack/test_copilot_loop.py` (`pytest.mark.integration`, compose emulators at 127.0.0.1).
  - Setup: the composed API, with the real `ApprovedEndpointAdapter` over a recorded HTTP transport (no network, no fixture adapter) and seeded catalog and recommendations.
  - Flow:
    1. Ask a question; the tool call returns citations with freshness from Cosmos records, and evidence resolves through item 9.
    2. An action suggestion drafts through the real action plane.
    3. The chat chart is saved as a report through item 10's `query_spec`.
    4. A second user runs the shared report under their own scope.
    5. After the share is revoked, the next run is denied.
  - Output is recorded in `docs/evidence/G12/copilot/`.
- Owned files: that test, `docs/evidence/G12/copilot/`.
- Must NOT touch: product code; report gaps instead.
- Depends on: Items 8, 9, 10, 11.
- Acceptance criteria: passes locally against `docker compose up -d --wait`; never runs in CI.

### Item 16 - evaluation-result-point-read  [P] (added 2026-11-11, user decision)
Why: `EvaluationStore` has no by-id read (only list, scan and window reads). As a result the item 9 reader omits every `evaluation_result` evidence id in production.
- Deliverable: a scope-filtered `get_result(scope, domain, evaluation_id) -> EvaluationResult | None` on the `EvaluationStore` protocol, plus the in-memory and Cosmos implementations.
  - It must be a point read: the Cosmos partition key and id, never a query scan.
  - An out-of-scope domain or a cloud mismatch returns None. It never raises a "not found vs forbidden" distinction.
- Owned files: `packages/core/neurosphere_core/evaluation/store.py`, `packages/core/neurosphere_core/evaluation/cosmos_store.py`, and their core tests.
- Must NOT touch: `services/`, `evaluation/pipeline.py`, `packages/contracts/`.
- Acceptance criteria:
  - Get-by-id returns the result for an in-scope caller.
  - It returns None for an unknown id, another domain, or another customer or cloud.
  - The Cosmos store uses `read_item`, shown by a unit test with a fake container.
  - The item 9 reader resolves `eval:` ids through it once merged (orchestrator re-runs the item 9 tests).

Waves (round 2): 1 = items 9, 10, 11, 14; 2 = items 8, 12, then 13 after item 10 merges; 3 = item 15 (the only compose lane).

Orchestrator seams:
- Swap the reports registry's `EmptyEvidenceReader` in `planes.py` to the item 9 reader once items 9 and 11 have merged.
- Regenerate `openapi.json` and `docs/reference`.
- Write the OPEN notes in RESEARCH-AND-GATES.

## Validation gates
```
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode fast    # per item
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full    # before merge
python scripts/validate_planning.py
```
Feature-specific:
```
docker compose --profile app up -d --wait
python -m pytest packages/core/tests/copilot packages/core/tests/charts services/api/tests/copilot services/api/tests/reports
python -m pytest services/api/tests/copilot_api/test_orchestrator_injection.py   # D4: corpus consumed from the copilot suite
python -m pytest -m integration tests/integration/copilot
pnpm --filter frontend test
pnpm --filter frontend exec playwright test frontend/tests/e2e/copilot.spec.ts frontend/tests/e2e/chart-sandbox.spec.ts
```
A live model run is optional: operator-approved, requires NS_LIVE_APPROVED=1, and not required for merge.

## Live and open gates
- G01 (service/feature/region matrix): model endpoint and Foundry Agent Service availability per cloud come from the matrix; no evidence closes G01 here.
- G05 (model swap compatibility): action contract identity across adapters is verified with fixtures only; live swap evidence belongs to PRP-17.
- G12 (emulator parity): record where emulator behavior differs from live for conversation storage.
- Injection results are recorded as test output; any corpus case skipped or marked expected-fail is listed in the completion note.
- If a live item did not run, record it OPEN in the completion note and in docs/RESEARCH-AND-GATES.md; never report it as a skipped green test.

## NOT building
- The MCP server and client (PRP-22); this PRP only owns the tool registry they reuse.
- The action executor, HITL workflow and confirmation dialog (PRP-17).
- The injection corpus and threat model (PRP-12); this PRP consumes the corpus.
- Cost, latency and coverage dashboards themselves (PRP-14); this PRP renders model-proposed charts from tool data.
- Free-form query languages, generated JavaScript, or arbitrary Vega specifications.
- Public docs assistant (PRP-25); it is a separate read-only backend.
- Contract changes to `ChartPlan` or `StructuredQuery`; request them through PRP-01.

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [x] All clarification questions are decided, not guessed

## Execution state

Plan approved 2026-10-21 with five deltas signed off by the operator.

- D1: new item 7 owns the shared hookup files: `services/api/neurosphere_api/routers.py`, `services/api/openapi.json` regeneration, app-state wiring (default fixture adapter, tool registry, conversation store), `frontend/src/app/main.tsx`, `frontend/src/app/workspaceNav.ts`, the app-shell mount for the copilot panel, `frontend/tests/mock-api/`, `tests/integration/copilot/`. Items 2 and 5 ship a `register(registry)` hook and do not edit `routers.py`. Item 7 creates a placeholder `frontend/src/features/copilot/index.ts`; item 6 replaces its contents and keeps the export names.
- D2: item 4 also owns `frontend/package.json`, `pnpm-lock.yaml` (vega-lite, vega, vega-interpreter only), `frontend/vite.config.ts` plus the chart-sandbox HTML entry, and `docs/licenses.md` if the licence gate needs regeneration.
- D3: API copilot tests live in `services/api/tests/copilot_api/` (not `copilot/`) because `packages/core/tests/copilot/` exists and same-named test packages shadow each other.
- D4: the injection corpus run is `services/api/tests/copilot_api/test_orchestrator_injection.py` (all cases via `run_corpus`); `tests/security/injection -k copilot` would collect 0 cases and PRP-12 owns that folder.
- D5: no new permission constants (PRP-06 owns them). Ask = `data.read`; tools recheck `data.read` / `evidence.read` / `action.propose`; save/share report = `report.create`; add-to-UI approval = a different principal with `config.manage` in the same domain, self-approval refused.

Waves: A = items 1, 3, 4 in parallel; B = items 2, 5 in parallel; C = item 7; D = item 6. Models: all implementers sonnet; every item gets one reviewer pass; rework confirmation passes haiku. Item 2 dispatched as soon as item 1 merged (its only dependency), without waiting for item 4.

- D6 (2026-10-21, orchestrator, within item 1 scope): "model-supplied `domain_id`/`customer_id` is ignored" is implemented as never consulted + logged + call refused (`ScopeArgumentRefusedError`), because the PRP-12 corpus expects `deny` for scope-smuggling tool calls. The derived `IdentityScope` is the only scope a tool ever sees.

### Wire contract (decided 2026-10-21; items 2, 5, 6, 7 code against it)
- Conversations are user-scoped, not domain-scoped. `POST /api/v1/copilot/conversations` -> `{id, created_at, retention_class, expires_at}`. `GET /api/v1/copilot/conversations` (caller's own only, paged `{items, next_cursor}`), `GET /api/v1/copilot/conversations/{id}` (owner only; anyone else gets 404, not 403), `DELETE /api/v1/copilot/conversations/{id}` (owner). Stored turns are redacted; people pseudonymized.
- `POST /api/v1/copilot/conversations/{id}/messages` with body `{text, context: {page, route, filters: {<allowlisted key>: string|string[]}, time_range: {from, to} | null, selection: [entity_id], domain_id: string | null}}` returns `text/event-stream`. Context is a hint: `domain_id` and `selection` only ever narrow the derived scope; unreadable selections are dropped and counted. Requires `data.read` in at least one domain.
- SSE events (`event:` name, JSON `data:`), in order: `context` `{page, route, filters, time_range, selection, dropped_selection_count, applied_domains}` (exactly what the copilot received; drives the context chip) -> zero or more `tool` `{name, status: started|ok|refused}` -> zero or more `token` `{text}` -> zero or more `citation` `{record_id, kind, source, as_of, freshness: fresh|stale|unknown}` / `chart` `{chart_plan}` (server-validated) / `action_suggestion` `{intent_id, domain_id, action_type, target, intent_hash}` (a DRAFT created through the PRP-17 actions service; the UI opens the PRP-17 confirmation dialog for `intent_id`; chat has no confirm/execute) -> exactly one terminal: `done` `{message_id, status: answered}` | `abstain` `{message_id, reason_code, reason}` | `denied` `{message_id, reason_code, reason}` | `error` `{code, detail}`.
- Terminal semantics: `denied` = a policy boundary refused something in the turn (unregistered tool or argument, scope-shaped argument, missing permission, banned chart plan, raw query, disclosure of system prompt/secrets); `abstain` = no authorized evidence supports an answer (no tool records, or the model's text cites ids no tool result produced, or the model only tried to change its own behaviour). Text tokens already streamed before an `abstain`/`denied` are discarded by the UI and never persisted as an answer.
- Reports (item 5): `POST/GET /api/v1/reports/domains/{domain_id}/reports`, `GET/PUT/DELETE .../reports/{report_id}`, `POST .../reports/{report_id}/run` (re-validates plan + re-authorizes as the viewer every run), `POST .../reports/{report_id}/shares` `{principal_id}` / `DELETE .../shares/{principal_id}`, `POST .../reports/{report_id}/publication` (request add-to-UI, `report.create`) and `POST .../reports/{report_id}/publication/decision` `{decision: approve|reject}` (different principal with `config.manage`; self-approval refused). Stored report = `{id, domain_id, owner, title, chart_plan, query_spec, shares[], publication: {state: none|pending|approved|rejected, ...}, etag}`; never stored result data.

Round 2 (items 8-15) approved 2026-11-11 as written: integration branch `prp-19-round2` from main 6d93f15; reviews on items 9, 10, 11, 14; Haiku rework confirmations.

| Item | Status | Branch | Model | Evidence | Updated |
|------|--------|--------|-------|----------|---------|
| 1 | merged | worktree-agent-acec59f7281c6b9a0 | sonnet | ed89a6f; orchestrator re-run: only copilot/__init__ + copilot/tools/ + conftest + test_tool_scope + test_tool_allowlist touched, ruff + format clean, pyright 0 errors, core copilot + import boundaries 78 passed; decisions: D6 scope-shaped args refused (key-normalised), unsupported StructuredQuery clauses (sort/group_by/fields/cursor/traversal) refused not dropped, limit cap 100, timeout cap 10 s; no core evidence service, item 2 must supply an `EvidenceReader`; reviewer APPROVED (follow-ups: empty `lifecycle_status in []` likely means no filter, model-supplied evidence refs on propose_action not existence-checked, contract test that real `get_entity` hides unreadable entities); merge 52e2255 (copilot/__init__ auto-merged with item 3); post-merge core copilot + import boundaries 159 passed | 2026-10-21 |
| 2 | merged | worktree-agent-a4a37fc807b8f2065 | sonnet | dd62b13; orchestrator re-run: only copilot/ + tests/copilot_api/ touched, ruff + format clean, pyright 0 errors, copilot_api + core copilot + test_app + openapi drift 263 passed 1 deselected (Cosmos integration); injection corpus 78/78 passed, 0 overscoped retrievals, 0 complied, no skip/xfail (denied 63, abstained 13 + positive and negative controls); additive: citation handles `[cite:rN]` (prompt redaction masks GUID ids), `uncited_answer` and `tool_budget_exhausted` abstain reasons; open: EmptyEvidenceReader (no core evidence store, evidence questions abstain), get_evidence not narrowed by context (still scope-bounded), output-guard 40+ char opaque-run rule may flag long ids; reviewer APPROVED, injection corpus run real and not skipped: YES (reviewer re-ran 78/78, outcomes mapped only from the engine terminal event, `case.expected` never consulted, negative control fails all 78; follow-ups: corpus-level forged-handle control, re-run corpus once item 7 binds the real chart validator (7 chart cases currently denied by the fail-closed default), document get_evidence context narrowing, comment on persist-before-release on client disconnect); merge d8b4914; post-merge copilot_api + core copilot + charts + import boundaries + test_app + openapi drift + actions_api 362 passed 1 deselected | 2026-10-21 |
| 3 | merged | worktree-agent-ac5d48f3d669cd67c | sonnet | b408ba0; orchestrator re-run: only copilot/__init__ + copilot/models/ + test_adapter_* touched, ruff + format clean, pyright 0 errors, core copilot + import boundaries 82 passed; deviations: `oauth_scope` field name (S106), Gov Foundry needs explicit oauth_scope, GUIDs redacted; open: no Commercial foundry.model_* matrix rows (Commercial resolves disabled on the shipped matrix), Gov foundry.agent_function_calling unverified -> disabled, Foundry Responses wire shape unverified vs Learn, httpx undeclared in packages/core/pyproject.toml (item 7); reviewer APPROVED (follow-ups: redaction misses phones/addresses/names and "password is x" phrasing, tool_call_id/tool_name unredacted, oauth_scope allow-list, fixture scenario via create_adapter test); merge 817f683; post-merge core copilot + import boundaries 82 passed | 2026-10-21 |
| 4 | merged | worktree-agent-a16772ddc765c9d4f | sonnet | a36ccd4; orchestrator re-run: ruff + format clean, pyright 0 errors, charts + import boundaries 67 passed, licences PASS (603), tsc + eslint clean, vitest charts + app 35 passed, build ok (chart-sandbox.html 777 kB), Playwright chart-sandbox + smoke 10 passed; deps vega ^6.4.0, vega-lite ^6.5.0, vega-interpreter ^2.3.2 (BSD-3); deviation: sandbox script is one inline IIFE allowed by a sha256 CSP via a vite plugin (not a multi-page module entry: opaque-origin module scripts need CORS and dev HMR breaks connect-src none); docs/adr/0002-stack-pins.md licence appendix regenerated by the licence gate (accepted under D2); `ChartPlanInvalidError` lives in charts (422); reviewer APPROVED (served the built page under the real CSP and rendered 10 transform-heavy plans with 0 violations; follow-ups: client `specViolations` is shape-only (mirror transform/channel allowlists), callers persist `plan.model_dump(by_alias=True)` not raw input, Playwright cases for sort/aggregate/filter/timeUnit/bin, tighten `_scan` data.values skip); merge b705b42; post-merge core charts + copilot + import boundaries 225 passed, licences PASS, tsc clean, vitest charts + app 35 passed | 2026-10-21 |
| 5 | merged | worktree-agent-aa9a3fcd231240a36 | sonnet | e1bbb38; orchestrator re-run: only reports/ (api, tests, frontend) touched, ruff + format clean, pyright 0 errors, reports + charts + test_app + openapi drift 128 passed 3 deselected (Cosmos integration), tsc + eslint clean, vitest reports + charts + app 67 passed; additive: ReportView `is_owner`/`can_decide_publication`, optional `metric`, `?publication_state=`, approved publication readable/runnable by `data.read` holders under their own scope, stored plan is a template (`data.values` emptied, refilled + re-validated per run, `no_data` status); reviewer CHANGES REQUIRED (blocker: publication decision If-Match optional, owner edit + re-request race lets a reviewer approve an unseen definition) -> rework round 1 a8655d6 (decision route requires If-Match, missing -> 422, stale -> 409 `stale_version`, UI sends viewed ETag, race test); orchestrator re-run: ruff + pyright clean, reports + charts + test_app + openapi drift 130 passed 3 deselected, tsc + eslint clean, vitest 67 passed; haiku confirmation CONFIRMED FIXED (note: `_check_etag` None guard still present but unreachable for decisions); follow-ups: If-Match optional on share/unshare/request-publication, principal-id normalization for self-approval compare, RunCache scope-hash test, raw principal ids (no directory lookup), no audit events for run/share/decision, unsupported stored query fails only at run (422); merge 6bc3efe; post-merge reports + copilot_api + core copilot + charts + import boundaries + test_app + openapi drift 378 passed 4 deselected, tsc clean, vitest 67 passed | 2026-10-21 |
| 6 | merged | worktree-agent-abbe4fd3d153e829d | sonnet | feb036c; orchestrator re-run: only copilot feature + e2e spec + tests/e2e/copilot + docs/evidence/G07/copilot touched, tsc + eslint clean, ruff + format + pyright clean, first token unmarked test 1 passed (re-run p50 62 ms, p95 69 ms, max 139 ms; committed evidence run p50 119 ms, p95 140 ms, max 296 ms, n=30, recorded fixtures, provider excluded, target <= 3 s printed not asserted), collection 255 no clash, build ok, full Playwright 83 passed; full vitest flaked 1 in 5 (reports sharing / actions button flow: Fluent dialog `findByRole` past the 1 s default under parallel load; integration branch without item 6 0 in 5) -> orchestrator seam fix 44b5fe7 (Testing Library asyncUtilTimeout 5 s in frontend/tests/setup.ts); handoff navigates to `/actions/detail?domain_id=&intent_id=` (PRP-17 Validate -> Request confirmation -> dialog), chat calls only conversation create + message post; reviewer CHANGES REQUIRED (blocker: Save as report paired the chat chart with a hardcoded daily cost query, undisclosed) -> rework round 1 2731e1a (save offered only when the `chart` event carries `query_spec`, never sent today; saveQuery.ts deleted); orchestrator re-run: tsc + eslint clean, vitest copilot + reports + app 75 passed (1 intermittent failure on the branch without 44b5fe7, then 3/3 green), Playwright copilot + smoke 8 passed; haiku confirmation CONFIRMED FIXED; follow-ups: add `query_spec` to the `chart` event contract to re-enable save from chat, discard streamed text on `error` terminal, client first-token clock includes conversation creation on the first message, `useCopilotSelection` module-level store leaks across sessions/tests, axe excludes `[data-tabster-dummy]`; merge 83baac1; post-merge full vitest 8/8 runs 389 passed | 2026-10-22 |
| 7 | merged | worktree-agent-a218c4a7a119cb3bd | sonnet | dc95aba; orchestrator re-run: only item 7 owned files, ruff + pyright clean, core copilot + charts + copilot_api + reports + tests/integration/copilot + test_app + openapi drift + actions_api 416 passed 7 deselected; corpus with REAL chart validator 78/78, 0 overscoped (deny:chart_plan_rejected=7); Cosmos emulator `-m integration tests/integration/copilot` 3 passed; licences PASS (603); tsc + eslint clean, full vitest 34 files 361 passed, build ok, Playwright smoke + chart-sandbox + actions 26 passed; openapi +10 paths +46 components, NOT purely additive (7 module-qualified renames: DecisionBody, TimeRange, Lock-*, Timestamp-Input, Validity-*); no container provisioning precedent (stores create containers in code); httpx >=0.28,<0.29 declared in packages/core; mock fixtures answered/abstain/denied/action_suggestion/error via `?fixture=` > `fixture:<name>` text > keywords; CopilotDock mounted in Layout (routes.tsx) inside ErrorBoundary; open: production app.state bootstrap still absent (composition tests stand in); reviewer APPROVED (follow-ups: wrapper `exclude_unset=True` drops schema defaults from emitted plans, re-export `validate_chart_plan_mapping`, check mock SSE tool names vs contract when item 6 lands, call out the 7 OpenAPI renames in the PR); merge 8b71985; post-merge 416 passed 7 deselected, tsc clean, vitest app + reports + charts 67 passed | 2026-10-21 |
| 8 | merged | worktree-agent-a1dba54c780fad516 | sonnet | b074c20; 16 rows foundry.model_gpt_4_1_mini.commercial.<region>.global-standard (brazilsouth, canadaeast, centralus, eastus, eastus2, northcentralus, southcentralus, westus, westus3) and .data-zone-standard (7 US regions), GA, none_claimed, observed 2026-11-11 (Learn verified by orchestrator); compose NS_COPILOT_* passthrough default disabled; docs/runbooks/copilot.md; hosted-demo + G01 note; tests: gating commercial (centralus GS enabled, canadacentral GS + brazilsouth DZS disabled, Gov + Commercial endpoint endpoint_cloud_mismatch), loader row count 646 -> 662 and TODAY 2026-11-11; orchestrator found item 14's bare 'from conftest import _agent' failed deterministically with tests/contracts in-session -> fix e8bd39c (agent_factory fixture); orchestrator re-run: capabilities + contracts matrix + core copilot 245 passed, compose config ok, validate_planning exit 0; merge 67ba291; post-merge runtime_planes + copilot_api 178 passed; operator: .env.example NS_COPILOT_* lines owed | 2026-11-11 |
| 9 | merged | worktree-agent-a67baa0caec1c9674+worktree-agent-a60fea91e1390a58d | sonnet | c665eb1 + rework 4d90451; StoreEvidenceReader (eval: prefix -> evaluation get_result, 5-segment recommendation id -> recommendation, else catalog; cap 50; observed_at from record; catches only ForbiddenError/InvalidSchemaError per id, everything else propagates); orchestrator re-run: copilot_api + runtime_planes 165 passed; reviewer CHANGES REQUIRED (except Exception masked outages) -> rework round 1; Haiku CONFIRMED FIXED (11 passed); merge b37ea57; post-merge 1 failure = item 9 test pinning 'shipped evaluation store omits eval evidence', obsoleted by item 16 -> orchestrator fix-forward fafc1c4 (shipped store now resolves eval: ids; absent point read still omits); reports registry keeps EmptyEvidenceReader by design (report runs only execute tool_for tools), documented in planes.py | 2026-11-11 |
| 10 | merged | worktree-agent-a57884b80eaa44193 | sonnet | d75ffd5; orchestrator re-run: ruff + pyright clean, copilot_api + reports + test_app 163 passed (corpus 78/78); query_spec only when exactly one recorded query tool call's result ids equal the chart record_id set and it passes StructuredQuery + ReportBody + validate_chart_plan (cost metric default only); model-supplied query_spec popped; GET /copilot/status from the composition registry (falls back to get_copilot); reviewer APPROVED (follow-ups: is_reason_code guard on fallback reason, debug log on unsaveable chart, docs note that rows without record_id are never saveable); merge 20326bf; post-merge copilot_api + reports + test_app + runtime_planes 226 passed, core copilot 168 passed; openapi drift expected (orchestrator regenerates) | 2026-11-11 |
| 11 | merged | worktree-agent-a76dc3dfffc6b9d78 | sonnet | 7dffb28; orchestrator re-run: reports + runtime_planes + authz + test_app + tests/integration/copilot 301 passed; If-Match required (422 missing / 409 stale) on share/unshare/request-publication; ReportAuditor report.run/share/unshare/publication.request/publication.decide incl. denials (report_not_visible same for missing/invisible, self_approval_refused); normalize_principal strip+casefold at compare and write; composition fails closed without an audit repo; outside ownership (accepted): tests/integration/copilot scenarios/support If-Match, test_planes_builder assertion; reviewer APPROVED (follow-ups: bound URL report_id length in denied audit, audit-write failure turns 404 into 500, legacy shares normalized only on next write); merge cac4546; post-merge reports + copilot_api + runtime + authz + test_app + integration/copilot 515 passed | 2026-11-11 |
| 12 | merged | worktree-agent-a034bd62310dc89f2 | sonnet | f6927fa; [phone] (E.164 needs +, US needs separators, before the card rule), [address] (number + 1-4 words + bounded suffix list), credential phrasing keeps the label and masks the value (behaviour change: the old rule replaced the label too), generic key=value rule for credential-named keys (max_tokens untouched), safe_call_id in redact_request (non-matching tool_call_id -> call_ + sha256 prefix, applied to call and result so pairing survives), tool_name validated not redacted (mismatch raises ValueError), person names documented as a limit; no fixture or adapter change; orchestrator re-run: ruff + pyright clean, core copilot + evaluation + capabilities + contracts matrix 444 passed, copilot_api 114 passed (corpus 78/78); merge 8de002e; post-merge core copilot + evaluation 379 passed | 2026-11-11 |
| 13 | merged | worktree-agent-a10a427e21ec4ad59 | sonnet | 1344ae8; error terminal (and client-side failTurn) discards partial text; first-token clock after conversation create (injectable now); CopilotSelectionProvider per-provider store, dock wraps itself, module-level setCopilotSelection removed (no product page publishes a selection; Shell.tsx must wrap Outlet + dock for pages to publish: follow-up); useCopilotStatus on open: disabled/failed shows 'not configured' + reason + runbook hint, no composer; 503 copilot_unconfigured same message; implementer: Playwright copilot 7 passed; orchestrator re-run: tsc + eslint clean, vitest copilot + app 119 passed; merge dcaef7a; post-merge vitest copilot + reports + app 154 passed | 2026-11-11 |
| 14 | merged | worktree-agent-aa47edf72fd10f9b2 | sonnet | b2ed8ae; orchestrator re-run: ruff + format clean, pyright 0, core copilot 168 passed, corpus + tests/security/mcp 53 passed; propose_action refuses unresolved evidence refs (ForbiddenError evidence_ref_unresolved, count-only log), empty in/eq filter values refused (ToolBudgetError empty_filter_values; contract already rejects values: [] so the gap was in/eq with neither value nor values), real InMemoryCatalogRepository hides unreadable entity (no get_entity tool exists; tested via propose_action + search_catalog); reviewer APPROVED (follow-ups: split branchy empty-in test, document all-or-nothing evidence refusal in the tool description, MCP-path test for evidence refusal); merge 56659cb; post-merge core copilot 168 passed | 2026-11-11 |
| 15 | merged | worktree-agent-ac3b8a8c00215ab0d+worktree-agent-a02724a52165ee950 | sonnet | f59e3ed + 9721bc8; tests/integration/real_stack/test_copilot_loop.py (integration marker, compose emulators, real authz/data/planes/action/reports/copilot builders, REAL ApprovedEndpointAdapter enabled by the item 8 matrix row (commercial centralus model_gpt_4_1_mini Global Standard) over a sequential recorded-HTTP transport + static fake credential); 9 steps PASS: status ready; chart turn context/tool ok/3 citations (as_of = Cosmos updated_at)/chart with query_spec/done; evidence turn cites recommendation + evaluation result (item 16 get_result; as_of = completed_at; domain B eval id not cited); action_suggestion intent drafted not executed; chart saved as report, owner run 3 rows; shared viewer B 2 of 3 rows; unshare with If-Match -> B 404; user C denied domain_out_of_scope / abstain no_authorized_evidence, user D 403; Cosmos audit report.run (after + denied), share, unshare; follow-up 9721bc8 replaced a stale 'no by-id read' claim with a seeded eval citation and fixed the evidence.py docstring; freshness stale (example timestamps old); evidence docs/evidence/G12/copilot/real-stack-loop-2026-11-11.md; orchestrator re-run: 1 passed 8.53 s, default selection 1 deselected; merge 826e8fe, post-merge 1 passed 8.30 s; never runs in CI; not exercised: live model, Playwright UI, Government | 2026-11-11 |
| 16 | merged | worktree-agent-aa228e82cd7b7e00e | sonnet | 6a2a03b; get_result(scope, domain, evaluation_id) on protocol + memory + Cosmos (read_item, pk [customer, domain], doc id _doc_id; None for out-of-scope domain before any read, 404, wrong doc_type, cloud/customer/domain mismatch; other errors mapped via _raise_mapped); orchestrator re-run: ruff + pyright clean, core evaluation 159 passed; implementer: api evaluation + evaluation_worker 112 passed; merge 72dd5c0; emulator conformance not run | 2026-11-11 |

## Completion note (filled at ship)
- Date: 2026-10-22
- Merged commits: PR #87, merge `b9fe5c0` into main. Item merges on `prp-19-copilot-and-report-creation`: item 3 `817f683`, item 1 `52e2255`, item 4 `b705b42`, item 2 `d8b4914`, item 5 `6bc3efe` (rework `a8655d6`), item 7 `8b71985`, item 6 `83baac1` (rework `2731e1a`), orchestrator test-timeout fix `44b5fe7`, gate notes `f4b1a48`, CI fix-forward `ee60c94` (gitleaks fixture split + `.gitleaksignore` fingerprint, four CodeQL alert classes) and `891dede` (CodeQL match-capture false positive). CI on PR #87: 21 checks passed, 2 licence-register regeneration jobs skipped (nothing to regenerate). Local `verify-gates -Mode full`: PASS (6542 passed, 102 deselected).
- Deviations from blueprint and why:
  - D1: new item 7 owned the shared hookup files (router hooks, `openapi.json`, frontend app wiring, mock API, `tests/integration/copilot`), because no item owned them. Item 7 also bound the real chart validator as the copilot default and declared `httpx` in `packages/core/pyproject.toml`. No container provisioning was added: there is no precedent, because stores create their containers in code.
  - D2: item 4 owned the frontend deps (`vega`, `vega-lite`, `vega-interpreter`, BSD-3), the Vite sandbox entry, and the licence register and stack-pin appendix regeneration. The sandbox script is one inline bundle allowed by a sha256 CSP, not a separate module entry. An opaque-origin module script needs CORS, and dev HMR breaks `connect-src 'none'`.
  - D3: API copilot tests live in `services/api/tests/copilot_api/`, because same-named test packages shadow each other.
  - D4: the corpus run is `services/api/tests/copilot_api/test_orchestrator_injection.py`; the PRP's `tests/security/injection -k copilot` gate line was corrected.
  - D5: no new permission constants.
  - D6: model-supplied scope arguments are refused and logged rather than silently ignored, because the corpus expects `deny`.
  - Item 2 was dispatched as soon as item 1 merged, its only dependency.
  - Wire additions on top of the pinned contract:
    - Citation handles `[cite:rN]`, because prompt redaction masks GUID record ids.
    - `uncited_answer` and `tool_budget_exhausted` abstain reasons.
    - ReportView `is_owner` and `can_decide_publication`, an optional `metric`, and a `?publication_state=` filter.
    - An approved publication is runnable by `data.read` holders, each under their own scope.
    - Stored report plans are templates with `data.values` emptied.
  - Item 6 deliberately does not offer save-as-report from chat (review rework), because the `chart` event carries no query spec.
  - `openapi.json` is NOT purely additive. It gained 10 paths and 46 components, and 7 components were renamed module-qualified (`DecisionBody`, `TimeRange`, `Lock-*`, `Timestamp-Input`, `Validity-*`).
  - Orchestrator seam fix `44b5fe7`: Testing Library `asyncUtilTimeout` raised to 5 s. Fluent dialogs exceeded the 1 s default under parallel workers, and the full suite flaked about 1 run in 5.
- Descoped items: none. Not built:
  - A production `app.state` bootstrap, as in PRP-18; composition tests stand in.
  - A core evidence store; `get_evidence` uses an empty reader, so evidence questions abstain.
  - Save-from-chat; it needs `query_spec` on the `chart` event.
- Injection corpus result (cases run, overscoped retrievals): 78 cases run, 78 passed, 0 complied, 0 overscoped retrievals, 0 drafted intents, with no case skipped or marked expected-fail. The run uses both the fail-closed and the real chart validator, through the real engine and item 1 registry. Outcomes come only from the engine's terminal event (denied 65, abstained 13). Reviewer confirmed the run is real and not skipped.
- Optional live model run: OPEN (not run; `NS_LIVE_APPROVED=1` not set). Fixtures only, no paid calls. First token, measured against the 3 s planning target and not asserted: p50 119 ms, p95 140 ms, max 296 ms, n=30. This used the composed API with the recorded-fixture adapter, provider time excluded (`docs/evidence/G07/copilot/`). The engine releases tokens only after the output guard and persistence, so a live first token tracks full model-turn time. G01, G05, G07 and G12 stay OPEN, with PRP-19 notes on their rows in `docs/RESEARCH-AND-GATES.md`.
- Follow-ups (non-blocking, from reviews):
  - Tools and orchestrator:
    - Empty `lifecycle_status in []` filter semantics.
    - Existence-check model-supplied evidence refs on `propose_action`.
    - Contract test that the real `get_entity` hides unreadable entities.
    - Corpus-level forged-handle control.
    - Document `get_evidence` context narrowing.
    - The output guard's 40+ character opaque-run rule may flag long ids.
  - Adapters:
    - Redaction misses phones, addresses, names and "password is x" phrasing; `tool_call_id`/`tool_name` are unredacted.
    - `oauth_scope` allow-list.
    - Add Commercial `foundry.model_*` matrix rows.
    - Verify the Foundry Responses wire shape against Learn before any live run.
  - Charts:
    - Mirror the server allowlists in the client `specViolations`.
    - Playwright cases for sort, aggregate, filter, timeUnit and bin.
    - Tighten the `data.values` scan skip.
    - The `exclude_unset=True` wrapper drops schema defaults.
  - Reports:
    - Make `If-Match` required on share, unshare and request-publication.
    - Principal-id normalization for the self-approval compare.
    - RunCache scope-hash test.
    - Directory lookup for share principals.
    - Audit events for run, share and decision.
  - Chat UI:
    - Add `query_spec` to the `chart` event to re-enable save-from-chat.
    - Discard streamed text on an `error` terminal.
    - The client first-token clock includes conversation creation on the first message.
    - `useCopilotSelection` module-level store.
    - Axe excludes `[data-tabster-dummy]`.

## Audit 2026-11-04

Reopened after a deep audit (static read by a read-only agent; no tests were run). Gaps, with evidence:

- The copilot answers 503 `copilot_unconfigured` by default: `docker-compose.yml:147` sets `NS_COPILOT_MODE: disabled`; `infra/demo/main.bicep:224` takes `copilotMode` defaulting to disabled (`docs/deploy/hosted-demo.md:489`). Production never binds the recorded-fixture adapter, so chat is dead without an operator-configured endpoint. (It is composed by PRP-29 builders `copilot.py` and `planes.py:329-363`; the completion note is stale.)
- `EmptyEvidenceReader` is the default, so every evidence question abstains. Save-from-chat is not built.
- No Commercial `foundry.model_*` matrix rows (Commercial resolves disabled); Foundry wire shape unverified, live run OPEN.
- Reports follow-ups open: `If-Match` not required on share/unshare/request-publication; no audit events for run/share/decision. Redaction misses phones, addresses and names. Copilot e2e runs against the mock API only.
