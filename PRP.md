# PRP — NeuroSphere

> Product Requirement Prompt (build spec). This is the single source of
> truth for the build session. Fill every section, then build phase by
> phase keeping each phase green (lint + tests + compose smoke) before
> the next.

## 1. Mission

Enterprise AI agent governance, catalog, telemetry, and recommendation platform — Azure-first (Commercial + Government), Purview/Unity Catalog lineage integration, pluggable analytics backend (Fabric/Synapse/Databricks), real-time visual ecosystem map, permission-gated AI Copilot, MCP integration, FedRAMP-aligned with ATO accelerator.

## 2. Success criteria

- [ ] `cp .env.example .env && make demo` brings the stack up healthy and
      prints the headline answer **through the gateway** (with a
      correlation id).
- [ ] Auth at the edge: no token -> 401, valid token -> 200, over-limit
      -> 429.
- [ ] Zero-move proven by `tests/test_zero_move.py` (system of record
      unreachable from the client network).
- [ ] Catalog entry + OpenAPI discoverable; MCP tool answers the same
      question an agent would ask.
- [ ] Observability dashboard shows per-consumer calls + latency.
- [ ] Any external pricing is live + dated; `tests/test_no_fabric.py`
      passes; all docs present; CI green.

## 3. Architecture

Describe the zero-move flow: consumer / MCP agent -> gateway (JWT +
rate-limit + meter + correlation-id) -> auto-API over the system of
record -> system of record (data never leaves). Map each local / OSS
component to its managed cloud equivalent (see `docs/ARCHITECTURE.md`).

## 4. Tech stack (pin versions here)

Docker Compose · PostgreSQL · Data API Builder · Kong Gateway OSS
(DB-less) · local RS256 JWT issuer · Python 3.11 + FastAPI (catalog,
seeder, MCP) · `mcp` SDK · httpx · Prometheus + Grafana · `ruff` +
`pytest` + pre-commit + GitHub Actions.

## 5. Repo structure

See the scaffolded tree (this repo). Each `services/*` and `tools/`
folder has a one-line README naming what to build there.

## 6. Phases (keep each green before the next)

1. **Scaffold** — confirm the tree, env, CI, lint baseline.
2. **Data / system-of-record** — seed the synthetic dataset; apply the
   classification labels.
3. **Auto-API** — Data API Builder over the SoR (REST + GraphQL +
   OpenAPI).
4. **Identity / gateway** — local JWT issuer + gateway (JWT, rate-limit,
   metering, correlation-id).
5. **Catalog / discovery** — publish the OpenAPI + owner + classification
   + request path.
6. **Consumers** — Python client + MCP tool answer the headline question
   through the gateway.
7. **Observability** — Prometheus + Grafana per-consumer dashboard.
8. **Docs / Azure** — fill the doc stubs + the Azure deployment
   reference.
9. **Optional UI** — a thin frontend over the catalog + query.

## 7. Hard constraints

See `CLAUDE.md` (the seven non-negotiables). CI enforces them where
possible.

## 8. Definition of done

Every box in §2 checked, every doc stub filled, CI green, and a
`docs/DEMO-SCRIPT.md` a presenter can follow live in ~10 minutes.
