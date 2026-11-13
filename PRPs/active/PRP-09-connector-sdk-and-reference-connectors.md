---
name: PRP-09-connector-sdk-and-reference-connectors
status: active
priority: P2
order: 4
started: 2026-11-13
pr: 45
branch: prp-09-round2
review: required
created: 2026-10-08
model: sonnet
phase: 2
ns: NS-01, NS-09
depends_on: [PRP-01-contracts-and-schemas, PRP-05-api-worker-runtime-and-self-observability]
wave: W4
absorbs: P2.2
orchestrator_model: sonnet
implementer_model: sonnet
---

# PRP-09: Connector SDK and reference connectors

## Goal
Ship the Python and TypeScript connector SDKs, a shared manifest format with a contract test kit, four reference connectors (generic OpenTelemetry push, Azure Monitor polling, Foundry discovery, Azure billing export reader), a reconciliation variance report, and the `WriteConnector` protocol that the action executor (PRP-17) consumes. It is for connector authors and platform operators who need honest coverage, freshness and rate-limit reporting from every source. It lands in wave W4 because the telemetry envelope and connector manifest schemas (PRP-01) and the API runtime (PRP-05) exist, and PRP-17 needs the write interface before it can delegate any change.

> Ingest OpenTelemetry traces/metrics and versioned CloudEvents through authenticated push and bounded polling connectors. Azure Monitor/Application Insights/Log Analytics supply observed signals where exposed; provider usage/billing APIs provide aggregates with explicitly reported granularity.

> Connector SDK (Python/TypeScript), capability manifests, schema contracts, health/rate-limit reporting and contract tests.

> Planned connector targets: Azure/Foundry and generic OpenTelemetry first; Microsoft Graph/M365/GitHub Copilot reports, Anthropic, Google, xAI, Palantir, Cursor and Claude Code where documented/admin-authorized signals exist. Publish coverage/latency/license/API limitations; no invented APIs or endpoint agents without consent.

The binding rule for this PRP is the last clause: no invented APIs. Where a documented, admin-authorized signal is not verified, the connector is not built and the gap is documented.

## Acceptance criteria
- [x] Item 1: Python SDK ships a contract test kit; running the kit against a deliberately broken connector fails, against a conforming one passes; a credential value never appears in logs (log-capture test).
- [x] Item 2: Manifest JSON produced by the TypeScript SDK validates in the Python kit and vice versa (interop fixtures).
- [x] Item 3: Sandbox traces pushed through the OTel generic connector land at the ingest edge as `TelemetryEvent` envelopes with missing fields null/unknown, not zero.
- [x] Item 4: Each Azure Monitor poll reports freshness (data lag) and coverage (what fraction of expected sources answered); polling is bounded by an explicit window and page budget.
- [x] Item 5: Variance report compares billing aggregates against ledger estimates at the granularity the billing source reports and states that granularity; `docs/connectors/coverage.md` documents the Palantir, xAI and Cursor gaps and states they are not implemented.
- [x] Item 6: A read-only connector reports `advisory=true`; `WriteConnector` exposes dry-run, apply, verify, rollback with typed results; a connector without write capability cannot be registered as a write target.
- [x] PRP exit: both SDKs pass their own kits; `docs/RESEARCH-AND-GATES.md` G04 is narrowed only with live contract evidence, otherwise recorded OPEN.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|---|---|---|
| 1 | Model and review | sonnet/none; sonnet/required | sonnet, review required (D6) |
| 2 | Which connectors are built | all NS-09 targets; documented-first set | Four reference connectors only: OTel generic, Azure Monitor, Foundry, Azure billing. All other NS-09 targets are listed in `docs/connectors/coverage.md` as not built, with the reason and what documented API evidence would unlock them |
| 3 | Palantir, xAI, Cursor | build speculative adapters; document gaps | Document gaps only. No code, no guessed endpoints. This is the "no invented APIs" rule |
| 4 | Live provider calls | run in CI; operator-approved only | No live provider or Azure call in CI (D7). Live contract runs use `pytest.mark.live` and `NS_LIVE_APPROVED=1`; absent evidence leaves G04 OPEN |
| 5 | Credential handling | env values; vault references | Vault references only; SDK resolves at call time through an injected resolver; a rotation hook is part of the interface; nothing is logged or serialized into manifests |
| 6 | Push vs poll | all push; both | OTel connector pushes to the PRP-07 ingest edge; Azure Monitor, Foundry and billing poll with bounded windows |
| 7 | Where does `WriteConnector` live | separate package; inside sdk-python | Inside `connectors/sdk-python/neurosphere_connector/write/` (item 6). PRP-17 imports it; the TypeScript SDK does not get a write surface in this PRP |
| 8 | Manifest source of truth | per-SDK; PRP-01 schema | `ConnectorManifest` schema from PRP-01 (`packages/contracts/schemas/connectors/`). Both SDKs validate against the generated types; neither redefines it |
| 9 | Variance granularity | force per-request; report what the source gives | Report the source's granularity (for example daily per resource or per vendor) and never apportion below it |
| 10 | Government | build now; params only | Connectors read cloud endpoints from the cloud profile; Government hosts are configuration, not live-tested here. Unverified Government API availability is stated in the manifest |
| 11 | Payload bodies | pass through; drop by default | Prompt/response bodies dropped by default; redaction runs in the connector before transmission to the ingest edge |

## Context manifest

### Files that matter
- `PRP.md` - sections 1-3 (contracts first; vault references for third-party credentials).
- `docs/PRD.md` - NS-01 envelope and cost rules, NS-09 connector text.
- `docs/ARCHITECTURE.md` - ingest edge and connector placement.
- `docs/RESEARCH-AND-GATES.md` - G04 row; Foundry Government findings (retrieved 2026-10-06 and 2026-10-08).
- `docs/adr/0002-stack-pins.md` - azure-monitor-opentelemetry, opentelemetry-sdk, cloudevents, azure-ai-projects pins.
- `docs/DECISIONS-LOG.md` - D6, D7, D8.
- `pyproject.toml`, `docker-compose.yml`, `infra/compose/eventhubs.config.json`, `.env.example`, `.claude/hooks/config.ps1`, `scripts/validate_planning.py`.
- Created by PRP-01: `packages/contracts/schemas/connectors/` (`ConnectorManifest`), `.../telemetry/` and `.../cost/` schemas, generated Python and TS types.
- Created by PRP-05: `neurosphere_core.errors`, `neurosphere_core.cloud`, `neurosphere_core.observability` (redaction filter).
- Created by PRP-03: `sandbox/` generator output used by item 3.
- Created by PRP-07 (same wave): `services/api/neurosphere_api/ingest/`; item 3 tests against a stub ingest edge until it merges.
- Consumed by PRP-17: `connectors/sdk-python/neurosphere_connector/write/`.

### Patterns to match
- Pydantic v2 models with `model_config = ConfigDict(extra="forbid")` in the Python SDK; TS strict types generated from the same schemas.
- Async clients; Azure clients through `neurosphere_core.clients` when running inside the platform, injectable for SDK tests.
- Errors from `neurosphere_core.errors` (`rate_limited`, `dependency_transient`, `invalid_schema`) mapped to connector health states.
- Tests beside packages; `pytest.mark.live` and `pytest.mark.integration` markers; Vitest for sdk-ts.
- Contract test kit as an importable pytest plugin so each reference connector runs the same suite.

### Conventions
- ruff line 100, py312, S rules on; pyright standard; TS strict; conventional commits; owned-file discipline.
- Evidence under `docs/evidence/G04/` if a live run happens; live scripts under `scripts/gates/` refuse without `NS_LIVE_APPROVED=1`.
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
- PRP-specific: "no invented APIs". Every connector cites the documented API (URL and observed date) in its manifest or `docs/connectors/coverage.md`. If you cannot cite it, do not build it.
- PRP-specific: billing aggregates and gateway/app observations of the same request must not be summed; the reconciliation report compares, it does not add. Estimated vs invoiced stay distinct.
- PRP-specific: Foundry Agent Service in Government lacks hosted agents, web search, Bing grounding, Fabric tool and agent-to-agent (retrieved 2026-10-08); discovery must report absent capabilities as unavailable, not as empty.
- PRP-specific: `azure-ai-projects` preview features need `allow_preview=True`; Government needs 2.0 or later (ADR-0002). Do not enable preview paths silently.
- PRP-specific: the Azure Monitor query APIs are rate- and size-limited; a poll must page within a stated budget and report partial coverage rather than loop.
- PRP-specific: the TypeScript SDK must not grow a write surface; `WriteConnector` is Python-only in this PRP.

### External references
- Foundry Agent Service in Azure Government: https://learn.microsoft.com/azure/foundry/agents/concepts/azure-government (retrieved 2026-10-06, re-observed 2026-10-08).
- Foundry platform in Government: https://learn.microsoft.com/azure/foundry/concepts/foundry-azure-government (retrieved 2026-10-06).
- OpenTelemetry Python SDK 1.45 and azure-monitor-opentelemetry 1.8 pins: docs/adr/0002-stack-pins.md (observed 2026-10-08), https://pypi.org/project/opentelemetry-sdk/.
- CloudEvents Python 2.2: https://pypi.org/project/cloudevents/ (observed 2026-10-08).
- MCP versioning (for the later PRP-22 consumer of manifests): https://modelcontextprotocol.io/specification/versioning (observed 2026-10-08).
- For each reference connector, the implementer adds the specific Azure Monitor, Foundry and Cost Management API page and its observed date to `docs/connectors/coverage.md`.

## Implementation blueprint

### Item 0 - shared root wiring  (added at plan approval, 2026-10-17; orchestrator)
- Deliverable: package skeletons for `connectors/sdk-python`, the four `connectors/reference/*` packages and `connectors/sdk-ts`; root `pyproject.toml` workspace members, dev dependencies, pytest `testpaths` and pyright `include` covering `connectors`; regenerated `uv.lock` and `pnpm-lock.yaml`. Added because no item owns the root files, and parallel lanes would otherwise conflict on them and on the lockfiles.
- Owned files (may edit): root `pyproject.toml`, `uv.lock`, `pnpm-lock.yaml`, skeleton `pyproject.toml`/`package.json`/`__init__.py` files under `connectors/`.
- Rule for items 1-6: dependencies may be added only to the item's own package manifest; lockfiles and the licence register (`docs/licenses.md`, ADR-0002 appendix) are regenerated by the orchestrator after each merge.
- Sequencing change: item 2 additionally owns `connectors/sdk-python/tests/interop/` and runs after item 1 merges, so both halves of the interop test land in one lane.

### Item 1 - sdk-python  [P]
- Deliverable: Python base connector class, manifest builder/validator, health, rate-limit and coverage reporting, vault credential references with a resolver interface, rotation hook, and an importable contract test kit.
- Owned files (may edit): `connectors/sdk-python/` (excluding `neurosphere_connector/write/`).
- Must NOT touch: `connectors/sdk-python/neurosphere_connector/write/` (item 6), `connectors/sdk-ts/`, `connectors/reference/`, `packages/contracts/`, root `pyproject.toml`, `docker-compose.yml`, `docs/RESEARCH-AND-GATES.md`.
- Depends on: none.
- Acceptance criteria:
  - Contract test kit fails a connector missing health, a manifest, or coverage reporting; passes a conforming one.
  - Log-capture test: a credential value passed through the resolver never appears in any log record or exception text.
  - Rotation hook invoked on credential change without restarting the connector (test).
- Pattern references: Pydantic forbid-extra; errors taxonomy; redaction filter from PRP-05.
- Tests to write: `connectors/sdk-python/tests/test_contract_kit.py`, `connectors/sdk-python/tests/test_credentials.py`.

### Item 2 - sdk-ts  [P]
- Deliverable: TypeScript SDK with the same surface (base connector, manifest, health/rate-limit/coverage, credential refs) and interoperable manifest JSON.
- Owned files (may edit): `connectors/sdk-ts/`.
- Must NOT touch: `connectors/sdk-python/`, `connectors/reference/`, `packages/contracts/ts/`, `frontend/`, root `package.json`, `pnpm-workspace.yaml`.
- Depends on: none.
- Acceptance criteria:
  - Manifest fixtures generated by sdk-ts validate in the Python kit and Python fixtures validate in sdk-ts.
  - `tsc --noEmit` passes under TS strict (6.0.x).
  - No write-connector API is exported.
- Pattern references: TS strict; Vitest.
- Tests to write: `connectors/sdk-ts/tests/manifest.interop.test.ts`.

### Item 3 - otel-generic-connector
- Deliverable: reference push connector: OTel collector exporter config plus a Python connector that maps OTel spans/metrics and CloudEvents to `TelemetryEvent`, redacts bodies, and posts to the ingest edge.
- Owned files (may edit): `connectors/reference/otel-generic/`.
- Must NOT touch: `connectors/sdk-python/`, `connectors/reference/azure-monitor/`, `connectors/reference/foundry/`, `connectors/reference/azure-billing/`, `services/api/neurosphere_api/ingest/` (PRP-07).
- Depends on: Item 1.
- Acceptance criteria:
  - Sandbox traces (PRP-03) arrive as valid `TelemetryEvent` envelopes with trace/span/parent IDs preserved.
  - Missing optional fields are null/unknown, never zero.
  - Prompt/response attributes are dropped before send by default.
- Pattern references: contract kit from item 1; PRP-01 telemetry schema.
- Tests to write: `connectors/reference/otel-generic/tests/test_mapping.py`, `tests/integration/connectors/test_otel_generic_ingest.py` (marker `integration`, uses compose).

### Item 4 - azure-monitor-connector  [P]
- Deliverable: bounded polling connector for Application Insights and Log Analytics through documented query APIs, with window, page budget and watermark.
- Owned files (may edit): `connectors/reference/azure-monitor/`.
- Must NOT touch: `connectors/sdk-python/`, other `connectors/reference/*` directories, root `pyproject.toml`.
- Depends on: Item 1.
- Acceptance criteria:
  - Every poll result carries `freshness` (lag) and `coverage` fields.
  - Page budget exceeded yields partial result with flag, never an unbounded loop (test with a fake paginator).
  - API rate limit response maps to `rate_limited` and backs off.
- Pattern references: SDK health/rate-limit reporting; async clients.
- Tests to write: `connectors/reference/azure-monitor/tests/test_polling.py`.

### Item 5 - foundry-and-billing-connectors  [P]
- Deliverable: Foundry discovery connector (agents, deployments, reporting unavailable capabilities per cloud), Azure cost export reader, a reconciliation variance report, and `docs/connectors/coverage.md`.
- Owned files (may edit): `connectors/reference/foundry/`, `connectors/reference/azure-billing/`, `docs/connectors/coverage.md`.
- Must NOT touch: `connectors/sdk-python/`, `connectors/reference/otel-generic/`, `connectors/reference/azure-monitor/`, `connectors/reference/foundry-actions/` (PRP-17), `packages/core/neurosphere_core/ledger/` (PRP-07), `docs/RESEARCH-AND-GATES.md`.
- Depends on: Item 1.
- Acceptance criteria:
  - Variance is computed at the billing source's reported granularity and the report states it; null cost stays null.
  - `docs/connectors/coverage.md` has a row per NS-09 target with built/not-built, API citation and observed date, and states Palantir, xAI and Cursor are gaps not implemented.
  - Foundry discovery marks Government-unavailable capabilities as `unavailable`, not empty.
- Pattern references: cost schema from PRP-01; estimated vs invoiced distinction.
- Tests to write: `connectors/reference/foundry/tests/test_discovery.py`, `connectors/reference/azure-billing/tests/test_variance.py`.

### Item 6 - write-connector-interface
- Deliverable: `WriteConnector` protocol with `dry_run`, `apply`, `verify`, `rollback`, an `advisory` flag, typed result models, and a registration check that rejects non-write connectors as action targets.
- Owned files (may edit): `connectors/sdk-python/neurosphere_connector/write/`.
- Must NOT touch: the rest of `connectors/sdk-python/`, `connectors/sdk-ts/`, `connectors/reference/foundry-actions/` (PRP-17), `packages/core/neurosphere_core/actions/` (PRP-17).
- Depends on: Item 1.
- Acceptance criteria:
  - A read-only connector reports `advisory=true` and `apply` raises `capability_unavailable`.
  - `verify` returns observed post-state separate from the requested diff, so callers can detect a pretend change.
  - Protocol is importable without Azure SDK dependencies (import-time test).
- Pattern references: Pydantic forbid-extra; errors taxonomy.
- Tests to write: `connectors/sdk-python/tests/write/test_write_connector.py`.

### Round 2: audit gap closure (items 7-13, added 2026-11-13)
Reopened by the 2026-11-04 audit (section at the end). Rechecked 2026-11-13 against main c60fba0:
- Still open:
  - The OTel, Foundry-discovery and billing connectors and `build_variance_report` have no non-test caller. Only Azure Monitor runs, via the `gateway_poll` role (PRP-33).
  - Nothing runs `check_connector_contract` against a reference connector. The TS contract kit has no pass/fail assertions.
  - #46 is still live. `connector.py` `_poll` advances `cursor` past a truncated page (`page.partial`: PartialError or MAX_ROWS). A 429 on a later slice raises and discards the earlier slices. An empty source list advances the watermark over nothing.
  - #47, #48, #49 and #50 are open.
- Already in place, so reused rather than rebuilt:
  - PRP-14 `/api/v1/reconciliation` and `frontend/src/features/reconciliation/` already compare gateway, app and billing against the ledger.
  - The ledger fold (`neurosphere_core/ledger/fold.py`) handles invoiced billing observations and allocations.
  - `CostRecord` carries `kind=invoiced`, `observation_source=billing` and `billing_period`, sent as CloudEvent type `com.neurosphere.cost.v1`.
  - The catalog projection creates `draft` entities marked `attributes.discovered_from` (`services/workers/neurosphere_workers/projections/catalog/discovery.py`).

User decisions 2026-11-13:
- Full gap closure, including composition (the "real data path" step for these connectors).
- Billing feeds the existing reconciliation view through ingest. No parallel variance API. `build_variance_report` gets an operator CLI.
- OTel is composed as an opt-in compose profile, with a compose-gated integration test.
- G04 stays OPEN. No live run this round.

Shared rules for items 7-13:
- New worker roles follow the `gateway_poll` pattern in `services/workers/neurosphere_workers/runtime/factories.py`. Each is part of `all`, idles with one info log line when unconfigured, and raises `RoleConfigError` on half-configured settings.
- Agents cannot edit `.env.example`. The orchestrator hands the new `NS_*` lines to the operator.
- Helm and Bicep env wiring for the new roles is a follow-up issue, not this round.
- The compose project name is shared across worktrees, so compose-gated runs are sequenced, never concurrent.

### Item 7 - azure-monitor-watermark (#46)  [P]
- Deliverable:
  - A truncated page holds the cursor at that slice's start, so the slice is re-polled. Alternatively, the gap is recorded explicitly in the result. Either way, the watermark never passes unread rows.
  - A 429 on a later slice returns the records of the completed slices, with `partial=True` and the rate-limit state recorded. It does not discard them.
  - An empty source list does not advance the watermark.
- Owned files (may edit): `connectors/reference/azure-monitor/`, `services/workers/neurosphere_workers/ingestion/gateway_poll/` (only where the poller relies on the old semantics), and their tests.
- Must NOT touch: `connectors/sdk-python/`, other `connectors/reference/*`, `factories.py`, `docs/`.
- Acceptance criteria:
  - A fake-paginator test with a MAX_ROWS page and a PartialError page shows the next poll re-reads that slice.
  - A 429 on slice 2 still returns slice 1's records and flags the result partial.
  - With empty sources, `next_watermark` equals the input watermark.
  - The `gateway_poll` tests stay green.

### Item 8 - write-verify-strictness (#47)  [P]
- Deliverable:
  - `verify` compares with strict types (`True` does not equal `1`).
  - An empty observed state is unverifiable, not matched.
  - `move` and `copy` verification requires the prior value, or the limitation is documented and flagged.
  - Path lookup rejects Unicode digits and leading-zero indexes.
  - `_check_capable` requires the protocol methods to be coroutine functions.
- Owned files (may edit): `connectors/sdk-python/neurosphere_connector/write/`, `connectors/sdk-python/tests/write/`.
- Must NOT touch: the rest of `connectors/sdk-python/`, `connectors/reference/`, `packages/core/neurosphere_core/actions/`, `services/`.
- Acceptance criteria:
  - Each #47 case has a test.
  - Cross-tests stay green: `connectors/reference/foundry-actions`, `connectors/reference/apim-gateway`, and every test importing `neurosphere_connector.write` (found by grep).

### Item 9 - sdk-hardening (#48, #50)  [P]
- Deliverable:
  - #48: the vault error carries no `__context__` holding the raw resolver exception; rotation-drain behaviour is documented or auto-scheduled; the rate-limit `remaining=0` survives a later success; duplicate-name detection is O(n) and reports every duplicate; the dead branch is removed.
  - #50: `validateManifest` returns a frozen copy; a shared invalid fixture covers a malformed `documentation_url`; the `SecretValue.equals` comment is accurate; credential failures raise a `ConnectorError` with a code; `UPDATE_INTEROP_FIXTURES=1` is documented.
  - TS contract-kit pass/fail tests: a conforming connector passes and a broken one fails.
- Owned files (may edit): `connectors/sdk-python/` (excluding `neurosphere_connector/write/` and `tests/write/`), `connectors/sdk-ts/`.
- Must NOT touch: `connectors/reference/`, `packages/`, root manifests and lockfiles.
- Acceptance criteria:
  - A log-capture and exception-chain test proves no credential value is reachable through `__context__` or `__cause__`.
  - Interop fixtures still pass both ways.
  - `tsc --noEmit` and Vitest are green.

### Item 10 - otel-composition (#49)  [P]
- Deliverable:
  - #49 fixes: widen the body-name guard (bare `completion` and `messages`); count dropped array, bytes and None attributes; reject or omit NaN and Inf; make `force_flush` really flush; fail on an unrecognised vault host; parse HTTP-date `Retry-After`.
  - An opt-in `otel` docker-compose profile runs the official OpenTelemetry collector with the body-dropping config, exporting to the composed ingest edge. The producer credential comes from the environment, never from a file.
  - A compose-gated integration test (`integration` marker) sends an OTLP span to the collector and checks it lands as a `TelemetryEvent`, with missing fields null and the body attributes absent.
- Owned files (may edit): `connectors/reference/otel-generic/`, `docker-compose.yml` (the new `otel` profile service only), `tests/integration/connectors/`, `packages/core/neurosphere_core/payload/` (the body-name guard only).
- Must NOT touch: `services/api/neurosphere_api/ingest/` (except reading it), other compose services, `.github/`, `.env.example`.
- Acceptance criteria:
  - Each #49 case has a unit test.
  - The guard widening keeps every importer's tests green (grep `neurosphere_core.payload`).
  - The integration test passes locally against compose, run sequenced. CI does not run the `integration` marker for this test, and that is stated.
  - The G12 delta (no Entra producer identity on the emulator) stays recorded.

### Item 11 - foundry-discovery-role (after Wave A)  [P with 13]
- Deliverable:
  - A `foundry_discovery` worker role that polls the Foundry project(s) configured by `NS_FOUNDRY_DISCOVERY_*`, using `FoundryDiscoveryConnector` with a bounded interval.
  - It upserts `draft` Agent and ModelDeployment catalog entities with `attributes.discovered_from="foundry"`. It creates them only if absent and never overwrites a curated or declared entity.
  - Government-unavailable capabilities are recorded as `unavailable` (log and health), never as empty.
  - Includes the item-5 Foundry review findings, if any remain.
- Owned files (may edit): new `services/workers/neurosphere_workers/ingestion/foundry_discovery/`, `connectors/reference/foundry/`, the `foundry_discovery` builder and registration in `services/workers/neurosphere_workers/runtime/factories.py` and `runtime/settings.py`, and their tests.
- Must NOT touch: `projections/catalog/` (except reading it), `packages/core/neurosphere_core/catalog/`, other roles' builders, `infra/`.
- Acceptance criteria:
  - An unconfigured role idles, and a half-configured role raises `RoleConfigError`.
  - A fake-reader test shows draft entities created once and a curated entity left untouched on re-poll.
  - A Government profile reports the documented absent capabilities as `unavailable`.
  - The workers runtime tests stay green.

### Item 13 - contract-kit-conformance (after Wave A)  [P with 11]
- Deliverable: one parametrized test running `check_connector_contract` against every reference connector (otel-generic, azure-monitor, foundry, azure-billing, apim-gateway, foundry-actions), each constructed with fakes and no network.
- Owned files (may edit): new `tests/unit/connector_conformance/` (a unique directory name, to avoid test-package clashes).
- Must NOT touch: any connector source. A connector that fails conformance is reported to the orchestrator, which dispatches it as a fresh fix item.
- Acceptance criteria:
  - All six connectors are covered.
  - A deliberately broken fake fails the kit in the same test file.
  - Nothing reaches the network.

### Item 12 - billing-export-role (after item 11 merges; shares factories.py)
- Deliverable:
  - A `billing_export` worker role that reads the Cost Management export configured by `NS_BILLING_EXPORT_*` (`AzureBlobExportSource`, managed identity).
  - It maps the export's daily per-resource aggregates to `CostRecord` (`kind=invoiced`, `observation_source=billing`, `billing_period`, and a stable `dedupe_key`) and posts them as `com.neurosphere.cost.v1` CloudEvents through the ingest edge, so the PRP-14 reconciliation view shows the billing source.
  - Granularity is never finer than the export, and null cost stays null.
  - Reader hardening from the item-5 review: cap on `gzip.decompress` size; `Decimal` rejects underscores and non-ASCII digits; dropped dateless rows and missing partitions are stated.
  - Operator CLI `scripts/connectors/billing_variance.py` runs `build_variance_report` offline.
- Owned files (may edit): new `services/workers/neurosphere_workers/ingestion/billing_export/`, `connectors/reference/azure-billing/`, the `billing_export` builder and registration in `factories.py` and `runtime/settings.py`, `scripts/connectors/billing_variance.py`, and their tests.
- Must NOT touch: `packages/core/neurosphere_core/ledger/`, `aggregates/`, `services/api/neurosphere_api/ingest/`, `services/api/neurosphere_api/reconciliation/`, `frontend/`.
- **Stop condition:** if the ingest edge rejects request-less invoiced CostRecords, or the ledger and aggregates do not surface them as the reconciliation `billing` source, stop and report. That is a PRP-07 change, not this lane's.
- Acceptance criteria:
  - A fake-blob test, run through the ingest pipeline's fakes, shows billing amounts arriving as the reconciliation billing source at export granularity.
  - Unconfigured and half-configured behaviour matches item 11.
  - Snyk Code is clean on the new files.

## Validation gates
```
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode fast    # per item
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full    # before merge
python scripts/validate_planning.py
```
Feature-specific:
```
python -m pytest connectors/sdk-python connectors/reference
pnpm --filter ./connectors/sdk-ts test
docker compose up -d --wait
python -m pytest -m integration tests/integration/connectors
python -m pytest connectors -m live    # operator-approved, requires NS_LIVE_APPROVED=1
```

## Live and open gates
- G04 (provider/API/license coverage): this PRP produces `docs/connectors/coverage.md` and contract-kit results. G04 stays OPEN until live contract results exist for Azure Monitor, Foundry and billing under `docs/evidence/G04/`; unbuilt targets remain open by design.
- G12 (emulator parity): the compose-based ingest test cannot reproduce Entra producer identity; record the delta.
- G05 is touched indirectly (write interface) but closed only by PRP-17.
- If a live item did not run, record it OPEN in the completion note and in docs/RESEARCH-AND-GATES.md; never report it as a skipped green test.

## NOT building
- Connectors for Microsoft Graph/M365/GitHub Copilot reports, Anthropic, Google, xAI, Palantir, Cursor, Claude Code (documented in coverage.md only).
- Any endpoint agent or desktop collector (requires consent and is outside the baseline).
- Foundry model-swap write connector (`connectors/reference/foundry-actions/`, PRP-17).
- Ingest edge and normalizer (PRP-07); cost ledger (PRP-07).
- MCP server or client (PRP-22).
- CI/CD registration integrations for GitHub Actions, Azure DevOps and Jenkins (not in this decomposition).

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [x] All clarification questions are decided, not guessed

## Execution state

| Item | Status | Branch | Model | Evidence | Updated |
|------|--------|--------|-------|----------|---------|
| 0 | merged | prp-09-connector-sdk | opus | committed directly on integration branch; ruff/format/pyright clean; full default suite 3914 passed after licence register regen; sdk-ts typecheck ok; licences PASS (530); validate_planning PASS | 2026-10-17 |
| 1 | merged | worktree-agent-a95e623057e6e32ed | sonnet | ruff/format/pyright clean; sdk-python 49 passed (re-run on branch); contracts 1683 passed; Snyk Code 0 issues; 35a5fdd. Deviation: credentials module named vault.py (security hook denies *credentials* paths); review APPROVE (6 non-blocking follow-ups); merge 8a311df, sdk-python 49 passed + pyright clean post-merge | 2026-10-17 |
| 2 | merged | worktree-agent-aa43819c280ffa6e6 | sonnet | sdk-ts typecheck clean, vitest 25 passed; sdk-python 60 passed, ruff/format/pyright clean (re-run on branch); Snyk: 1 low (hardcoded test secret) fixed c8e633e, rescan 0; d485850. Deps ajv, @types/node (relock at merge); review APPROVE (5 non-blocking); merged, pnpm relocked, licences PASS (533); sdk-ts 25 + sdk-python 60 passed post-merge | 2026-10-17 |
| 3 | merged | worktree-agent-a526b9a31c65eacee | sonnet | ruff/format/pyright clean; 24 unit passed; integration tests/integration/connectors 1 passed vs compose emulators (re-run on branch, 47.5s); Snyk: 1 low (hardcoded test secret) fixed d068432, rescan 0; 9a4b050. Bodies always dropped (no opt-out); G12 delta: emulator lacks Entra producer identity; review APPROVE (7 non-blocking); merged + uv relock, licences PASS (533); connectors 141 passed, integration 1 passed post-merge | 2026-10-17 |
| 4 | merged | worktree-agent-aa7e2a4c99970301d | sonnet | ruff/format/pyright clean; 23 passed, 1 live deselected (re-run on branch); Snyk: 1 low (URL substring check in test) fixed 4bbcbb8, rescan 0; a938df3. Gov gated behind allow_unverified_government; App Insights Gov disabled; review APPROVE (5 non-blocking; top: truncated slice (MAX_ROWS/PartialError) still advances watermark — rows lost, flagged partial only); merge 6e2d0cf, connectors 93 passed + pyright/ruff clean post-merge | 2026-10-17 |
| 5 | merged | worktree-agent-a28be3f1c8bf37394 | sonnet | fa7fde2: ruff/format/pyright clean, 52 passed, Snyk 0. Verify FAIL round 1: licence gate — azure-ai-projects -> openai -> httpx2 -> httpx2-jsfetch (emscripten-only) UNKNOWN licence. Documented Foundry REST list APIs exist (rest/api/microsoft-foundry/aiproject); fix round 1 dispatched: REST reader, drop SDK. Round 1 fix f679df8: REST reader, azure-ai-projects removed; ruff/format/pyright clean, 73 passed, licences PASS, Snyk 0 (re-run on branch); review APPROVE (5 non-blocking); merged + uv relock; coverage.md item 3/4 rows reconciled by orchestrator | 2026-10-17 |
| 6 | merged | worktree-agent-a4a17a14f0a492cd0 | sonnet | ruff/format/pyright clean; sdk-python 59 passed (re-run on branch); Snyk Code 0 issues; 84f3cdc; review APPROVE (6 non-blocking: verify type coercion True==1, move/copy post-state limits, SDK does not enforce target version — executor must); merge b3910e9, sdk-python 59 passed + pyright clean post-merge | 2026-10-17 |
| 7 | todo | | sonnet | | 2026-11-13 |
| 8 | todo | | sonnet | | 2026-11-13 |
| 9 | todo | | sonnet | | 2026-11-13 |
| 10 | todo | | sonnet | | 2026-11-13 |
| 11 | todo | | sonnet | | 2026-11-13 |
| 13 | todo | | sonnet | | 2026-11-13 |
| 12 | todo | | sonnet | | 2026-11-13 |

## Completion note (filled at ship)
- Date: 2026-10-17
- Merged commits: PR #45 (merge 4fc4ba5). Item 0 4a13249; item merges 8a311df (1), b3910e9 (6), e89a2f3 (2), 6e2d0cf (4), add0250 (3), b00d6ba (5); close-out docs a9dca2a; CodeQL fix 9269189.
- Deviations from blueprint and why:
  - Item 0 (shared root wiring) added at plan approval: no item owned root `pyproject.toml`, the lockfiles or the licence register, and parallel lanes would have conflicted on them. Items added deps only to their own manifests; the orchestrator relocked and regenerated the register after each merge.
  - Item 2 ran after item 1 (not in parallel) and also owned `connectors/sdk-python/tests/interop/`, so both halves of the interop test landed in one lane.
  - Python SDK credentials module is `vault.py` and its test `test_vault_refs_and_rotation.py`: a security hook denies paths containing `credentials`.
  - Item 5 verify failed once on the licence gate: `azure-ai-projects` pulls `openai` -> `httpx2` -> `httpx2-jsfetch` (emscripten-only, UNKNOWN licence). Fixed by reading Foundry through the documented REST API (`rest/api/microsoft-foundry/aiproject`, `GET /agents`, `GET /deployments`, api-version `v1`) with httpx; the SDK is not a dependency.
  - Azure Monitor: the query APIs have no cursor paging, so a "page" is a time slice of the window. Government Log Analytics needs an explicit `allow_unverified_government` opt-in; Application Insights has no documented Government host and is disabled there. Auth is managed identity (first-party Azure), not vault references.
  - OTel connector drops bodies always (stricter than "by default"); it sends the PRP-07 edge's own wire format, so the edge keeps the single OTLP-to-TelemetryEvent mapping.
  - TS SDK manifests are always advisory with no write option (Clarification 7).
  - Snyk flagged three low test-fixture findings (hardcoded fixture secrets, a URL substring check) and CodeQL one high (URL substring check in a Foundry test); all fixed. 15 CodeQL notes remain (Protocol `...` bodies, two `await` false positives), matching the existing convention on main.
- Descoped items: none.
- Live items run or OPEN (G04, G12):
  - G04 OPEN: no live contract run for Azure Monitor, Foundry or billing (`NS_LIVE_APPROVED=1` not used; no `docs/evidence/G04/`); Government endpoints are configuration only; unbuilt NS-09 targets open by design. Recorded in docs/RESEARCH-AND-GATES.md.
  - G12: `tests/integration/connectors/` (1 test) passed against the compose emulators locally; delta recorded — Entra producer identity is not reproducible on the Event Hubs emulator, the edge checks the producer credential instead.
- Follow-ups: #46 (Azure Monitor watermark advances past truncated slices: data-loss path, fix before any live G04 run), #47 (WriteConnector verify strictness: type coercion, move/copy, target version enforced by PRP-17 executor), #48 (Python SDK hardening), #49 (OTel connector edge cases), #50 (TS SDK polish). Item 5 non-blocking review findings, not filed separately: billing `blobs_expected` equals blobs read so missing partitions show only via the row-count check; rows without a date are dropped (counted, not stated in the variance report); `gzip.decompress` has no size cap; `Decimal` accepts underscores and non-ASCII digits in cost cells.

## Audit 2026-11-04

Reopened after a deep audit (static read; no tests were run). The SDK, write interface, tests and docs are real. Composition into the product is thin. Gaps:

- The OTel, Foundry and billing reference connectors and `build_variance_report` have no non-test caller in `services/`, `packages/` or `scripts/`. Only the Azure Monitor connector is called (`services/workers/neurosphere_workers/ingestion/gateway_poll/poller.py:90`, wired at `runtime/factories.py:639` as the opt-in `gateway_poll` role, not part of `all`, from PRP-33). The variance report has no API, worker or UI surface.
- The contract kit (`connectors/sdk-python/neurosphere_connector/contract_kit.py`, `check_connector_contract`) is exercised only by its own tests. The PRP-exit claim that it runs against each reference connector has no test behind it. TS `contract-kit.ts` pass/fail assertions not checked.
- Criterion 3 (OTel push lands as TelemetryEvent with nulls): the test is real (`tests/integration/connectors/test_otel_generic_ingest.py:136-151`) but runs against compose emulators and stays out of default runs. The connector posts OTLP/CloudEvents and the ingest edge maps it. Nothing composes the exporter. Entra producer identity is untested (G12 delta).
- Issue #46: the Azure Monitor watermark advances past truncated slices, so rows are lost. Fix before any live G04 run. G04 is correctly OPEN; `docs/evidence/G04/` does not exist.
- Foundry connector reads REST via httpx; `azure-ai-projects` was dropped over a licence problem.
- Met: contract kit pass/fail and credential-not-logged tests; TS/Python manifest interop; `WriteConnector` and registry (used by PRP-17 and PRP-34); Azure Monitor polling freshness, page budget and 429 handling.
