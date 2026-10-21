# G07 live map event-to-view freshness evidence (PRP-18 item 6)

**Label: sandbox on compose, emulators; bounded feasibility** (the in-memory file is labelled
`in-memory`). Measured on one developer machine (Windows 11, AMD Ryzen 9 5950X, 32 logical CPUs,
127.9 GiB RAM, Python 3.12.13), 2026-10-21, at git SHA `3bde2f5` (the PRP-18 integration branch
this item was built on; the SHA is also inside each JSON). This is not a performance guarantee or
an SLA.

## What was measured

Event-to-view freshness, defined exactly:

* **t0** = the instant (`time.perf_counter`) a synthetic normalized telemetry event is handed to
  the worker's aggregate rollup path, immediately before `AggregateProjection.handle(entry)` is
  awaited. This is the real `neurosphere_workers.aggregates` handler and rollup code writing the
  real aggregate store.
* **t1** = the instant (same clock) a subscribed WebSocket client receives a `delta` whose node
  `frequency` (the domain's request count in the current hour bucket) has reached the event's
  ordinal within its domain, so the frame's aggregates reflect that event.
* **freshness** = t1 - t0, one sample per (subscriber, event).

Pipeline: synthetic `model_call` events (domain ids from the sandbox generator's world plan, as in
the PRP-14 dashboards load test; about 5% errors, 3% unknown outcomes, 10% without a duration) ->
`AggregateProjection.handle` -> aggregate store -> `AggregateDeltaSource` polling (real
`RealtimeSettings`: 2 s poll interval, 1 s read cache) -> gateway pump with its send-time scope
filter -> WebSocket client, through the real FastAPI app with dev-issuer tokens. Each subscriber is
a principal whose scope holds one domain; it also tries to subscribe to a second domain it does not
hold. Correctness is asserted: every event became visible to every subscriber of its domain, every
out-of-scope subscription was refused, and the count of deltas received for a domain outside a
subscriber's scope is **0**.

## Exclusions (also listed in each JSON)

* **Event Hubs transport and the ingest edge** are not in the loop: the Event Hubs emulator lacks
  Entra and the ingest edge is measured elsewhere. Events enter at the normalized, post-ingestion
  boundary, so real end-to-end freshness is this figure plus ingestion latency.
* **Provider billing freshness** (days of lag; the map shows the billing watermark instead).
* Entra / JWKS (dev-issuer tokens validated in memory), the network between client and API
  (in-process ASGI transport), browser rendering (see the placeholder below), RU accounting and
  index policy of a real account (G12), sized profiles (G07, PRP-21).

## Files

| File | Backend | Domains | Events | Subscribers | Samples |
|------|---------|---------|--------|-------------|---------|
| `p95.json` | `InMemoryAggregateStore` | 3 | 30 (5/s for 6 s) | 6 (2 per domain) | 60 |
| `p95_emulator.json` | `CosmosAggregateStore` on the compose Cosmos vNext emulator | 3 | 30 (5/s for 6 s) | 6 (2 per domain) | 60 |

Each JSON also holds p99, mean, the definition, the environment block (OS, CPU model, logical CPUs,
RAM, Python, poll interval, read-cache TTL, revocation TTL, knobs), the exclusions, the generator
slip (max 17 ms in both runs, so the writer kept the schedule), the correctness counters, the
timestamp and the git SHA.

Reproduce: `uv run pytest -q tests/load/map_freshness -s` (in-memory; runs in CI, about 10 s) and
`uv run pytest -q -m integration tests/load/map_freshness -s` (emulator; needs
`docker compose up -d --wait`, fails loudly rather than skipping when it is unreachable).
Knobs: `NS_MAP_FRESHNESS_EVENTS_PER_SECOND` (5), `NS_MAP_FRESHNESS_DOMAINS` (3),
`NS_MAP_FRESHNESS_DURATION_SECONDS` (6), `NS_MAP_FRESHNESS_SUBSCRIBERS` (6). The poll interval is
the product setting `NS_REALTIME_POLL_INTERVAL_SECONDS`. Results land in `temp/map_freshness/`
(gitignored); these files are copies. The tests record the numbers and assert correctness only,
never a latency threshold.

## Results (seconds)

| Statistic | In-memory | Emulator | Target |
|-----------|-----------|----------|--------|
| p50 | 1.003 | 1.085 | |
| **p95** | **2.003** | **2.028** | **<= 10 s (PRD planning target: a target, not a guarantee)** |
| p99 | 2.004 | 2.103 | |
| max | 2.004 | 2.103 | |
| mean | 1.032 | 1.124 | |
| `meets_target` | true | true | |

Reading the numbers: the figures sit at the poll interval because that dominates. A session's
pump polls every 2 s on its own phase, so an event waits between 0 and 2 s for the next poll
(p50 about 1 s, max about 2 s), and the 1 s shared read cache did not add a visible tail here.
Rollup and store write time is not timed separately; the writer never fell more than 17 ms
behind its schedule, so it kept pace with the load, and the distribution has no visible tail
beyond the poll interval.
The three consecutive in-memory CI-shaped runs gave p95 2.008, 1.996 and 2.003 s. Raising the poll
interval raises these figures nearly one for one; a real account adds RU throttling and network.
These numbers narrow the planning target only for this shape of load (5 events/s, 3 domains,
6 subscribers, 30 events), not for a sized profile.

## Gate status

* **G07 stays OPEN.** No live Commercial run was made and sized profiles belong to PRP-21; this
  is bounded-feasibility evidence from emulators and an in-memory store.
* **G12 (emulator parity):** the Cosmos vNext emulator has no RU accounting, so there is no
  throttling or 429 retry time in `p95_emulator.json`, and it runs on the local network (no
  cross-region or private-endpoint latency), without the range/composite index policy of a real
  account. On a live account the store read and write legs will differ; the poll-interval
  component will not.
* Event Hubs transport and provider billing freshness are not measured here (see Exclusions).

## Browser frame rate (item 3)

**Label: one developer workstation, headed Chromium against the e2e mock API; hardware-specific.**
Measured 2026-10-21 by the orchestrator on the item 3 rework commit `bb9040c` (the merged code
differs only by import paths, `5a0622c`). This is not a universal frame-rate claim.

**Documented hardware:** AMD Ryzen 9 5950X (16 cores, 32 threads), 128 GB RAM, NVIDIA GeForce
RTX 5090 through ANGLE Direct3D11 (WebGL 2.0), Windows 10.0.26300, Chromium 156 (Playwright),
Node 24.20.

**What was measured:** `frontend/tests/e2e/map-perf.spec.ts` loads the deterministic 2,000-node,
4,000-edge mock viewport (`commercial:e2e:sandbox:domain:map-perf`), drives a live session through
a fake gateway WebSocket so observed-edge animation is on (1,334 animated edges), then counts
`requestAnimationFrame` frames over a 5 s window while the camera pans and zooms every frame.
fps mean is frames over elapsed time; fps p5 is derived from the 95th-percentile frame time (the
slowest 5% of frames).

| File | fps mean | fps p5 | frame time p95 (ms) | frames in 5 s |
|------|----------|--------|---------------------|---------------|
| `fps-run1.json` | 41.84 | 29.94 | 33.4 | 211 |
| `fps-run2.json` | 41.03 | 30.03 | 33.3 | 206 |
| `fps-run3.json` | 38.57 | 24.04 | 41.6 | 194 |

**Against the target (PRD planning target >= 30 fps at 2k visible nodes on documented hardware):**
the mean met it in all three runs; the slowest 5% of frames did not in run 3 (24 fps) and sat at
the line in runs 1 and 2. Treat the target as met on average, not at the tail, on this hardware.
An earlier measurement on the pre-rework commit `c940730` (same hardware) gave mean 37.2 / 30.5 /
32.2 and p5 29.9 / 24.0 / 24.0; caching the observed-edge id list per frame raised the mean.

**Not a hardware result:** headless Chromium falls back to SwiftShader software GL and measured
about 4-5 fps mean on the same machine. Headless and CI numbers say nothing about the target.

Reproduce (run alone, nothing else heavy on the machine):
`cd frontend && NS_MAP_PERF_HEADED=1 NS_MAP_PERF_ENFORCE=1 pnpm exec playwright test tests/e2e/map-perf.spec.ts --reporter=line`;
results land in `temp/map-perf/fps.json`.
