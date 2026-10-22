# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/). The release process is in `docs/release/release-process.md`.

## [Unreleased]

### Added
- Repository hygiene baseline: version-controlled git hooks, gitleaks config,
  CI without suppressed failures, CodeQL, Dependabot, issue/PR templates,
  CODEOWNERS, SECURITY and CONTRIBUTING guides.
- Orchestrated-PRP kit onboarding (`PRPs/`, `.claude/hooks/config.ps1`).
- Local emulator stack (`docker-compose.yml`): Cosmos DB vNext, Event Hubs, Azurite.
- Architecture decision records and decisions log.
- Split PRPs `PRP-00` to `PRP-27` with master index.
- Telemetry ingestion and cost ledger (PRP-07): authenticated OTLP/JSON and CloudEvents
  push edge, normalizer worker with dedupe, watermarks and bounded retries, blob quarantine
  with replay CLI, redacted archive, cost ledger with double-count resolution and outbox.
- Deployment intelligence and IaC (PRP-08): per-cloud Bicep modules with reuse inputs, Helm 4
  chart and App Service profile, consented read-only Resource Graph scan, reuse/create/skip
  planner projecting to `DeploymentManifest`, ownership register with a live-inventory-guarded
  uninstall, matrix-gated Fabric provisioning adapter, and the G01 Commercial deploy smoke gate.
- Connector SDK and reference connectors (PRP-09): Python and TypeScript connector SDKs with
  health/rate-limit/coverage/freshness reporting, vault credential references with rotation,
  a contract test kit and cross-SDK manifest interop; `WriteConnector` protocol for the action
  executor; reference connectors for generic OpenTelemetry/CloudEvents push, bounded Azure
  Monitor polling, Foundry discovery and Azure Cost Management exports with a billing-vs-ledger
  variance report; `docs/connectors/coverage.md`.
- Catalog and relationship governance (PRP-10): versioned `CatalogRepository` on Cosmos NoSQL
  and in memory with ETag concurrency, canonical IDs and aliases, scope-filtered queries and a
  single partition-key configuration point; bounded `GraphQuery` with depth, fan-out, node, edge
  and time budgets and presented lineage; curation decisions and locks with a review queue;
  outbox projection worker producing inferred INVOKES/USES_MODEL edges; catalog API (CRUD,
  search, lineage, import/export, recertification, stale-agent reconcile); Azure AI Search
  `AuthorizedSearch` with a server-side scope filter. G03 live benchmark run on a private,
  Entra-only Commercial account (the harness now provisions through the control plane);
  G03 narrowed for Commercial.
- Analytics adapters (PRP-11): `TelemetryAnalytics` and `RecommendationCompute` contracts with
  required `AnalyticsBudget` (time, rows scanned, cost units; breach cancels and raises
  `rate_limited`), a shared whitelisted-identifier SQL renderer, a matrix-gated registry that
  lists disabled backends with reasons, a sandbox-only fixture adapter, and Fabric, Synapse
  (serverless/dedicated) and Azure Databricks adapters with per-cloud host checks and versioned
  migrations; stub-endpoint equivalence and profile-gating suites (contract conformance only);
  `scripts/gates/g01_analytics_live.py`. Live analytics runs are OPEN for every adapter.
- Threat model and security baseline (PRP-12): STRIDE threat model per trust boundary with
  abuse-case DFDs (`docs/security/`), `security.yml` supply-chain workflow (syft SBOM, Trivy and
  Grype blocking on High, sha256-pinned binaries), Bicep network module with private endpoints for
  created resources only and a release-scoped default-deny Helm NetworkPolicy, a shared
  78-case prompt-injection corpus and harness (`tests/security/injection/`), and secrets,
  rotation, leak-response and incident runbooks. Live what-if is OPEN.
- Release tooling (PRP-13): SemVer policy with the contract and migration version mapping
  (`docs/release/versioning.md`), the operator release process
  (`docs/release/release-process.md`), and `scripts/release/changelog.py`, which builds
  Keep-a-Changelog sections from conventional commits. Multi-stage non-root production
  Dockerfiles for api, workers and frontend; tag-triggered `release.yml` publishing to GHCR
  with syft CycloneDX SBOM attestations, cosign keyless signatures verified in-workflow, the
  Helm chart as OCI and a draft GitHub Release (exercised on `v0.1.0-rc.1`); a versioned
  Cosmos/analytics migrations runner with ledger, rollback, dry run and expand-then-contract
  lint; and a release Definition-of-Done checklist (`docs/release/dod-checklist.md`).
- Dashboards for cost, latency and coverage (PRP-14): a hot-aggregates projection worker
  (90-day rolling day/hour rollups from the outbox, idempotent, null never 0, `complete` and
  watermark on every document) with a core `AggregateReader` store; scoped
  `GET /api/v1/dashboards/domains/{domain}/{metric}` and
  `GET /api/v1/reconciliation/domains/{domain}` APIs (403 outside scope, 503 fail closed,
  bounded budgets, `Server-Timing`); cost, latency/errors, coverage and reconciliation pages
  with estimated/invoiced and price-version badges, lag indicator and analytics-state chip;
  Playwright e2e on the mock API and measured G07 latency evidence
  (`docs/evidence/G07/dashboards/`).
- Recommendations engine (PRP-15): advisory-only, evidence-backed recommendations. Versioned
  bounded rules (cost spike, latency, error rate, unused agent) with no-score
  `insufficient_evidence` on cold start or sparse data and `unknown` coverage never reported as
  unused; read-only duplicate consolidation-review candidates over the presented catalog;
  immutable content-hashed price snapshots and right-sizing estimates that always cite a price
  version; scoped `GET /api/v1/recommendations/domains/{domain}` list, detail and search,
  review routing, and an executions route that always refuses (`capability_unavailable`);
  list and detail pages with advisory badge and route-to-review; sandbox pipeline, Playwright
  e2e and measured G12 evidence (`docs/evidence/G12/recommendations/`).
- Agent evaluation and quality (PRP-16): append-only versioned datasets, rubrics and judge
  configs with fail-closed judge approval (unknown classification is restricted, judge cloud must
  match, capability-matrix availability); a stratified, seeded sampling worker that checks
  classification and reserves worst-case token/cost budget before every judge call and stops
  with `budget_exhausted`; recorded-fixture judges only (no paid calls in CI); human-label
  calibration (agreement with interval, bias, coverage), Wilson intervals and PSI drift alerts;
  scoped `GET /api/v1/evaluation/domains/{domain}/results` and `/quality`; a quality page where
  every score carries judge version, calibration state and uncertainty, unknown is never 0, and
  the grounded-answer rate is a pilot-set target with a confidence interval, not a guarantee;
  sandbox pipeline, Playwright e2e and measured G12 evidence (`docs/evidence/G12/evaluation/`).
- Action executor and human-in-the-loop workflow (PRP-17): one durable action plane for button,
  chat, REST and MCP. Allowlisted intent state machine, PRP-01 confirmation hash bound to target,
  version, diff, expiry and actor (channel excluded), idempotent intent store (in-memory and
  Cosmos), and an executor worker that is the only caller of connector apply/rollback: it
  rechecks permission (token-free, revocation-aware), target version and the emergency kill
  switch, then dry-run, apply, verify-only canary, verify and audit, with rollback on failure,
  crash-safe resume that never re-applies and a lease kept alive across long connector calls.
  Maker-checker review queue with self-approval refused on real principal ids, append-only
  hash-chained decisions, durable SLA/escalation timers and stub notifiers that only record.
  `/api/v1/actions` and `/api/v1/review` APIs, a Foundry deployment-swap write connector with
  advisory mode for read-only or Government targets, and a confirmation dialog showing exact
  target, version, diff and expiry. G05 stays OPEN (live swap not run); production action
  execution remains blocked.
- Live map and session replay (PRP-18): scoped WebSocket gateway at `/api/v1/realtime/ws` fed
  by hot aggregates, with `ns.bearer` subprotocol auth, send-time scope filtering, per-session
  budgets and revocation fan-out that closes sockets (4403). Bounded viewport API at
  `/api/v1/map` (2000-node cap, kind clusters, paginated expansion, pseudonymized people,
  coverage and lag). sigma.js 4 + graphology WebGL map that animates observed edges only while
  the session is live and coverage is fresh, with reduced motion, plus an accessible treegrid
  table on the same API. Read-only trace replay at `/api/v1/replay` with gap, sampling and
  late-span labels and a static ban on action, executor and connector imports. Measured, not
  guaranteed: freshness p95 about 2 s on emulators (poll-interval bound) against a 10 s target;
  38.6-41.8 fps mean at 2k nodes on one documented workstation, with p5 below 30 fps. G07 stays
  OPEN (no live run).
- Copilot and report creation (PRP-19): allowlisted server tool registry that only ever sees the
  server-derived `IdentityScope` (scope-shaped arguments refused and logged), with tool-produced
  citations carrying data freshness. Copilot API at `/api/v1/copilot` streams SSE with
  first-class `abstain` and `denied` terminals, an output guard, chat-only action drafting
  through the PRP-17 executor, and redacted, owner-only conversations with retention.
  `ModelAdapter` protocol with recorded-fixture, approved-endpoint and optional Foundry Agent
  Service adapters behind one action contract, gated by the capability matrix (Government never
  routed to Commercial). Server-validated Vega-Lite subset rendered by `vega-interpreter` in a
  sandboxed iframe under a sha256 CSP. Saved reports at `/api/v1/reports` store plan and query
  only, re-validate and re-authorize as the viewer on every run, and need a second
  `config.manage` principal to publish. Chat dock UI with context chip, citations and inline
  charts. The PRP-12 injection corpus passes 78/78 with 0 overscoped retrievals. First token
  measured, not guaranteed: p95 about 140 ms with recorded fixtures (provider time excluded)
  against a 3 s planning target; live model run OPEN.
- UI shell and usability (PRP-28): Fluent v9 app shell with header, user menu, skip link and
  grouped permission-aware navigation (hiding is not authorization; the API still denies). A
  domain switcher is fed by the new `GET /api/v1/me/domains`, which returns the caller's
  `data.read` domains, derived server-side only. `?domain_id=` stays the source of truth, and
  the last domain id is remembered under a pseudonymous key. Adds the real
  `GET /api/v1/workspaces/{role}` with an explicit role map. Shared page template, and Fluent
  controls on every feature page; a static test allows no native form controls beyond a
  2-entry allowlist. Role-aware overview tiles never sum currencies, never invent counts ("N+"),
  and never show 0 for unknown data. `pnpm demo` runs the UI against the mock API with stub
  sign-in and a demo banner; tests prove neither ships in production builds or deployment
  artifacts. The CI frontend job timeout is now 25 minutes.

### Removed
- Legacy Kong / Data API Builder / Artemis procurement demo scaffold.
- `pre-commit` framework config (replaced by `.githooks/`).
