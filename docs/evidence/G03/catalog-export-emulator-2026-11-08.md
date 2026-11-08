# G03 catalog export / read latency on the Cosmos emulator (2026-11-08)

Date: 2026-11-08. PRP-10 item 13 (export-p95-on-cosmos).

**Cosmos vNext emulator, bounded feasibility (G12), not a live claim: no RU accounting, no
range/composite indexes.** Nothing here is evidence for the PRP-10 p95 target (<= 500 ms on
indexed scoped queries). No latency threshold is asserted anywhere in the test.

**live export p95: OPEN (not run; needs operator approval).** The live mode exists
(`pytest -m live`, needs `NS_LIVE_APPROVED=1`, `NS_CATALOG_LATENCY_LIVE_ENDPOINT`,
`NS_CATALOG_LATENCY_LIVE_DATABASE`, Entra via `DefaultAzureCredential`) and refuses otherwise
(unit-tested in `tests/load/catalog_latency/test_live_guard.py`). It was not run.

## Setup

- Backend: `CosmosCatalogRepository` (flat domain partition key) on the compose vNext emulator,
  `http://127.0.0.1:8081`, throwaway database and container, deleted after the run.
- Dataset: `sandbox/` generator, custom profile, seed 7, 8 domains, 200 agents; 305 entities,
  1140 edges loaded. The caller is an analyst scoped to 3 of the 8 domains.
- Iterations: 60 per workload, cycling over the visible agents or domains.
- Export path: `CatalogService.export_page` (the service behind `GET /catalog/export`),
  one 100-item page of agents for one scoped domain, with the `data.export` domain check.
- Search uses the in-process fixture index, not Azure AI Search (not in the emulator).
- Run: `uv run pytest -q -s -m integration tests/load/catalog_latency`
  (`temp/catalog_latency/p95-emulator.json`, gitignored).

## Results (ms)

| Workload | Emulator p50 | Emulator p95 | Emulator max | In-memory p50 | In-memory p95 | In-memory max |
|---|---:|---:|---:|---:|---:|---:|
| get_entity | 48.172 | 49.858 | 52.812 | 0.255 | 0.318 | 0.358 |
| list_entities_scoped | 51.007 | 55.134 | 68.109 | 0.714 | 0.883 | 2.180 |
| export_page_scoped | 50.388 | 54.197 | 62.215 | 0.800 | 0.880 | 1.166 |
| search (fixture index) | 144.093 | 334.393 | 359.208 | 0.950 | 2.135 | 2.237 |
| neighbors_depth3 | 5028.517 | 5075.615 | 5089.099 | 100.462 | 145.804 | 171.078 |
| impact_paths_depth3 | 1103.595 | 2009.076 | 2403.664 | 8.829 | 17.646 | 20.096 |

## Deltas and reading (G12)

- Point reads, filtered list and scoped export are about 50 ms per call on the emulator versus
  under 1 ms in memory: a roughly 50x network/serialization floor per round trip. Export tracks
  list (same repository query plus the permission check), as expected.
- Graph workloads multiply that floor by the number of round trips. `neighbors_depth3` sits at
  about 5.0 s, which equals the 5000 ms request budget (`timeout_ms=5000`) plus overhead, so
  that workload is most likely budget-bound rather than a clean traversal time. Treat the
  figure as "hit the budget", not a traversal p95. Not investigated further (product code out
  of scope for this item).
- The emulator has no range/composite indexes and no RU accounting, so index behavior and RU
  cost are NOT characterised; the live account delta for both stays open under G12.
- The earlier G03 live figure (1.58-2.13 s) is graph traversal over WAN, not export. Live
  export p95 on an indexed account is still unmeasured.
