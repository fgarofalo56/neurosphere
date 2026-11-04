# Seeding the synthetic catalog (local compose)

A fresh compose stack starts with an empty catalog. The `seed` compose service loads the synthetic
sandbox catalog (entities and edges) through `CatalogRepository`, idempotently, with no host-side
Python. It is for the local emulator stack only.

## Run it

```bash
docker compose --profile seed run --rm --build seed
```

`make stack-up` runs it as its last step. Output is one JSON line on stdout, for example
`{"seeded": {"edges": 120, "entities": 87, "grants": 6}, "skipped_existing": 0}`; a second run
reports zero seeded and a non-zero `skipped_existing` (it never duplicates).

Needs the emulators up (`docker compose up -d --wait`) and, so the workers' scope matches, the
same `NS_ENTRA_TENANT_ID` and `NS_WORKER_OBJECT_ID` as the app profile (the default worker id in
`docker-compose.yml` equals the Makefile's `STACK_WORKER_OID`; a test pins it).

## What it does and does not do

- Generates the `small` sandbox world in the container, grants the workers' own scope (the same
  grants as `make seed-stack`), then writes entities via the stack seed's `seed_entities` and
  edges via `put_edge`. Edge ids are the ingestion projection's deterministic ids, so the
  projection merges into seeded edges later instead of duplicating them.
- Aliases: the sandbox generator emits none, so none are seeded.
- Reads no production data and holds no secret: the emulator key is built at runtime.
- It does not publish telemetry or write costs, recommendations, reports or MCP servers. Use
  `make seed-stack` for the full stack seed (it also writes entities; the two are compatible).

## Safety

- **Refuses unless `NS_ENV=local`** (and `NS_CLOUD=commercial`): any other value, including unset,
  `hosted`, or a Government profile, exits `2` with `REFUSED: refusing to seed synthetic data ...`
  before any backend is opened. Hosted and Government stacks never receive synthetic data.
- The loopback-only `sbx_guard` rules are unchanged. The service shares the `cosmos` container's
  network namespace (`network_mode: service:cosmos`), so it talks to `127.0.0.1:8081`.
- Exit codes: `0` seeded or already seeded, `2` refused, `3` failed.

## Verification status

Unit tests (`tests/unit/sandbox_stack/test_seed_catalog.py`) cover the in-memory repository,
idempotence, the refusals and the compose wiring. A run against the live Cosmos emulator is a
local check: seed twice and compare `skipped_existing`.
