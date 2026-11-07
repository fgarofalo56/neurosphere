# Lane 2 validation: catalog, recommendations and evaluation, HITL (NS-02, NS-03, NS-04)

Date 2026-11-06, branch main, read-only on source. Rubric: `docs/validation/RUBRIC.md`.

## What I ran

| Command | Result | Store used |
|---|---|---|
| `uv run pytest services/api/tests/catalog_api services/api/tests/hitl_api services/api/tests/evaluation -q` | exit 0, all pass (the `-q -q` run printed no count; log was `temp/lane2-api.log`, only the exit line is kept) | in-memory twins (`InMemoryCatalogRepository`, in-memory HITL/evaluation stores) behind the real routers |
| `uv run pytest services/workers/neurosphere_workers/recommendations/tests services/workers/tests/projections services/workers/tests/hitl_timers services/workers/tests/evaluation_worker -q` | 99 passed | in-memory; sandbox files; recorded-fixture judge |

I did NOT run any test against Cosmos or the compose stack (rubric forbids docker compose), and I did not run the UI. Every WORKS verdict below is therefore "worked against the in-memory twin through the real router", and I say so per row. Nothing in this lane was exercised against real customer data.

## 1. Summary table

Operator-configurable column: UI / API only / file or env only / IaC only / not configurable.

| Capability | PRD | PRP and tracker status | Class | Operator-configurable? | Evidence |
|---|---|---|---|---|---|
| Catalog list, get, search, lineage (read) | NS-02 | PRP-10 `backlog` (PR #52 merged, 7 of 7 items merged), PRP-31 `backlog` (PR #150 merged) | PARTIAL | UI for read (`/catalog`, `/catalog/entity`); search needs a search provider (`catalog_graph`) | catalog_api tests pass (in-memory); `/catalog` search 503s on a bare API (PRP-31 audit note) |
| Create / edit / bulk import entities | NS-02 | PRP-10; PRP-31 Clarification 6 deferred the UI | PARTIAL: API real, no UI | API only: `POST /api/v1/catalog/entities`, `PUT .../entities/{id}`, `POST .../import` | `catalog/router.py:182,230,287`; `frontend/src/features/catalog/*` has no create/import (only `post` calls are stale-agent dry-run/confirm and grant/MCP publish: `hooks.ts:38-53`, `explorerHooks.ts:240,249`) |
| Discovery of agents/models/tools from real sources into the catalog | NS-02 | PRP-09 `backlog` (PR #45), PRP-10 | MISSING | not configurable | Foundry `FoundryDiscoveryConnector.discover()` exists (`connectors/reference/foundry/.../connector.py:156`) but no code in `services/` or `packages/` imports it; nothing writes its `DiscoveryResult` to the catalog |
| Entities seeded for the demo | NS-02 | sandbox generator | WORKS for synthetic only | file/script only: `scripts/sandbox/sbx_seed_stack.py:1077-1100` calls `CatalogRepository.create_entity` | script reads sandbox output, not real systems |
| Inferred edges from traces (INVOKES, USES_MODEL, DELEGATES_TO) | NS-02 | PRP-10 item 3 | PARTIAL | role `projections` is in `NS_WORKER_ROLES` (env); no thresholds exposed | `projections/catalog/handler.py` consumes outbox `SINK_CATALOG`; `factories.py:365-382`; 99 worker tests pass (in-memory). Writes edges only: it never creates the Agent entity those edges point at |
| Versioning, ETag concurrency, aliases, canonical IDs | NS-02 | PRP-10 items 0-1 | WORKS (in-memory) | not configurable (by design) | catalog_api tests; `catalog/router.py:138-152` If-Match |
| Curated relationships (accept/reject/override/lock) | NS-02 | PRP-10 item 4, PRP-31 item 4 | PARTIAL | UI `/catalog/edge`; API `POST /catalog/curation/edges/{id}/decisions` | `catalog/curation/router.py:76`; page mock-verified only (PRP-31 audit) |
| Conflict items routed to review | NS-02/NS-04 | PRP-10 item 4 | MISSING (path is a dead end) | not configurable | conflicts are enqueued to a separate `ReviewQueue` (`handler.py:195`, `curation/service.py:345`); `list_open`/`resolve` have no caller in `services/api`; the `/review` UI reads the HITL store, not this queue, so a relationship conflict never reaches a reviewer |
| Deprecation and ownership recertification | NS-02 | PRP-10, PRP-31 item 3 | PARTIAL | UI `/catalog/entity`, `/catalog/recertifications` | `catalog/router.py:194,211,322`; the reason typed in the dialog is not stored (PRP-31 completion note) |
| Stale-agent reconciliation | NS-02 | PRP-10, PRP-31 item 3 | PARTIAL | UI `/catalog/stale-agents` (dry-run then confirm) | `router.py:338,344`; window is a UI field; real "last seen" depends on telemetry having reached the catalog |
| Export | NS-02 | PRP-10 | PARTIAL | API `GET /catalog/export`; PRP-31 listed an export download in the UI | `router.py:303`; I found no export control in the catalog feature (UNVERIFIED in browser) |
| Grant and MCP server publication | NS-02/NS-09 | PRP-34 (backlog, order 2), PRP-22 shipped | PARTIAL | UI `/catalog/publication`, `/mcp-admin` | `catalog/grant_publish.py`, `mcp_publish.py`, `hooks.ts:38-53`; needs a real APIM/Foundry target (live gate), not run here |
| Recommendation generation | NS-03 | PRP-15 `backlog` (PR #79 merged) | PARTIAL: rules real, input is sandbox files | env/file: `NS_WORKER_REC_DATA_DIR`, `NS_WORKER_REC_PAIRS_FILE`, `NS_WORKER_REC_INTERVAL_SECONDS` | `factories.py:595-630`; `recommendations/pipeline.py`; reads `agents.ndjson`, `relations.ndjson`, `telemetry.ndjson`, `cost.ndjson` (`rules/sandbox_source.py:1-10`) |
| Recommendations list/detail/review request | NS-03 | PRP-15 | WORKS (in-memory) / hosted: empty | UI `/recommendations`; no rule thresholds in UI | recommendations tests pass; `recommendations/router.py:79-142`; refuses execution with 409 (`router.py:141`) |
| Right-sizing / model swap recommendations | NS-03 | PRP-15, PRP-17 | PARTIAL | file only: `NS_WORKER_REC_PAIRS_FILE` JSON; without it produces nothing | `settings.py:111-113` |
| Duplicate-agent detection | NS-03 | PRP-15 | PARTIAL | file/env | `recommendations/duplicates/*`; loads an in-memory copy of the sandbox catalog (`pipeline.py` docstring item 2), not the live Cosmos catalog |
| Evaluation / quality (what runs) | NS-03 | PRP-16 `backlog` (PR #81 merged) | MOCK-ONLY for any customer, PARTIAL for engine | env/file: `NS_WORKER_EVAL_DATA_DIR` with `datasets.json`, `rubrics.json`, `judge_configs.json`, `judge_fixtures.json` | `factories.py:682-745`; the only judge is `RecordedFixtureJudge` (`factories.py:77,689`); no live LLM judge exists (`core/evaluation/judge.py:1-8`; PRP-16 completion note: "No model-inference SDK is a dependency") |
| Evaluation suites, rubrics, datasets, judge config | NS-03 | PRP-16 | MISSING in UI and API | file only | evaluation API is read-only: `GET .../results`, `GET .../quality` (`evaluation/router.py`); no create/run route anywhere |
| Quality and evaluations pages | NS-03 | PRP-16, PRP-31 item 8 | PARTIAL | UI read only (`/quality`, `/evaluations`) | pages fed by `/api/v1/evaluation/...`; mock server `frontend/tests/mock-api/server.ts:648-789` |
| Human-label calibration and drift alerts | NS-03 | PRP-16 item 3 | PARTIAL (engine only) | file only | `core/evaluation/calibration/`; human labels have no input path other than files |
| HITL review queue: list, assign, decide | NS-04 | PRP-17 `shipped` (#173) | WORKS (in-memory) | UI `/review`, `/review/item` | `hitl/router.py:66-119`; hitl_api tests pass |
| HITL item creators | NS-04 | PRP-17 | PARTIAL | n/a | only two callers of `open_item`: actions (`actions/service.py:305`, kind `maker_checker`) and recommendation review (`recommendations/review_hitl.py:78`). Kinds `relationship`, `evaluation_dispute`, `policy_exception` have no producer |
| SLA, escalation, expiry timers | NS-04 | PRP-17 | WORKS (in-memory, 99 worker tests incl. hitl_timers) | not configurable: `ReviewPolicyRegistry()` hardcoded defaults (SLA 24h, assignment 4h, escalation step 8h, max 2, expiry 7d) in `core/hitl/policy.py:37-70`, constructed with no arguments at `runtime/builders/data.py:377` and `factories.py:451` | worker role `hitl_timers` runs under `NS_WORKER_ROLES` |
| Notifications | NS-04 | PRP-17 clarification 6 | MISSING (stub) | not configurable | `core/hitl/notify.py:1-10`: stubs only record an audit entry, import no network library; no email/Teams delivery |
| Reviewer routing and scope | NS-04 | PRP-06, PRP-17 | WORKS (in-memory) | IaC/identity: Entra app roles; no UI | `hitl/service.py:67`, `ports.py` |
| Maker-checker approval and self-approval ban | NS-04 | PRP-17 | WORKS (in-memory) | not configurable per policy; default forbids | `policy.py:38`, default table |

## 2. Per-capability notes

### 2.1 How a brand-new customer gets their real agents into the catalog (key question 1)

Three ways exist, none of them is "connect my Foundry project and see my agents".

1. API: `POST /api/v1/catalog/entities` (one entity), `POST /api/v1/catalog/import` (bulk, with dry-run), both need the catalog-curate permission (`catalog/router.py:182,287`). The caller must already know the canonical ID format `cloud:customer:source:type:id` and hand-build the entity body. No page calls these (PRP-31 Clarification 6 deferred "Create / edit / bulk import" and the 2026-11-04 audit in the PRP confirms "catalog create/edit/import UI ... never built").
2. Seed script: `scripts/sandbox/sbx_seed_stack.py` writes synthetic entities with `create_entity`. Demo only.
3. Edges from telemetry: the `projections` worker creates INVOKES / USES_MODEL / DELEGATES_TO edges from archived trace events (`projections/catalog/handler.py`, mapping in `mapping.py`). It writes edges and observations, not the Agent / Model / Tool entities themselves. I found no code path that mints an Agent entity from an unseen `external_agent_id`. So telemetry from an agent nobody registered produces edges that point at entities that do not exist. UNVERIFIED end to end (no emulator run); this is from reading `handler.py` and grepping `put_entity|create_entity` across `services/`, `packages/`, `connectors/`, `scripts/` (only the API service, the seed script and the recommendations pipeline's in-memory loader call it).

The Foundry discovery connector (`connectors/reference/foundry`) lists agents and model deployments, but it is a library with tests only; `grep` for `FoundryDiscoveryConnector` in `services/` and `packages/` returns nothing. The APIM connector's `arm.py` mentions catalog entities for gateways (PRP-33/34 scope, covered by another lane).

Answer: a new customer cannot populate the catalog with real agents without hand-writing JSON and calling the API (or running the seed script, which only knows synthetic data).

### 2.2 What produces a recommendation today (key question 2)

Chain: worker role `recommendations` (`runtime/roles.py`, part of `all`) -> `build_recommendations` (`factories.py:595`) -> `run_pipeline(data_dir, ...)` (`recommendations/pipeline.py`) -> `RecommendationStore.put` (Cosmos) -> API `GET /api/v1/recommendations/domains/{d}` -> `/recommendations`.

- Input is a directory of NDJSON files in the sandbox layout (`agents.ndjson`, `relations.ndjson`, `telemetry.ndjson`, `cost.ndjson`), read through `SandboxSeriesSource`. Not the live Cosmos aggregates, not the ledger, not the live catalog. A customer's real telemetry (ingested via `/v1/ingest/...` into archive/aggregates/ledger) is never read by this role. `build_recommendations` raises `RoleConfigError("recommendations_data_dir_missing")` if `NS_WORKER_REC_DATA_DIR` is unset (`factories.py:597-600`).
- Rules: cost spike, latency, error rate, unused agent (`rules/`); duplicate candidates (`duplicates/`); right-sizing projections from a pairs file (`projection/`). All bounded rules, no ML. PRP-15 D5 (operator sign-off) records latency detection at 0/5 at pilot density.
- Hosted Azure demo: `infra/demo/main.bicep:236-242` runs only `ingestion,projections,aggregates,actions,hitl_timers,lifecycle`, with the comment "Hosted recommendations and evaluations are written by the seeder instead". So in the hosted environment no recommendation is computed at all, whatever is in the store was seeded.
- Compose: `docker-compose.yml:198-212` runs `all` with `NS_WORKER_REC_DATA_DIR=/data/sandbox`, i.e. synthetic.

Consequence: recommendations are real code over synthetic input. The API and page are WORKS in the sense that they list what is in the store; where the store content comes from for a real customer is MISSING.

### 2.3 Backlog PRPs 10, 15, 16 versus the pages that exist (key question 3)

| PRP file location | Tracker | What the product has | What is behind it |
|---|---|---|---|
| `PRPs/backlog/PRP-10` | backlog, `pr: 52`, all 8 execution items "merged", G03 live evidence "filed 2026-10-17" | `/catalog*` (6 routes), `/catalog/edge`, via PRP-31 | real routers over `CatalogRepository` (Cosmos in production composition: `runtime/builders/data.py:205-220`); search needs provider |
| `PRPs/backlog/PRP-15` | backlog, `pr: 79` | `/recommendations`, `/recommendations/detail` | `RecommendationStore`; fed by the sandbox-file worker |
| `PRPs/backlog/PRP-16` | backlog, `pr: 81` ("PR #81 merged as b0a2a2b" in its own completion note) | `/quality`, `/evaluations` | `EvaluationStore` (`app.state.evaluation_store`, `data.py:300-304`); fed by worker with recorded-fixture judge over archive spans |
| `PRPs/backlog/PRP-31` | backlog, `pr: 150` merged, "Reopened after a deep audit" | 12 routes | mock-verified; "No page has ever run against the real API" |

All four have the product code merged; their files remain in `backlog/` and PRPs/INDEX.md lists them as backlog with `depends_on: -`. The PRP-16 completion note's follow-up says the Cosmos `EvaluationStore` and production bootstrap were pending; `runtime/builders/data.py:300` now builds the store, so that follow-up looks done by PRP-35/29 (UNVERIFIED against a live Cosmos).

### 2.4 Evaluation: what actually runs (part of key question 2)

- Online evaluation worker: `build_evaluation` (`factories.py:682`) loads `datasets.json`, `rubrics.json`, `judge_configs.json` from `NS_WORKER_EVAL_DATA_DIR` and creates `RecordedFixtureJudge.from_file(directory / "judge_fixtures.json")`. A request with no recorded fixture raises (`core/evaluation/judge.py:3-5`). So the "judge" replays canned answers. There is no live judge client anywhere, and the PRP-16 note says the live judge gate is OPEN (`scripts/gates/g16_judge_live.py` exits 3).
- Even with a live judge, PRP-16 D2 states the archive drops prompt/response bodies, so online evaluation scores only metadata-derivable dimensions.
- The scoring, budget, restricted-content, calibration and drift code is real and unit-tested (workers `evaluation_worker` tests pass, in-memory).
- No route creates or runs a suite. `evaluation/router.py` has two GET routes.
- Hosted Azure: `evaluation` role not started (`main.bicep:242`).

### 2.5 HITL: what it needs configured (key question 4)

- Items come from: maker-checker action proposals (PRP-17 executor) and recommendation "route to review". Nothing else calls `open_item`. The relationship-conflict items from the projection/curation paths go to `catalog_review_queue`, which no API route lists, so that review stream has no UI. Evaluation disputes and policy exceptions have no producer.
- Reviewers: need the approver permission (`action.approve` for maker-checker, `catalog.curate` for insight kinds) in the item's domain, from Entra app roles. Assign/decide is in the UI.
- Policy (SLA, escalation, expiry, assignment timeout, self-approval) is code defaults: `ReviewPolicyRegistry()` is built with no arguments in the API (`data.py:377`) and workers (`factories.py:451`). There is no setting, file, route or page to change it. PRP-31's own table says "SLA / notification configuration: no API, deferred".
- Timer worker role `hitl_timers` must be running (it is in the hosted demo roles list).
- Notifications are audit-record stubs. Nobody receives an email or Teams message.
- Pre-conditions for the queue to function: `hitl` and `review_router` components `ok` in composition (`runtime/builders/planes.py`, `data.py:478`).

## 3. What an operator cannot do today

- Connect a Foundry project or any other source and have its agents, models and tools appear in the catalog. Discovery code exists but is not run by anything.
- Create, edit or import a catalog entity from the UI. They can only call the API or edit a seed script.
- See an Agent show up in the catalog just because telemetry from it was ingested (edges are written, entities are not) UNVERIFIED end to end.
- Get a recommendation computed from their own ingested telemetry and cost. The rules read sandbox files, and on the hosted environment the role is not even started.
- Define an evaluation suite, dataset, rubric or judge in the product, or trigger a run, or get a real LLM judge. Only a files-in-a-directory recorded-fixture replay exists.
- Change any HITL timing, escalation, expiry or approver rule, or have a reviewer notified by email or Teams.
- Review relationship conflicts raised by inference or curation: no UI reads that queue.
- Raise an evaluation dispute or a policy exception for review: no creator exists.
- Set recommendation rule thresholds or pairings in a UI. Pairings are a JSON file (`NS_WORKER_REC_PAIRS_FILE`).
- Store a reason on deprecate or recertify (the UI collects it and discards it).

## 4. Contradictions between "shipped/backlog" status and reality

1. PRP-10, 15, 16 and 31 sit in `PRPs/backlog/` and in the INDEX backlog table with no dependencies, yet their PRs (#52, #79, #81, #150) are merged and their execution tables say "merged". The tracker will propose them as "next PRP" again. Either they are closed in the tracker or they should be reopened for what is genuinely not built; today the status says neither.
2. PRP-17 is `shipped` with the notification and policy-administration pieces recorded as stubs and "no API". Shipped here means "state machine and workers exist", not "an operator can run an approval program".
3. PRP-31's goal is "all functionality built is true in the product". Its own audit section says no page ever ran against the real API and create/import UI was never built.
4. PRP-15 and 16 criteria are phrased as "Given the sandbox...". They are satisfied for synthetic data. The PRD wording (cost spikes, groundedness over a customer's agents) is not satisfied for real data.
5. PRP-10 item 4 "a conflicting inference lands in the review queue" holds literally (it lands in `catalog_review_queue`) but the PRD NS-04 requirement "route low-confidence relationships to scoped reviewers" does not, because no reviewer surface reads that queue.

## 5. Open questions (could not answer)

- Does the Cosmos-backed catalog list/search work in the running stack with the projections worker creating edges, and what does `/catalog` show for telemetry from an unregistered agent? Needs the orchestrator's stack.
- Is there an export control in the catalog UI? I found none in `features/catalog`; PRP-31 says item 3 includes a download. Needs a browser check.
- Does the hosted seeder ("recommendations and evaluations are written by the seeder instead", `main.bicep:239`) cover real tenants or only the demo tenant? I did not locate the seeder.
- Whether `catalog_review_queue` items are surfaced anywhere I missed (I grepped `services/api`, `services/workers`, `packages/core` for `list_open` and `.resolve(` on the queue and the frontend `features/review` for kinds; no consumer found).
