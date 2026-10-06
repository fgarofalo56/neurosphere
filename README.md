# neurosphere

> Enterprise AI agent governance, catalog, telemetry, and recommendation platform — Azure-first (Commercial + Government), Purview/Unity Catalog lineage integration, pluggable analytics backend (Fabric/Synapse/Databricks), real-time visual ecosystem map, permission-gated AI Copilot, MCP integration, FedRAMP-aligned with ATO accelerator.

This repository is a runnable demo / proof-of-concept. It ships the
build spec, the project rules, and the scaffold a fresh Claude Code
session needs to implement it end to end.

> **Status: scaffold + build spec.** The services are not implemented
> yet. Everything a coding agent needs is in place: the complete build
> spec (`PRP.md`), the project rules (`CLAUDE.md`), the folder
> structure, and (optionally) the synthetic dataset and the program
> narrative under `docs/whitepapers/`. See **"Start the build"** below.

---

## What this is

NeuroSphere — Enterprise AI agent governance, catalog, telemetry, and recommendation platform — Azure-first (Commercial + Government), Purview/Unity Catalog lineage integration, pluggable analytics backend (Fabric/Synapse/Databricks), real-time visual ecosystem map, permission-gated AI Copilot, MCP integration, FedRAMP-aligned with ATO accelerator.

## Repo layout

```text
PRP.md                  # the complete build spec — read this first
CLAUDE.md               # project rules for the Claude Code build session
.claude/                # Claude Code config (settings, permissions)
data/                   # synthetic dataset generator + classification manifest
docs/                   # ARCHITECTURE / DEMO-SCRIPT / ZERO-MOVE / SECURITY / AZURE-DEPLOYMENT + whitepapers/
services/               # seeder · dab · gateway · identity · catalog · mcp
client/                 # consumer CLI that queries through the gateway
tools/                  # helper utilities (e.g. live Azure pricing)
observability/          # prometheus + grafana
infra/azure/            # Azure deployment reference (not required to run)
scripts/                # demo + helper scripts
tests/                  # the constraint + behavior test suite
frontend/               # optional UI
```

## Quickstart (after the build)

```bash
cp .env.example .env
make demo        # up -> wait-for-healthy -> seed -> run the client -> print the answer
```

## Start the build (Claude Code)

1. Open this folder in a fresh Claude Code session.
2. Tell it: **"Read PRP.md and CLAUDE.md, then build this exactly,
   phase by phase, until every box in the Definition of Done is
   checked."**
3. It will scaffold the services, implement them, wire CI, write the
   docs, and validate — keeping each phase green before the next.

## License

MIT — see `LICENSE`. (c) 2026 Frank Garofalo.
