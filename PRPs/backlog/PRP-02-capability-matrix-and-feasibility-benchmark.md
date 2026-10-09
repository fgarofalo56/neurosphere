---
name: prp-02-capability-matrix-and-feasibility-benchmark
status: backlog
review: required
created: 2026-10-08
model: sonnet
phase: 0
ns: NS-07, NS-08
depends_on: PRP-01
wave: W2
absorbs: P0.1, P0.2 ADR/benchmark, G01, G03
---

# PRP-02: Capability matrix and feasibility benchmark

## Goal

Ship two Phase 0 evidence products. First, a dated, source-cited capability matrix (service, feature, cloud, region, SKU, availability, GA status, authorization scope) with a loader and `validate_profile()` that makes unsupported cloud, region and feature combinations come back as "disabled with reason" instead of being guessed. Second, a Cosmos DB partition and traversal benchmark harness that runs against the emulator now (labelled bounded feasibility only) and against a real Commercial account later through an operator-approved script, plus three ADRs that cite both. The audience is PRP-08 (deployment intelligence), PRP-10 (catalog, which cannot merge until the live benchmark exists), PRP-11 (analytics adapters) and every UI that renders a disabled option. It runs now because deployment choices and the catalog store decision depend on facts, not memory, and because the 2026-10-08 research already supplies the first rows.

Requirement text fulfilled, quoted from `docs/PRD.md`:

> At deployment choose Commercial or Government, approved region(s), AKS enterprise or App Service smaller profile, and Fabric/Synapse/Azure Databricks analytics backend where validated. Show unavailable options disabled with reasons; never route Government telemetry to Commercial to fill a gap. (NS-07)

> Service availability, feature GA and authorization are distinct verification items. (NS-08)

> NeuroSphere is not FedRAMP authorized and cannot grant an agency ATO. Azure Government, GCC/GCC High and DoD impact levels are not interchangeable. (NS-08)

PRD section 4 adds: "Production deployment requires approved service/feature/region/SKU matrix ... Record these customer-specific inputs; do not silently select them."

## Acceptance criteria

- [ ] Item 1: Every matrix row has a source URL and an observed date; the services Foundry, Fabric, Synapse, Databricks, Cosmos, APIM, Search, Event Hubs and Resource Graph each have at least one row; `availability`, `ga_status` and `authorization_scope` are separate columns; Fabric Government rows say GCC High GA in US Gov Virginia and US Gov Texas only, with GCC and DoD marked `unverified`.
- [ ] Item 2: Given a Commercial profile and a Government profile fixture, when `validate_profile()` runs, then supported combinations pass and each unsupported one returns `capability_unavailable` with a human-readable `reason` and the row id; an unknown combination returns `unverified`, never `supported`.
- [ ] Item 3: The harness produces evidence JSON and Markdown under `docs/evidence/G03/` labelled "emulator, bounded feasibility"; bounded-traversal p95 is recorded for three workloads (skewed partition, high-degree node, cross-domain) with run parameters and emulator version.
- [ ] Item 4: ADR-0005, ADR-0006 and ADR-0007 exist; each cites matrix row ids and G03 evidence file paths; none claims the emulator proved RU cost or index behaviour.
- [ ] Item 5: `scripts/gates/g03_live.py` exits non-zero without `NS_LIVE_APPROVED=1` before opening any network connection (tested); with approval it writes `docs/evidence/G03/live-<date>.md`.
- [ ] PRP exit: `verify-gates -Mode full` green; `python scripts/validate_planning.py` clean for this file; the completion note states G01 and G03 as OPEN or NARROWED exactly as evidence allows; the live G03 run is recorded as OPEN until the operator approves it (required before PRP-10 merges).

## Clarifications (decided)

| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| 1 | Where does emulator G03 evidence sit (D9) | emulator exits Phase 0; live before wave 4 | The emulator run EXITS Phase 0 as bounded feasibility. The live Commercial run is required before PRP-10 merges; item 5 builds the script, PRP-10 item 7 runs it. |
| 2 | Commercial subscription (D7) | per-PRP approval; none | Available; each live run needs explicit operator approval and `NS_LIVE_APPROVED=1`. This PRP builds the script but does not run it unless the operator approves in-session. |
| 3 | Local dev stack (D8) | compose; fakes | Docker Compose emulators from `docker-compose.yml`. Benchmark targets the Cosmos vNext emulator on port 8081 via the existing compose service. |
| 4 | Model policy (D6) | Sonnet; Opus | Sonnet; review required. |
| 5 | Matrix file format | YAML; JSON; Python | YAML files under `packages/core/neurosphere_core/capabilities/data/`, validated against `CapabilityMatrixEntry` from PRP-01 (item 5 there). One file per service. |
| 6 | Row granularity | per service; per feature-region-SKU | One row per (service, feature, cloud, region or `*`, sku or `*`). Region wildcard only when the source states it. |
| 7 | Status vocabulary | free text; enum | `availability`: available, preview, unavailable, unverified. `ga_status`: ga, preview, not_applicable, unverified. `authorization_scope`: free-form citation of audit-scope document or `none_claimed`; never a claim that NeuroSphere is authorized. |
| 8 | Fabric Government rows | single row; per region | Separate rows: GCC High US Gov Virginia and US Gov Texas (available, GA 2026-10-01); GCC and DoD `unverified`; unsupported items in GCC High (customer-managed keys, workspace identity, Fabric IQ items) as `unavailable` feature rows. |
| 9 | Matrix freshness | static; staleness check | Each row has `observed_on`. `validate_profile()` adds a `stale` warning when a row is older than 90 days; staleness never turns a row into `supported`. |
| 10 | Conflicting sources | pick favourable; keep both | Keep both rows with their sources and mark `unverified`, per the RESEARCH-AND-GATES rule to resolve with current evidence rather than choose the most favourable statement (Foundry region page versus feature-specific page). |
| 11 | Benchmark workloads | many; three | Three: (a) skewed partition (hot domain), (b) high-degree node fan-out, (c) cross-domain traversal. Each bounded by depth, fan-out and time budgets from the `Budget` contract. |
| 12 | Benchmark metric on emulator | RU; latency | Latency distribution and bounded-result correctness only. RU is not available on the vNext emulator and must not appear in emulator evidence. |
| 13 | Graph engine | Gremlin; Neo4j; Cosmos NoSQL adjacency | ADR-0005 evaluates Cosmos NoSQL adjacency (default per PRP.md section 2) against Neo4j (optional deep-graph adapter, not an automatic Government fallback). Gremlin is out unless the benchmark and limits page change the answer. |
| 14 | Partition key shape | decide here; decide in PRP-10 | Benchmark parametrizes it (hierarchical keys up to 3 levels need azure-cosmos >= 4.6 and new containers); the decision is recorded in ADR-0005 as provisional until the live run. |
| 15 | Government evidence | fabricate; mark open | No Government subscription exists. All Government rows are documentation-derived and G01 and G02 stay OPEN for Government. |
| 16 | Edits to `docs/RESEARCH-AND-GATES.md` | any; owned rows | Item 3 owns the G03 row text and item 1 owns the G01 row text; both edit only their row, sequenced. |

## Context manifest

### Files that matter

- `PRP.md` - section 2 (Cosmos NoSQL adjacency, Neo4j optional, analytics adapters), section 3.
- `docs/PRD.md` - NS-07 and NS-08 text; section 4 release gates.
- `docs/ARCHITECTURE.md` - deployment and sovereign profile diagram (section 4), data model (section 6).
- `docs/RESEARCH-AND-GATES.md` - the 2026-10-06 and 2026-10-08 findings that seed rows; G01, G03, G12 rows.
- `docs/DECISIONS-LOG.md` - D7, D8, D9.
- `docs/adr/0002-stack-pins.md` - emulator licences and limits, azure-cosmos 4.17, azure-identity 1.26.
- `docker-compose.yml` - existing `cosmos` (vNext emulator, port 8081, http), `azurite`, `eventhubs` services; do not edit here (PRP-03).
- `infra/compose/eventhubs.config.json` - namespace `neurosphere-local`, hubs `telemetry` (4 partitions, groups `normalizer`, `aggregates`) and `quarantine` (1 partition, group `replay`).
- `pyproject.toml` (root) - markers `live` and `integration`; ruff and pyright.
- `.claude/hooks/config.ps1` - gate commands.
- `scripts/validate_planning.py` - validator.
- `.env.example` - template only; never read `.env`.
- Created by PRP-00: workspace members `packages/core` (`neurosphere_core`), `services/api`, `services/workers`; created by PRP-01: `packages/contracts/schemas/deployment/v1/` (CapabilityMatrixEntry), `.../errors/v1/` (error taxonomy), `.../query/v1/` (Budget), and generated `neurosphere_contracts` models.

### Patterns to match

No product code exists yet, so these are rules, not file references.

- Pydantic v2 models with `model_config = ConfigDict(extra="forbid")`; use the generated contract models from PRP-01, do not redefine them.
- FastAPI routers per module under `services/api/neurosphere_api/<module>/router.py` (not used here; the capabilities package is library code in `packages/core`).
- Async Azure SDK clients from `packages/core/neurosphere_core/clients` (created by PRP-05; the benchmark harness uses `azure-cosmos` directly with a local seam and does not wait for PRP-05).
- Error taxonomy exceptions from `neurosphere_core.errors` (PRP-05); until then `capability_unavailable` is produced as the contract error model from PRP-01.
- Tests beside packages plus cross-package suites in `tests/` (`tests/unit/capabilities/`, `tests/load/graph_benchmark/`).
- `pytest.mark.live` and `pytest.mark.integration` markers (declared in root `pyproject.toml`); benchmark emulator runs are `integration`, the live script is `live`.
- TypeScript strict with `@fluentui/react-components`; Vitest + Testing Library; Playwright under `frontend/tests/e2e` (not used here).

### Conventions

- ruff config in root `pyproject.toml`: line length 100, py312, `S` rules on; pyright standard.
- Conventional commits; commit scoped changes only after review; ask before push or deployment.
- Owned-file discipline; shared files are sequenced.
- Evidence under `docs/evidence/<gate>/` with the date in the filename; live scripts under `scripts/gates/` refuse without `NS_LIVE_APPROVED=1`.
- Every number in evidence carries its run parameters; planning targets from the PRD are cited as targets, never as results.
- Forward slashes in commands; Python is `python`; temp output goes to `./temp/`.

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
- PRP-02 specific: Fabric in GCC High is GA (2026-10-01) in US Gov Virginia and US Gov Texas only. GA is not authorization: FedRAMP High assessment is in progress. Do not write `authorization_scope` text that implies otherwise.
- PRP-02 specific: Azure AI Search semantic ranker, agentic retrieval and query rewrite exist in US Gov Arizona and Virginia, NOT Texas; Government vector search availability is not stated on the regional table, so it is `unverified`.
- PRP-02 specific: Event Hubs data geo-replication is GA on Premium and Dedicated only; Government support is `unverified`. Metadata geo-DR is a separate row and copies neither payloads nor RBAC.
- PRP-02 specific: the Foundry region-support page and the Government roadmap conflict with the feature-specific Government page. Record all, mark `unverified`, link all sources (Clarification 10).
- PRP-02 specific: the vNext Cosmos emulator accepts any key and enforces no auth; a benchmark that "passes" there says nothing about RU, throttling (429), cross-partition fan-out cost or index policy. Output must not contain RU numbers.
- PRP-02 specific: hierarchical partition keys apply to new containers only and need azure-cosmos >= 4.6; the benchmark must create fresh containers, never reuse.
- PRP-02 specific: the Event Hubs emulator has no persistence across restarts; nothing in this PRP depends on retained events.
- PRP-02 specific: the live script must check `NS_LIVE_APPROVED` as its first statement, before reading any config or opening a client, and must take its account endpoint from the environment (never a literal) with auth through managed identity or `DefaultAzureCredential`, no keys on the command line.

### External references

Observed 2026-10-08 unless stated (from `docs/RESEARCH-AND-GATES.md`):

- Fabric in GCC High: https://learn.microsoft.com/fabric/enterprise/us-government-community-cloud-high and https://www.microsoft.com/en-us/microsoft-cloud/blog/us-government/2026/09/02/microsoft-fabric-in-gcc-high-building-the-data-foundation-for-ai/
- Azure Government FedRAMP High / DoD audit scope (Synapse, Databricks, Resource Graph; updated 2026-09-21): https://learn.microsoft.com/azure/azure-government/compliance/azure-services-in-fedramp-auditscope
- Azure AI Search regions (2026-10-01): https://learn.microsoft.com/azure/search/search-region-support
- Foundry models in Azure Government (2026-09-01): https://learn.microsoft.com/azure/foundry/foundry-models/concepts/models-sold-directly-by-azure-gov
- Foundry Agent Service in Government: https://learn.microsoft.com/azure/foundry/agents/concepts/azure-government
- Foundry platform in Government (2026-10-06): https://learn.microsoft.com/azure/foundry/concepts/foundry-azure-government
- Foundry region support and Government roadmap, conflicting (2026-10-06): https://learn.microsoft.com/azure/foundry/reference/region-support and https://learn.microsoft.com/azure/azure-government/documentation-government-product-roadmap
- Event Hubs data geo-replication (2026-07-11): https://learn.microsoft.com/azure/event-hubs/geo-replication
- Event Hubs metadata geo-DR (2026-10-06): https://learn.microsoft.com/azure/event-hubs/event-hubs-geo-dr
- Event Hubs emulator (2026-08-26): https://learn.microsoft.com/azure/event-hubs/overview-emulator
- Cosmos vNext Linux emulator (GA June 2026): https://learn.microsoft.com/azure/cosmos-db/emulator-linux
- Cosmos hierarchical partition keys (2026-04-27): https://learn.microsoft.com/azure/cosmos-db/hierarchical-partition-keys
- Cosmos change feed modes (2026-06-17), why projections use an outbox: https://learn.microsoft.com/azure/cosmos-db/change-feed-modes
- Gremlin limits and partitioning (2026-10-06): https://learn.microsoft.com/azure/cosmos-db/gremlin/limits and https://learn.microsoft.com/azure/cosmos-db/gremlin/partitioning
- APIM: no row source yet in the research register; item 1 must fetch and cite the first-party APIM Government availability page itself, dated at fetch time, or mark the row `unverified`.

## Implementation blueprint

### Item 1 — matrix-data  [P]
- Deliverable: YAML matrix files, one per service (Foundry, Fabric, Synapse, Databricks, Cosmos, APIM, Search, Event Hubs, Resource Graph), validated against `CapabilityMatrixEntry`. Seed rows from the 2026-10-08 findings: Fabric GCC High (GA, US Gov Virginia and Texas; CMK, workspace identity and Fabric IQ unavailable; GCC and DoD unverified; FedRAMP High assessment in progress); Synapse and Databricks in Government audit scope (Databricks US Gov Virginia and Arizona); AI Search Government (audit scope; semantic ranker, agentic retrieval, query rewrite in Arizona and Virginia not Texas; vector search unverified); Foundry Government models (usgovvirginia and usgovarizona, Data Zone Standard: gpt-5.x family, gpt-5.1, gpt-4.1 and mini with 128K context cap, o3-mini, gpt-4o, text-embedding-3; Regional Standard lacks gpt-5.1 and o3-mini) and Agent Service features (prompt agents, AI Search, MCP servers, function calling available; workflows preview; hosted agents, web search, Bing grounding, Fabric tool and agent-to-agent unavailable); Event Hubs data geo-replication (GA Premium and Dedicated only, Government unverified) and metadata geo-DR; Cosmos NoSQL (hierarchical partition keys, all-versions-and-deletes change feed preview); Resource Graph Government in audit scope; plus the conflicting Foundry region rows.
- Owned files (may edit): `packages/core/neurosphere_core/capabilities/data/`, `docs/RESEARCH-AND-GATES.md` (G01 row only).
- Must NOT touch: `packages/core/neurosphere_core/capabilities/*.py` (item 2); `tests/` (items 2, 3); `docs/adr/` (item 4); `scripts/gates/` (item 5); `packages/contracts/` (PRP-01); `docker-compose.yml`; root `pyproject.toml`; any other row of `docs/RESEARCH-AND-GATES.md`.
- Depends on: none
- Acceptance criteria:
  - Every row has `source_url` and `observed_on`; a lint test (owned by item 2) fails on a row without them.
  - Fabric Government rows reflect GCC High GA in US Gov Virginia and US Gov Texas, with GCC and DoD `unverified`.
  - `availability`, `ga_status`, `authorization_scope` are distinct fields on every row; no row claims NeuroSphere or any dependency is authorized for an agency.
  - G01 row text updated to state what is now evidenced (documentation-derived) and what remains open (integration tests, Government authorization).
- Pattern references: ADR-0002 table style; RESEARCH-AND-GATES findings above.
- Tests to write: none in this item; item 2 validates the data.

### Item 2 — matrix-validator
- Deliverable: loader reading the YAML into contract models; `validate_profile(profile)` for a profile of cloud, region(s), hosting (aks|appservice), analytics backend and optional features; "disabled with reason" output suitable for the PRP-08 plan and UI; staleness warning.
- Owned files (may edit): `packages/core/neurosphere_core/capabilities/__init__.py`, `.../capabilities/loader.py`, `.../capabilities/validate.py` (code only), `tests/unit/capabilities/`.
- Must NOT touch: `packages/core/neurosphere_core/capabilities/data/` (item 1); other `neurosphere_core` subpackages (`errors`, `scope`, `paging`, `cloud` are PRP-05); contract schemas; `docs/RESEARCH-AND-GATES.md`.
- Depends on: item 1
- Acceptance criteria:
  - Commercial and Government fixture profiles: supported combinations pass; each unsupported one yields `capability_unavailable` with a `reason` naming the row id and source.
  - A combination with no row is `unverified` and is disabled, never silently enabled.
  - A Government profile can never resolve a Commercial endpoint or region (test).
  - Matrix rows missing `source_url` or `observed_on` fail loading.
- Pattern references: PRP-01 error taxonomy and `CapabilityMatrixEntry`; conventions.
- Tests to write: `tests/unit/capabilities/test_loader.py`, `test_validate_profile.py`, `test_government_isolation.py`, `test_row_lint.py`.

### Item 3 — cosmos-benchmark-harness  [P]
- Deliverable: parametrized benchmark under `tests/load/graph_benchmark/` that creates fresh containers (including hierarchical partition key variants), loads an adjacency data set (nodes and edges documents) for the three workloads, runs bounded traversals with depth, fan-out and time budgets, and writes evidence JSON and Markdown to `docs/evidence/G03/` labelled "emulator, bounded feasibility"; the same code takes an endpoint and credential mode parameter so item 5 can reuse it live.
- Owned files (may edit): `tests/load/graph_benchmark/`, `docs/evidence/G03/`, `docs/RESEARCH-AND-GATES.md` (G03 row only).
- Must NOT touch: `scripts/gates/` (item 5); `docs/adr/` (item 4); `packages/core/neurosphere_core/capabilities/` (items 1, 2); `docker-compose.yml` and `infra/compose/` (PRP-03); contract schemas; any other row of `docs/RESEARCH-AND-GATES.md`.
- Depends on: none
- Acceptance criteria:
  - `docker compose up -d --wait cosmos` then `uv run pytest tests/load/graph_benchmark -m integration` produces evidence JSON and Markdown.
  - Evidence records bounded-traversal p95 for the three workloads, run parameters (document counts, skew factor, budgets, SDK and emulator versions) and the label "emulator, bounded feasibility".
  - Evidence contains no RU figure and states that RU, index policy and throttling are unmeasured.
  - G03 row stays OPEN and states: emulator evidence done, live run required before PRP-10 merges (D9).
- Pattern references: PRP-01 `Budget` and catalog schemas for document shapes.
- Tests to write: `tests/load/graph_benchmark/test_benchmark_smoke.py` (marked integration), `test_evidence_format.py` (offline, validates the evidence writer).

### Item 4 — adrs
- Deliverable: ADR-0005 catalog store (Cosmos NoSQL adjacency versus Neo4j; status provisional pending live G03), ADR-0006 Event Hubs quarantine design (explicit container, replay CLI, checkpoint-after-durable rule, metadata-DR caveat), ADR-0007 analytics adapter contract (`TelemetryAnalytics` and `RecommendationCompute`, query budgets, Government gating via matrix).
- Owned files (may edit): `docs/adr/0005-catalog-store.md`, `docs/adr/0006-eventhubs-quarantine.md`, `docs/adr/0007-analytics-adapter-contract.md`.
- Must NOT touch: ADR-0002 and ADR-0004 (other PRPs); matrix data (item 1); evidence files (item 3); `docs/RESEARCH-AND-GATES.md`; `docs/DECISIONS-LOG.md`.
- Depends on: item 3 (needs evidence paths)
- Acceptance criteria:
  - Each ADR cites matrix row ids and the exact `docs/evidence/G03/` file names it relies on.
  - ADR-0005 marks the partition key decision provisional and names the live run as its closing evidence; it does not claim emulator results prove RU or index behaviour.
  - ADR-0006 states that Event Hubs has no built-in DLQ and that geo-DR metadata does not copy payloads or RBAC.
  - ADR-0007 lists which adapters are enabled per cloud strictly from matrix rows, with `unverified` rows disabled.
- Pattern references: `docs/adr/0002-stack-pins.md` structure (Status, Date, Deciders, Context, Decision, Consequences, References).
- Tests to write: none; `python scripts/validate_planning.py` and a link existence check in review.

### Item 5 — live-gate-script (operator approved)  [P]
- Deliverable: `scripts/gates/g03_live.py` re-running the item 3 benchmark against a real Cosmos DB account in the Commercial subscription; refuses without `NS_LIVE_APPROVED=1`; reads the account endpoint from the environment; writes `docs/evidence/G03/live-<date>.md` including measured RU and p95 for the three workloads. Required before PRP-10 merges (decision D9).
- Owned files (may edit): `scripts/gates/g03_live.py`, `tests/unit/gates/test_g03_live_guard.py`.
- Must NOT touch: `tests/load/graph_benchmark/` (item 3; import it, do not modify); `docs/evidence/G03/` files other than the generated `live-<date>.md`; `docs/RESEARCH-AND-GATES.md`; `docker-compose.yml`; contract schemas; other scripts.
- Depends on: item 3 (benchmark code to import); parallel with item 4 once item 3 merges, `[P]` per the decomposition
- Acceptance criteria:
  - Without `NS_LIVE_APPROVED=1` the script exits non-zero before any network call (unit test patches the socket layer and asserts zero calls).
  - With approval and a valid endpoint it writes the evidence file with an operator and date header, account SKU and region, and RU values.
  - No key or connection string is accepted as an argument or logged; auth is Entra via `DefaultAzureCredential` or a vault reference.
  - Running it is NOT part of this PRP's gates; the completion note records the live run as OPEN unless the operator ran it.
- Pattern references: conventions (live scripts); PRP-02 item 3 evidence format.
- Tests to write: `tests/unit/gates/test_g03_live_guard.py` (guard, no network, marked unit).

## Validation gates

```
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode fast    # per item
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full    # before merge
python scripts/validate_planning.py
```

Feature-specific commands:

```
uv run pytest tests/unit/capabilities -q
docker compose up -d --wait cosmos
uv run pytest tests/load/graph_benchmark -m integration -q
docker compose down
uv run pytest tests/unit/gates -q
python scripts/gates/g03_live.py     # operator-approved, requires NS_LIVE_APPROVED=1; expected to refuse without it
```

The last command is operator-approved and requires `NS_LIVE_APPROVED=1`; run without the variable it must exit non-zero, which is the guard test. The approved live run is not a merge gate for this PRP; it is a merge gate for PRP-10.

## Live and open gates

| Gate | Effect of this PRP |
|---|---|
| G01 service, feature, region, SKU matrix | NARROWED at best: documentation-derived dated rows exist. Stays OPEN for integration tests (PRP-08, PRP-11) and all Government authorization questions. |
| G03 graph partition and traversal benchmark | Emulator evidence exits Phase 0 (D9). The live run (item 5 script) stays OPEN until the operator approves it; blocks PRP-10 merge. |
| G12 emulator parity | Item 3 documents what the Cosmos vNext emulator cannot reproduce (RU, indexes, auth); gate stays OPEN. |
| G02 FedRAMP/DoD boundary | Untouched; matrix rows never claim authorization. |

If a live item did not run, record it OPEN in the completion note and in docs/RESEARCH-AND-GATES.md; never report it as a skipped green test.

## NOT building

- Catalog repository, graph query or any production Cosmos access code (PRP-10).
- Analytics adapters (PRP-11); only the ADR for the contract.
- Deployment plan generation and Resource Graph scanning (PRP-08); only the matrix it will consume.
- Any UI for disabled-with-reason options (PRP-04 and PRP-08).
- A Neo4j benchmark; Neo4j is evaluated on paper in ADR-0005 only.
- Government subscription tests; none exists and Government rows stay documentation-derived.
- Any cost, SLA or performance guarantee derived from emulator numbers.

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
- Matrix row count by service and cloud:
- Evidence paths (emulator run; live run if any):
- Open gates and follow-ups (G01, G03 live, G12):
