# CLAUDE.md — neurosphere

You are the coding agent building this proof-of-concept. **Read `PRP.md`
in full first** — it is the complete, self-contained build spec
(mission, success criteria, architecture, tech stack, repo structure,
phased plan, per-file contracts, hard constraints, Definition of Done).
Build exactly what it specifies.

## Mission (one line)

Enterprise AI agent governance, catalog, telemetry, and recommendation platform — Azure-first (Commercial + Government), Purview/Unity Catalog lineage integration, pluggable analytics backend (Fabric/Synapse/Databricks), real-time visual ecosystem map, permission-gated AI Copilot, MCP integration, FedRAMP-aligned with ATO accelerator.

## How to work

- **Follow the phases in `PRP.md`** (Scaffold -> Data/SoR -> Auto-API ->
  Identity/Gateway -> Catalog/Discovery -> Consumers -> Observability ->
  Docs/Azure -> optional UI). Keep each phase green (lint + tests +
  compose smoke) before starting the next.
- **Use TodoWrite** to track the phase tasks. Commit per phase with
  conventional messages (`feat:`, `fix:`, `docs:`, `chore:`).
- **If `data/synthetic_data.py` is present**, the synthetic dataset is
  already provided — the seeder calls its generator; don't rewrite it.
- **If `docs/whitepapers/` is present**, that is the program narrative —
  the running code is the proof of that narrative; keep them consistent.
- Finish only when every box in the Definition of Done is checked, then
  write `docs/DEMO-SCRIPT.md` a presenter can follow live in ~10 minutes.

## Hard constraints (non-negotiable — CI checks where possible)

1. **No Microsoft Fabric / OneLake** as a component or recommendation
   (not in Azure Gov / GCC). A single "explicitly excluded, and why"
   sentence in docs is fine. `tests/test_no_fabric.py` greps the repo.
2. **Zero-move is real, not just claimed.** The system of record and the
   auto-API attach only to an `internal` network; the ONLY path to data
   for clients is **through the gateway**. `tests/test_zero_move.py`
   proves the SoR is unreachable from the client network.
3. **Any external pricing is live + dated, never invented.** Pricing
   helpers hit the public source API and every figure carries a dated
   source note. **No staffing / services dollar figures anywhere.**
4. **Synthetic data only.** The `data/README.md` "SYNTHETIC" banner
   stays; no real-data ingestion paths. ITAR / CUI-safe.
5. **Gateway framed vendor-neutral** in docs — the built path is the OSS
   gateway; the managed cloud equivalent is documented; competitors are
   not named in comparisons.
6. **Open standards** — OData-style REST, OpenAPI, OAuth2 / JWT, MCP. No
   proprietary client required to consume the API.
7. **Data-platform posture** (for the Azure-deployment doc): the managed
   platform runs in **commercial Azure at FedRAMP High** by default; any
   managed-service gap is the **Azure-Government (ITAR / strict-CUI)
   exception only**, not the default. Don't present the OSS fallback as
   the primary.

## Coding conventions

- Python: `ruff format` + `ruff check` clean; type hints; small,
  testable modules; fail-safe (services degrade gracefully, never crash
  on a missing optional dep).
- Config via `.env` (copy from `.env.example`); never commit secrets.
- Every service has a Dockerfile + a healthcheck; `docker-compose.yml`
  uses `depends_on: condition: service_healthy`.
- Keep `README.md` quickstart working from a clean clone on a machine
  with only Docker.

## Definition of done

See `PRP.md`. In short: `cp .env.example .env && make demo` brings the
stack up healthy and prints the headline answer sourced **through the
gateway** (with a correlation id); no-token -> 401, valid token -> 200,
over-limit -> 429; zero-move proven by test; catalog + MCP work; Grafana
shows per-consumer traffic; live dated pricing prints; `test_no_fabric.py`
passes; all docs present; CI green.
