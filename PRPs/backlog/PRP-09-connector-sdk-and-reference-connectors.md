---
name: prp-09-connector-sdk-and-reference-connectors
status: backlog
review: required
created: 2026-10-08
model: sonnet
phase: 2
ns: NS-01, NS-09
depends_on: PRP-01, PRP-05
wave: W4
absorbs: P2.2
---

# PRP-09: Connector SDK and reference connectors

## Goal
Ship the Python and TypeScript connector SDKs, a shared manifest format with a contract test kit, four reference connectors (generic OpenTelemetry push, Azure Monitor polling, Foundry discovery, Azure billing export reader), a reconciliation variance report, and the `WriteConnector` protocol that the action executor (PRP-17) consumes. It is for connector authors and platform operators who need honest coverage, freshness and rate-limit reporting from every source. It lands in wave W4 because the telemetry envelope and connector manifest schemas (PRP-01) and the API runtime (PRP-05) exist, and PRP-17 needs the write interface before it can delegate any change.

> Ingest OpenTelemetry traces/metrics and versioned CloudEvents through authenticated push and bounded polling connectors. Azure Monitor/Application Insights/Log Analytics supply observed signals where exposed; provider usage/billing APIs provide aggregates with explicitly reported granularity.

> Connector SDK (Python/TypeScript), capability manifests, schema contracts, health/rate-limit reporting and contract tests.

> Planned connector targets: Azure/Foundry and generic OpenTelemetry first; Microsoft Graph/M365/GitHub Copilot reports, Anthropic, Google, xAI, Palantir, Cursor and Claude Code where documented/admin-authorized signals exist. Publish coverage/latency/license/API limitations; no invented APIs or endpoint agents without consent.

The binding rule for this PRP is the last clause: no invented APIs. Where a documented, admin-authorized signal is not verified, the connector is not built and the gap is documented.

## Acceptance criteria
- [ ] Item 1: Python SDK ships a contract test kit; running the kit against a deliberately broken connector fails, against a conforming one passes; a credential value never appears in logs (log-capture test).
- [ ] Item 2: Manifest JSON produced by the TypeScript SDK validates in the Python kit and vice versa (interop fixtures).
- [ ] Item 3: Sandbox traces pushed through the OTel generic connector land at the ingest edge as `TelemetryEvent` envelopes with missing fields null/unknown, not zero.
- [ ] Item 4: Each Azure Monitor poll reports freshness (data lag) and coverage (what fraction of expected sources answered); polling is bounded by an explicit window and page budget.
- [ ] Item 5: Variance report compares billing aggregates against ledger estimates at the granularity the billing source reports and states that granularity; `docs/connectors/coverage.md` documents the Palantir, xAI and Cursor gaps and states they are not implemented.
- [ ] Item 6: A read-only connector reports `advisory=true`; `WriteConnector` exposes dry-run, apply, verify, rollback with typed results; a connector without write capability cannot be registered as a write target.
- [ ] PRP exit: both SDKs pass their own kits; `docs/RESEARCH-AND-GATES.md` G04 is narrowed only with live contract evidence, otherwise recorded OPEN.

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

## Completion note (filled at ship)
- Date:
- Merged commits:
- Deviations from blueprint and why:
- Descoped items:
- Live items run or OPEN (G04, G12):
- Follow-ups:
