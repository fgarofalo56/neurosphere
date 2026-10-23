# G07 load evidence (PRP-21 item 1)

Environment label for every file here unless it says otherwise: **compose (emulators), bounded
feasibility only - not capacity evidence (G12)**. Targets are provisional PRD planning targets.

## Pilot result, 2026-10-22: FAILED the provisional thresholds

Pilot profile (1k agents, 1k events/s target), 60 s, synthetic events, single-worker local API
plus the compose Event Hubs emulator, client and server on one laptop.

| File | Users | Achieved events/s | Error ratio | Request p95 | Thresholds |
|---|---|---|---|---|---|
| `pilot-2026-10-22.json` (profile default) | 100 | 240 | 7.1% (44 client timeouts at 30 s) | 30,000 ms | 0 of 3 passed |
| `pilot-2026-10-22-users20.json` | 20 | 185 | 0% | 11,000 ms (p50 710 ms) | 1 of 3 passed (error ratio) |

Finding: the edge plus Event Hubs emulator on this setup tops out near 200-250 accepted events/s,
roughly a quarter of the 1k target. Beyond that, latency climbs into seconds and requests time
out; it is a ceiling of this setup (one worker, one emulator, shared host), not of the product.
Do not read it as capacity evidence in either direction. The `multi_domain` scenario (eight
partition keys per batch, each a separate emulator send) is the slowest. The skew shape held:
the hottest domain carried about 38x the median domain. No thresholds were tuned.

Observed emulator ceilings (G12), also in each file under `emulator_limits`: accepted-rate
ceiling above; no persistence, one namespace and ten hubs (documented limits); no Cosmos RU
accounting. Partition and consumer-group scale cannot be inferred from this run.

## Still OPEN

- Pilot at the 1k events/s target has not been met on compose.
- Enterprise (100k agents, 10k events/s sustained) and stress (1M entities / 10M relationships,
  50k sustained / 150k burst, "subject to partition/cost validation") have **not been run**. They
  are operator-run at a sized environment the operator names; nothing here is evidence for them.
- G07 stays OPEN.

## Reproduce

```
docker compose up -d --wait
uv run python tests/load/profiles/run_profile.py pilot --duration 60
uv run python tests/load/profiles/run_profile.py pilot --duration 60 --users 20 --suffix=-users20
docker compose --profile app down
```

Full instructions, including the enterprise and stress command lines, are in
`tests/load/profiles/README.md`.
