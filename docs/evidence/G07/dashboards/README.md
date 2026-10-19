# G07 dashboards latency evidence (PRP-14 item 5)

**Label: sandbox on compose, emulators; bounded feasibility.** Measured on one developer
machine (Windows 11, Python 3.12.13, 32 logical CPUs), 2026-10-19. This is not a performance
guarantee or an SLA.

## What was measured

Wall-clock p50, p95 and max of the dashboards endpoints and the reconciliation endpoint, called
through the real FastAPI app (token validation, scope derivation, router, aggregate reader,
response model) over an in-process ASGI transport, next to the server's own `Server-Timing:
app;dur=` figure. Endpoints: cost, latency, errors and coverage at the day grain over 90 days and
at the hour grain over 14 days, and reconciliation at the day grain over 90 days. Every request is
a 200 with data; a request for a domain the caller does not hold is checked to be a 403.

The documents come from the worker's real `rollup_bucket` over synthetic ledger entries and
`model_call` spans (about 10% of amounts and durations deliberately missing, so unknown cells are
exercised). Domain ids come from the sandbox generator's world plan.

| File | Backend | Domains | Documents | Requests | Iterations per endpoint |
|------|---------|---------|-----------|----------|-------------------------|
| `p95.json` | `InMemoryAggregateStore` | 3 | 7,284 | 1,509 | 100 |
| `p95_emulator.json` | `CosmosAggregateStore` on the compose Cosmos vNext emulator | 1 | 2,446 | 503 | 50 |

Reproduce: `uv run pytest -q tests/load/dashboards_latency -s` (in-memory, also runs in CI with a
small default) and `uv run pytest -q -m integration tests/load/dashboards_latency -s` (emulator,
needs `docker compose up -d --wait`). Knobs: `NS_DASHBOARDS_LATENCY_ITERATIONS`,
`NS_DASHBOARDS_LATENCY_DOMAINS`, `NS_DASHBOARDS_LATENCY_REQUESTS_PER_DAY`. The tests record the
numbers and assert correctness only, never a latency threshold.

## Results (wall clock, p95 in ms)

| Endpoint | In-memory p95 | Emulator p95 |
|----------|---------------|--------------|
| cost, day, 90 d | 11.2 | 144.0 |
| latency, day, 90 d | 10.4 | 64.2 |
| errors, day, 90 d | 9.9 | 63.7 |
| coverage, day, 90 d | 10.1 | 95.2 |
| cost, hour, 14 d | 16.5 | 251.6 |
| latency, hour, 14 d | 17.4 | 156.9 |
| errors, hour, 14 d | 14.4 | 173.8 |
| coverage, hour, 14 d | 11.8 | 144.5 |
| reconciliation, day, 90 d | 9.4 | 100.0 |

The slowest p95 observed is 251.6 ms (emulator, cost, hour grain); the in-memory maximum single
request was 116.9 ms. For comparison, the PRD planning target for dashboards is p95 <= 2 s on
bounded 90-day aggregates: **a target, not a guarantee**. Every measured p95 here is below it, on
this dataset shape and these backends only. p50, max and the `Server-Timing` figures are in the
JSON files.

## What this does not show (OPEN)

* **RU accounting, range/composite indexing and Entra are not reproduced** (gate G12). The Cosmos
  vNext emulator reports no request units and has no range or composite indexes, so the emulator
  figures say nothing about throttling, RU cost or index behavior on a real account. The harness
  validates dev-issuer tokens in memory, so no Entra or JWKS round trip is included.
* This narrows the dashboard planning target only. **Sized-profile and cost evidence stay OPEN**
  (gate G07, owned by PRP-21): the data here is a small sandbox, a handful of series per bucket,
  one machine, no concurrency, no network between the API and the store.
* The in-memory store scans documents without an index; its numbers describe the query and
  mapping code, not a database.
* Browser rendering time is not measured.
