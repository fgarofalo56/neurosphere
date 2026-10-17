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

### Removed
- Legacy Kong / Data API Builder / Artemis procurement demo scaffold.
- `pre-commit` framework config (replaced by `.githooks/`).
