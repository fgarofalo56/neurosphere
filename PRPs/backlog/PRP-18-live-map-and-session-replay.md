---
name: prp-18-live-map-and-session-replay
status: backlog
review: required
created: 2026-10-08
model: sonnet
phase: 3
ns: NS-05
depends_on: PRP-04, PRP-10, PRP-14
wave: W7
absorbs: P3.1
---

# PRP-18: Live map and session replay

## Goal
Ship the live agent map and run replay: a scoped WebSocket gateway fed by hot aggregates, a bounded viewport API, a sigma.js 4 and graphology WebGL renderer, an accessible table alternative, a read-only trace replay viewer, and a freshness load test. It is for analysts, stewards and auditors who need to see agent topology and inspect past runs without exposing the whole enterprise graph to a browser. It lands in W7 after the UI shell (PRP-04), catalog (PRP-10) and hot aggregates (PRP-14).

> Distinct node shapes/icons for people, agents, sub-agents, models and sources; configurable size/color legends for tokens, context size, frequency, latency and health. Animate observed edges only and label partial/delayed coverage. Aggregate into domain clusters; never download the full enterprise graph to a browser. Drill down to lineage, metrics, costs, evidence and recommendations.

> WebGL viewport with bounded node/edge budgets, aggregation and paginated expansion; text/table alternative, reduced motion, keyboard navigation and non-color status indicators. Restrict identity display; pseudonymize people by default. Live updates via scoped WebSocket gateway; permission revocation closes sessions and invalidates caches.

> Replay stored/redacted run traces with parent-child calls, timings, errors and tool interactions; label gaps, sampling and late spans. Replay is visual inspection, not re-execution of side-effectful tools. Payload access, retention, export and legal hold follow policy.

PRD planning targets (to be measured, not guaranteed): map freshness p95 <=10s after normalized ingestion; browser <=2k visible nodes at >=30fps on documented hardware.

## Acceptance criteria
- [ ] Item 1: A revoked principal's WebSocket session is closed within the configured TTL; a delta for another domain is never pushed to a scoped session; per-session budgets are enforced.
- [ ] Item 2: Viewport responses never exceed 2k nodes and the configured edge budget; expansion is paginated; truncation is flagged.
- [ ] Item 3: At 2k visible nodes the renderer meets the >=30fps target on the documented hardware (perf test records the measured value and hardware); reduced-motion preference disables edge animation; only observed edges animate; coverage labels show partial or delayed data.
- [ ] Item 4: The table alternative is axe clean, fully keyboard traversable (e2e), and status never relies on color alone.
- [ ] Item 5: The replay endpoint exposes no action capability (static analysis plus test); gaps, sampling and late spans are labeled.
- [ ] Item 6: Event-to-view freshness p95 is measured under sandbox load and evidence JSON is written to `docs/evidence/G07/map/`; the 10s figure is reported as a measured result against a target.
- [ ] PRP exit: items 1-6 green under `verify-gates -Mode full`; documented hardware spec recorded beside the perf result.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|---|---|---|
| 1 | Model and review | sonnet/none; sonnet/required; opus | sonnet, review required (D6) |
| 2 | Renderer | sigma + graphology; cosmograph; deck.gl | sigma.js 4 with graphology 0.26 (ADR-0002). Never `@cosmograph`: it is CC-BY-NC |
| 3 | Live gates | live required; emulator/sandbox | Sandbox load on Docker Compose emulators (D8). Freshness evidence is labelled emulator/sandbox; a live Commercial run is optional, operator-approved with `NS_LIVE_APPROVED=1`, else G07 map evidence stays OPEN |
| 4 | Node budget | unlimited; 2k visible | At most 2k visible nodes server-enforced; the browser never receives the full graph; aggregation into domain clusters beyond the budget |
| 5 | Frame rate and hardware | claim universally; document | The >=30fps figure is a target on documented hardware; the perf test writes the hardware description and measured fps; no universal claim |
| 6 | Freshness | guarantee; target | p95 <=10s after normalized ingestion is a PRD planning target to be measured; provider billing freshness is connector-dependent and excluded |
| 7 | Push transport | SSE; WebSocket | Scoped WebSocket gateway fed from PRP-14 hot aggregates, not from raw events or batch analytics |
| 8 | Revocation | poll; interface | Use the revocation interface from PRP-06 (`neurosphere_core.auth.revocation`): revocation closes sessions and invalidates caches within TTL |
| 9 | Replay semantics | re-execute; inspect | Visual inspection of stored, redacted traces only. No re-execution, no tool invocation, no write route in the replay module |
| 10 | Identity display | real names; pseudonyms | People pseudonymized by default; reveal only with explicit scoped permission and audit |
| 11 | Accessibility | later (PRP-24); now | Table alternative, keyboard navigation, reduced motion and non-color status ship here; the full WCAG audit is PRP-24 |
| 12 | Edge animation | all edges; observed only | Observed edges only; declared or inferred edges are static and visually distinct |

## Context manifest

### Files that matter
- `PRP.md` - sections 1-3 (scope; IdentityScope on WebSocket paths).
- `docs/PRD.md` - NS-05 text; planning targets and scale profiles (2k nodes, 30fps).
- `docs/ARCHITECTURE.md` - realtime and hot-aggregate diagrams.
- `docs/RESEARCH-AND-GATES.md` - G07, G12 rows.
- `docs/adr/0002-stack-pins.md` - sigma 4.0, graphology 0.26, React 19.3, Fluent UI 9.74.
- `docs/DECISIONS-LOG.md` - D6, D7, D8, D11.
- `pyproject.toml`, `docker-compose.yml`, `infra/compose/eventhubs.config.json`, `.env.example`, `.claude/hooks/config.ps1`, `scripts/validate_planning.py`.
- Created by PRP-01: `packages/contracts/schemas/scope/`, `.../query/`, `.../catalog/`.
- Created by PRP-04: `frontend/src/design-system/` (node-type icon set, themes), `frontend/src/api/`, `frontend/src/features/workspaces/`, `frontend/tests/`.
- Created by PRP-05: `neurosphere_core.errors`, `.../paging/`, observability, API app factory.
- Created by PRP-06: `neurosphere_core.auth.scope`, `neurosphere_api.authz`, `neurosphere_core.auth.revocation`.
- Created by PRP-10: `neurosphere_core.catalog.graph` (bounded `GraphQuery`).
- Created by PRP-14: `services/workers/neurosphere_workers/aggregates/` (hot aggregates with lag and coverage metadata).

### Patterns to match
- Pydantic v2 models with `model_config = ConfigDict(extra="forbid")`, generated from `packages/contracts`.
- FastAPI routers per module under `services/api/neurosphere_api/<module>/router.py` (`realtime/`, `map/`, `replay/`).
- Async Azure SDK clients from `packages/core/neurosphere_core/clients`; error taxonomy exceptions from `neurosphere_core.errors` (`rate_limited` for budget breach).
- Same `IdentityScope` object for WebSocket subscription, viewport queries and cache keys; cache key includes a hash of the scope.
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
- PRP-specific: `@cosmograph` packages are CC-BY-NC and must never appear in `package.json` or the lockfile; PRP-00's licence check should fail on it. Use sigma 4 and graphology only.
- PRP-specific: the 2k-node cap and the fps target are enforced and measured, but the fps result is hardware-specific. Record the exact hardware beside the number; headless CI numbers are not the documented-hardware result.
- PRP-specific: a delta pushed to a WebSocket must be filtered by the session's scope at send time, not at subscribe time; permissions change during a session. Revocation closes the socket, and cached viewport responses are invalidated by scope-hash keys.
- PRP-specific: a map that animates stale data as live is misleading. Show lag and coverage labels from the aggregate metadata; a gap is labelled, never smoothed over.
- PRP-specific: the replay module must contain no route or import that can invoke a tool, connector or action executor. Enforce with a static import check in tests.
- PRP-specific: WebGL rendering is not accessible by itself. The table view is the accessible equivalent, not an afterthought; both read the same viewport API.
- PRP-specific: reduced motion means no edge animation or transitions beyond essential state change; read `prefers-reduced-motion` and also offer an in-app toggle.

### External references
- sigma 4.0 and graphology 0.26, MIT, plus the @cosmograph CC-BY-NC prohibition: docs/adr/0002-stack-pins.md (observed 2026-10-08).
- WCAG 2.2 and reduced-motion guidance: https://www.w3.org/TR/WCAG22/ (W3C Recommendation; confirm the observed date when the WCAG audit in PRP-24 runs).
- Cosmos DB vNext Linux emulator limits (sandbox freshness numbers are bounded feasibility): https://learn.microsoft.com/azure/cosmos-db/emulator-linux (GA June 2026).
- Event Hubs emulator constraints (SAS only, no persistence): docs/RESEARCH-AND-GATES.md "Infrastructure and tooling" (observed 2026-10-08 per the register).

## Implementation blueprint

### Item 1 - websocket-gateway  [P]
- Deliverable: scoped WebSocket gateway fed from hot aggregates with per-session budgets and revocation-driven closure.
- Owned files (may edit): `services/api/neurosphere_api/realtime/`.
- Must NOT touch: `services/api/neurosphere_api/map/`, `services/api/neurosphere_api/replay/`, `services/workers/neurosphere_workers/aggregates/` (PRP-14), `neurosphere_core/auth/revocation/` (PRP-06), `frontend/`, root `pyproject.toml`, `docker-compose.yml`.
- Depends on: none.
- Acceptance criteria:
  - Revoked principal is disconnected within the configured TTL.
  - A cross-domain delta is never pushed, including after the session's permissions are narrowed mid-session.
  - Per-session message-rate and subscription budgets enforced with `rate_limited`.
- Pattern references: `IdentityScope` derivation; revocation interface; correlation ID middleware.
- Tests to write: `services/api/tests/realtime/test_revocation_closes_session.py`, `services/api/tests/realtime/test_scope_filter.py`, `services/api/tests/realtime/test_budgets.py`.

### Item 2 - viewport-api  [P]
- Deliverable: viewport API with domain clustering, drill-down and paginated expansion under node and edge budgets.
- Owned files (may edit): `services/api/neurosphere_api/map/`.
- Must NOT touch: `services/api/neurosphere_api/realtime/`, `services/api/neurosphere_api/replay/`, `packages/core/neurosphere_core/catalog/`, `frontend/`, root `pyproject.toml`.
- Depends on: none.
- Acceptance criteria:
  - Response never exceeds 2k nodes or the configured edge budget; overflow returns clusters plus a `truncated` flag.
  - Nodes outside scope never appear, including as intermediates; people are pseudonymized by default.
  - Response carries coverage and lag metadata from aggregates.
- Pattern references: `GraphQuery` budgets (PRP-10); pagination models (PRP-05).
- Tests to write: `services/api/tests/map/test_node_budget.py`, `services/api/tests/map/test_scope_and_pseudonyms.py`.

### Item 3 - map-renderer
- Deliverable: sigma.js and graphology WebGL view with node shapes per type, legends for tokens, context size, frequency, latency and health, observed-edge animation, and coverage labels.
- Owned files (may edit): `frontend/src/features/map/`.
- Must NOT touch: `frontend/src/features/map-table/`, `frontend/src/features/replay/`, `frontend/src/design-system/`, `frontend/src/api/`, `services/api/`, root `pyproject.toml`.
- Depends on: Item 2.
- Acceptance criteria:
  - Performance test at 2k nodes records measured fps and hardware; target is >=30fps on the documented hardware.
  - Reduced motion disables edge animation; only observed edges animate; inferred edges are static.
  - Partial or delayed coverage is labelled on the map; no `@cosmograph` dependency.
- Pattern references: Fluent UI v9 tokens; typed API client; node-type icon set from PRP-04.
- Tests to write: `frontend/src/features/map/map.test.tsx`, `frontend/tests/e2e/map-perf.spec.ts`, `frontend/tests/e2e/map-reduced-motion.spec.ts`.

### Item 4 - accessible-table-view  [P]
- Deliverable: table alternative to the map with keyboard navigation and non-color status indicators.
- Owned files (may edit): `frontend/src/features/map-table/`.
- Must NOT touch: `frontend/src/features/map/`, `frontend/src/features/replay/`, `frontend/src/design-system/`, `services/api/`.
- Depends on: Item 2.
- Acceptance criteria:
  - axe reports no serious or critical issues on the table route.
  - Full keyboard traversal including drill-down and expansion (e2e).
  - Health status conveyed by text or icon shape in addition to color.
- Pattern references: Fluent UI v9 DataGrid; viewport API client.
- Tests to write: `frontend/src/features/map-table/map-table.test.tsx`, `frontend/tests/e2e/map-table-keyboard.spec.ts`.

### Item 5 - replay-viewer  [P]
- Deliverable: trace tree viewer and API with timings, errors, tool interactions, and labels for gaps, sampling and late spans.
- Owned files (may edit): `frontend/src/features/replay/`, `services/api/neurosphere_api/replay/`.
- Must NOT touch: `frontend/src/features/map/`, `frontend/src/features/map-table/`, `services/api/neurosphere_api/actions/`, `connectors/`, root `pyproject.toml`.
- Depends on: none.
- Acceptance criteria:
  - Replay endpoint has no action capability: no write routes and no import of the action executor or connectors (static analysis plus test).
  - Gaps, sampling and late spans are labelled; payloads shown only if policy and opt-in allow.
  - Cross-domain traces are never returned; routes use `require(permission)`.
- Pattern references: router per module; redacted archive access via scope-checked reader.
- Tests to write: `services/api/tests/replay/test_replay_readonly.py`, `services/api/tests/replay/test_replay_scope.py`, `frontend/src/features/replay/replay.test.tsx`.

### Item 6 - freshness-test
- Deliverable: load test measuring event-to-view freshness under sandbox load and writing evidence.
- Owned files (may edit): `tests/load/map_freshness/`, `docs/evidence/G07/map/`.
- Must NOT touch: `tests/load/profiles/` (PRP-21), `services/`, `frontend/`, `docs/RESEARCH-AND-GATES.md`.
- Depends on: Items 1, 3.
- Acceptance criteria:
  - Measured event-to-view p95 recorded as evidence JSON plus markdown; target p95 <=10s is shown as a target beside the measurement.
  - Evidence labels the environment (compose emulators, sandbox load, hardware).
  - Test fails loudly, not skips, if the stack is unreachable.
- Pattern references: PRP-02 evidence format; sandbox generator load mode.
- Tests to write: `tests/load/map_freshness/test_freshness_p95.py`.

## Validation gates
```
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode fast    # per item
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full    # before merge
python scripts/validate_planning.py
```
Feature-specific:
```
docker compose --profile app up -d --wait
python -m pytest services/api/tests/realtime services/api/tests/map services/api/tests/replay
python -m pytest -m integration tests/integration/map
python -m pytest tests/load/map_freshness
pnpm --filter frontend test
pnpm --filter frontend exec playwright test frontend/tests/e2e/map-perf.spec.ts frontend/tests/e2e/map-table-keyboard.spec.ts frontend/tests/e2e/map-reduced-motion.spec.ts
```
A live Commercial freshness run is optional: operator-approved, requires NS_LIVE_APPROVED=1, using the PRP-21 load profile scripts once they exist.

## Live and open gates
- G07 (workload/SLO/DR): item 6 supplies map freshness evidence from sandbox load only; G07 stays OPEN until PRP-21 measures sized profiles and a live run.
- G12 (emulator parity): record where emulator timing differs from a live account.
- Browser fps on documented hardware is recorded as evidence in item 3; it is a target, not a guarantee.
- If a live item did not run, record it OPEN in the completion note and in docs/RESEARCH-AND-GATES.md; never report it as a skipped green test.

## NOT building
- Full WCAG audit across all routes and theming (PRP-24).
- Enterprise-scale or stress load profiles (PRP-21).
- Copilot map interaction (PRP-19) and any action launched from the map beyond a link to PRP-17 dialogs.
- Re-execution of traces or any side-effectful replay.
- Rendering the full enterprise graph, or any `@cosmograph` renderer.
- Changes to the revocation interface (PRP-06) or hot aggregates (PRP-14); request them from the owning PRP.

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
- Measured fps and hardware:
- Measured freshness p95 and environment (or OPEN):
- Follow-ups:
