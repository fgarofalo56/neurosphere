---
name: prp-11-analytics-adapters
status: backlog
review: required
created: 2026-10-08
model: sonnet
phase: 2
ns: NS-01, NS-07
depends_on: PRP-02, PRP-07
wave: W5
absorbs: P2.1
---

# PRP-11: Analytics adapters

## Goal
Ship the `TelemetryAnalytics` and `RecommendationCompute` contracts with an in-process fixture adapter, and three vendor adapters (Microsoft Fabric, Azure Synapse, Azure Databricks) that implement the same contract, plus an equivalence and gating suite and an operator-approved live gate. It is for operators who must choose an analytics backend at deployment and for PRP-14/15/21, which consume aggregates without caring which backend runs. It lands in W5 because the capability matrix (PRP-02) says which adapters may be enabled and the ledger and outbox (PRP-07) produce the normalized input the adapters serve.

> Implement all three adapters to a shared capability/query contract, not identical vendor internals.

> At deployment choose ... Fabric/Synapse/Azure Databricks analytics backend where validated. Show unavailable options disabled with reasons; never route Government telemetry to Commercial to fill a gap.

> Separate durable ingestion, operational catalog and analytical serving; materialized hot aggregates prevent batch analytics from blocking the map.

Adapters are equivalent at the contract level, not identical in internals. The suite proves that identical normalized input yields equivalent aggregates within a documented tolerance; it does not prove identical SQL, plans or performance.

## Acceptance criteria
- [ ] Item 1: Given a query exceeding its time, row or cost budget, When the fixture adapter runs it, Then it cancels and raises `rate_limited`; budget fields are required on every request.
- [ ] Item 2: Fabric adapter passes the equivalence suite against a stub SQL endpoint; migrations are versioned and idempotent.
- [ ] Item 3: Synapse adapter passes the same suite; serverless and dedicated modes are selected by configuration.
- [ ] Item 4: Databricks adapter passes the same suite against a SQL warehouse stub.
- [ ] Item 5: Identical normalized input yields aggregates equal within the documented tolerance across fixture, Fabric, Synapse and Databricks; the Government profile enables only approved adapters; an unavailable adapter is visible and disabled with its reason.
- [ ] Item 6: `scripts/gates/g01_analytics_live.py` refuses without `NS_LIVE_APPROVED=1`; with approval it runs per adapter and writes evidence under `docs/evidence/G01/analytics/`.
- [ ] PRP exit: items 1-5 green under `verify-gates -Mode full`; item 6 evidenced per adapter or recorded OPEN per adapter.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|---|---|---|
| 1 | Model and review | sonnet/none; sonnet/required | sonnet, review required (D6) |
| 2 | Are all three adapters in scope | pick one; all three | All three behind one contract (PRD NS-07); the customer chooses among validated profiles. No ClickHouse, no standalone Kafka |
| 3 | What does "equivalent" mean | identical results; within tolerance | Aggregates (sum, count, quantile approximations, group-by) match within a stated tolerance; exact-match for counts and sums, documented tolerance for approximate quantiles. Tolerance is in code and in the suite docstring, not implied |
| 4 | Government enablement | all three; approved only | Only adapters the capability matrix marks approved for the selected Government region. Fabric in GCC High is GA in US Gov Virginia and Texas (observed 2026-10-08); Fabric customer-managed keys and workspace identity are unsupported there, GCC and DoD unverified. Synapse and Azure Databricks are in Azure Government FedRAMP High / DoD audit scope (Databricks in US Gov Virginia and Arizona). Availability is not authorization; none of this is an ATO claim |
| 5 | Disabled options | hide; show disabled with reason | Visible but disabled with reason string from the matrix; selecting one returns `capability_unavailable` |
| 6 | Live runs | CI; operator-approved | Operator-approved only (D7); Commercial subscription; each adapter's live run is independent and may stay OPEN individually |
| 7 | Local tests | emulators; stubs | In-process fixture plus recorded stub endpoints. There is no local Fabric, Synapse or Databricks emulator, so adapter tests are contract and stub tests; real behavior is evidenced only by item 6 |
| 8 | Migrations | ad hoc; versioned | Versioned, backward-compatible migrations per adapter, applied by a runner that PRP-13 later generalizes; this PRP ships the adapter-local scripts and tests on a fixture snapshot |
| 9 | Where compute runs | any; inside boundary | Inside the selected cloud boundary only; adapter config carries cloud and region and the adapter refuses mismatched endpoints (Government config with a Commercial host raises) |
| 10 | Unknown values | zero-fill; null | Missing metrics aggregate to unknown/null, never 0; the suite includes null-bearing fixtures |
| 11 | Scope | per-adapter filtering; shared | Every request carries `IdentityScope` and the same structured filter object; adapters translate it, they never accept query text |
| 12 | Budgets | advisory; enforced | Enforced per request (time, rows scanned, cost units); cancellation is tested |

## Context manifest

### Files that matter
- `PRP.md` - sections 1-3 (analytics via TelemetryAnalytics/RecommendationCompute capability contracts).
- `docs/PRD.md` - NS-01 (cost and envelope), NS-07 (analytics options), section 3 (hot aggregates, scale profiles).
- `docs/ARCHITECTURE.md` - analytical serving layer.
- `docs/RESEARCH-AND-GATES.md` - G01 row and the Fabric GCC High, Synapse and Databricks findings (retrieved 2026-10-08).
- `docs/adr/0002-stack-pins.md` - pins; no Fabric/Synapse/Databricks SDK is pinned there yet, so item owners add rows via PRP-00 process before adding dependencies.
- `docs/DECISIONS-LOG.md` - D6, D7, D8.
- `pyproject.toml`, `docker-compose.yml`, `.env.example`, `.claude/hooks/config.ps1`, `scripts/validate_planning.py`.
- Created by PRP-02: `packages/core/neurosphere_core/capabilities/` (matrix, `validate_profile()`), `docs/adr/0007-analytics-adapter-contract.md`, `scripts/gates/` conventions.
- Created by PRP-07: `packages/core/neurosphere_core/ledger/`, outbox and normalized event model, `tests/integration/ingestion/`.
- Created by PRP-01: telemetry, cost, scope, query schemas and generated types.
- Created by PRP-05: `neurosphere_core.errors`, `.../cloud/`, `.../clients/`.
- Consumed by PRP-14, PRP-15 (and PRP-21): the contract in `analytics/base/`.

### Patterns to match
- Protocols (`typing.Protocol`) in `analytics/base/`; one subpackage per adapter; adapters registered through a capability-gated factory.
- Pydantic v2 `extra="forbid"` for query requests, budgets, results; async clients via `neurosphere_core.clients`.
- Errors from `neurosphere_core.errors` (`rate_limited`, `capability_unavailable`, `dependency_transient`).
- Tests beside packages; shared equivalence suite parametrized over adapters in `tests/integration/analytics/`; `pytest.mark.integration` and `pytest.mark.live` markers.

### Conventions
- ruff line 100, py312, S rules on (no string-built SQL from caller input; parameterized statements only); pyright standard; conventional commits; owned-file discipline.
- Evidence under `docs/evidence/G01/analytics/`; live scripts refuse without `NS_LIVE_APPROVED=1`.
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
- PRP-specific: the adapters are equivalent at the contract level. Do not force vendor internals to match; do not add vendor-specific fields to the shared contract to make one adapter pass.
- PRP-specific: stub-based adapter tests prove contract conformance only. Never describe them as evidence that Fabric, Synapse or Databricks works in a given cloud or region; only item 6 live runs do.
- PRP-specific: Fabric in GCC High does not support customer-managed keys, workspace identity or Fabric IQ items; adapter feature flags must reflect that and the matrix must be the source.
- PRP-specific: a Government adapter configuration containing any Commercial hostname must fail at construction, not at first call.
- PRP-specific: approximate quantile functions differ across engines; compare with the documented tolerance, and compare counts and sums exactly.
- PRP-specific: new third-party SDK dependencies (Databricks SQL connector, ODBC drivers) may carry non-permissive licences or EULAs; add an ADR-0002 row and get operator approval before adding them.

### External references
- Fabric in GCC High: https://learn.microsoft.com/fabric/enterprise/us-government-community-cloud-high (observed 2026-10-08); announcement https://www.microsoft.com/en-us/microsoft-cloud/blog/us-government/2026/09/02/microsoft-fabric-in-gcc-high-building-the-data-foundation-for-ai/.
- Azure Government FedRAMP High / DoD audit scope for Synapse and Databricks: https://learn.microsoft.com/azure/azure-government/compliance/azure-services-in-fedramp-auditscope (updated 2026-09-21).
- Event Hubs data geo-replication (Premium and Dedicated; Government unverified): https://learn.microsoft.com/azure/event-hubs/geo-replication (2026-07-11), relevant to upstream feed assumptions.
- Cosmos DB change feed modes (why outbox feeds the analytics sink): https://learn.microsoft.com/azure/cosmos-db/change-feed-modes (observed 2026-06-17).
- ADR-0002 pins: docs/adr/0002-stack-pins.md (observed 2026-10-08).

## Implementation blueprint

### Item 1 - contracts-and-fixture-adapter  [P]
- Deliverable: `TelemetryAnalytics` and `RecommendationCompute` protocols, request/response/budget models, an in-process fixture adapter over normalized sandbox data, and budget/cancellation enforcement.
- Owned files (may edit): `packages/core/neurosphere_core/analytics/base/`, `packages/core/neurosphere_core/analytics/fixture/`.
- Must NOT touch: `packages/core/neurosphere_core/analytics/fabric/`, `.../synapse/`, `.../databricks/`, `packages/core/neurosphere_core/capabilities/`, `packages/core/neurosphere_core/ledger/`, `tests/integration/analytics/`, root `pyproject.toml`.
- Depends on: none.
- Acceptance criteria:
  - Budget exceeded raises `rate_limited` and cancels the in-flight work (test with a slow fake).
  - Requests without `IdentityScope` or budgets fail validation; no field accepts query text.
  - Unknown metrics return `unknown`, not 0.
- Pattern references: Protocols; Pydantic forbid-extra; errors taxonomy.
- Tests to write: `packages/core/tests/analytics/test_base_budgets.py`, `packages/core/tests/analytics/test_fixture_adapter.py`.

### Item 2 - fabric-adapter  [P]
- Deliverable: Fabric Lakehouse / SQL endpoint adapter and migrations implementing the base protocols.
- Owned files (may edit): `packages/core/neurosphere_core/analytics/fabric/`.
- Must NOT touch: `packages/core/neurosphere_core/analytics/base/`, other adapter packages, `packages/core/neurosphere_core/deploy/fabric/` (PRP-08 provisioning), `tests/integration/analytics/`.
- Depends on: Item 1.
- Acceptance criteria:
  - Passes the equivalence suite with the Fabric stub within the documented tolerance.
  - Rejects a configuration whose host does not match the selected cloud.
  - Migrations are versioned, idempotent, and tested on a fixture snapshot.
- Pattern references: base protocols; clients factory.
- Tests to write: `packages/core/tests/analytics/test_fabric_adapter.py`.

### Item 3 - synapse-adapter  [P]
- Deliverable: Synapse serverless and dedicated SQL adapter and migrations.
- Owned files (may edit): `packages/core/neurosphere_core/analytics/synapse/`.
- Must NOT touch: `packages/core/neurosphere_core/analytics/base/`, other adapter packages, `tests/integration/analytics/`.
- Depends on: Item 1.
- Acceptance criteria:
  - Passes the equivalence suite with the Synapse stub; mode (serverless or dedicated) selected by config.
  - Cloud and host mismatch rejected at construction.
  - Migrations versioned and idempotent.
- Pattern references: base protocols; clients factory.
- Tests to write: `packages/core/tests/analytics/test_synapse_adapter.py`.

### Item 4 - databricks-adapter  [P]
- Deliverable: Azure Databricks SQL warehouse adapter and migrations.
- Owned files (may edit): `packages/core/neurosphere_core/analytics/databricks/`.
- Must NOT touch: `packages/core/neurosphere_core/analytics/base/`, other adapter packages, `tests/integration/analytics/`.
- Depends on: Item 1.
- Acceptance criteria:
  - Passes the equivalence suite with the warehouse stub.
  - Credentials via vault references only; none logged.
  - Cloud and host mismatch rejected at construction; migrations versioned and idempotent.
- Pattern references: base protocols; clients factory.
- Tests to write: `packages/core/tests/analytics/test_databricks_adapter.py`.

### Item 5 - equivalence-and-gating-suite
- Deliverable: shared suite that feeds identical normalized input to every adapter and compares aggregates, plus gating tests for Commercial and Government profiles.
- Owned files (may edit): `tests/integration/analytics/`.
- Must NOT touch: `packages/core/neurosphere_core/analytics/` (any subpackage), `packages/core/neurosphere_core/capabilities/`, `tests/integration/ingestion/` (PRP-07), `tests/integration/deploy/` (PRP-08).
- Depends on: Items 2, 3, 4.
- Acceptance criteria:
  - Identical normalized input yields aggregates equal within the documented tolerance (exact for counts and sums) across all adapters.
  - Government profile fixture enables only matrix-approved adapters; an unavailable adapter is listed disabled with the matrix reason and selecting it returns `capability_unavailable`.
  - Null-bearing fixtures aggregate to unknown, never 0.
- Pattern references: `validate_profile()` from PRP-02; parametrized pytest.
- Tests to write: `tests/integration/analytics/test_equivalence.py`, `tests/integration/analytics/test_profile_gating.py`.

### Item 6 - live-gate (operator approved)
- Deliverable: script that runs the equivalence workload against a real backend per adapter in the Commercial subscription and writes per-adapter evidence.
- Owned files (may edit): `scripts/gates/g01_analytics_live.py`, `docs/evidence/G01/analytics/`.
- Must NOT touch: `scripts/gates/g01_deploy_smoke.py` and `docs/evidence/G01/` outside `analytics/` (PRP-08), `docs/RESEARCH-AND-GATES.md`, `tests/integration/analytics/`.
- Depends on: Item 5.
- Acceptance criteria:
  - Exits non-zero with a clear message without `NS_LIVE_APPROVED=1`.
  - With approval, runs only the adapters named on the command line and records tolerance results per adapter.
  - Evidence names backend SKU class, region, date and the delta from the stub run (G12); no credential values.
- Pattern references: `scripts/gates/` conventions from PRP-02.
- Tests to write: `tests/unit/gates/test_g01_analytics_refuses.py`.

## Validation gates
```
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode fast    # per item
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full    # before merge
python scripts/validate_planning.py
```
Feature-specific:
```
docker compose up -d --wait
python -m pytest packages/core/tests/analytics
python -m pytest -m integration tests/integration/analytics
NS_LIVE_APPROVED=1 python scripts/gates/g01_analytics_live.py --adapter fabric    # operator-approved, requires NS_LIVE_APPROVED=1
NS_LIVE_APPROVED=1 python scripts/gates/g01_analytics_live.py --adapter synapse    # operator-approved, requires NS_LIVE_APPROVED=1
NS_LIVE_APPROVED=1 python scripts/gates/g01_analytics_live.py --adapter databricks    # operator-approved, requires NS_LIVE_APPROVED=1
```

## Live and open gates
- G01 (service/feature/region/SKU matrix): item 6 supplies Commercial integration evidence per adapter under `docs/evidence/G01/analytics/`. Government Fabric, Synapse and Databricks stay OPEN (no Government subscription; availability is not authorization, see G02).
- G02 (FedRAMP/DoD boundary): not touched by evidence here; the Government profile only enables approved adapters and makes no authorization claim.
- G12 (emulator parity): record what stubs cannot reproduce (engine-specific SQL semantics, throttling, auth).
- If a live item did not run, record it OPEN in the completion note and in docs/RESEARCH-AND-GATES.md; never report it as a skipped green test.

## NOT building
- Hot aggregates worker and dashboards API (PRP-14); recommendation rules (PRP-15).
- Provisioning Fabric capacity or workspaces (PRP-08 `deploy/fabric/`).
- Cross-cell federation summaries and load profiles (PRP-21).
- A migration runner shared across stores (PRP-13); only adapter-local migrations here.
- Any ClickHouse, Kafka, Neo4j or other unlisted analytics backend.
- Data movement between Government and Commercial clouds, ever.
- Authorization or compliance claims for any adapter.

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
- Live items run or OPEN per adapter (Fabric, Synapse, Databricks; G01, G12):
- Follow-ups:
