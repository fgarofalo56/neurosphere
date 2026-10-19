# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/). Release automation arrives with PRP-13.

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

### Removed
- Legacy Kong / Data API Builder / Artemis procurement demo scaffold.
- `pre-commit` framework config (replaced by `.githooks/`).
