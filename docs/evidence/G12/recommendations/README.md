# G12 evidence: PRP-15 recommendations engine (bounded feasibility, in-memory)

Date measured: 2026-10-19. Gate G12 (emulator parity) stays OPEN. This document records what the
PRP-15 recommendations pipeline detected on generated sandbox data, and, just as important, what
this run could not exercise.

## What was run

`neurosphere_workers.recommendations.pipeline.run_pipeline` over a generated sandbox output
directory: bounded rules (cost spike, latency degradation, error rate, unused agent), duplicate
candidates over the presented catalog, and right-sizing projections priced from a SYNTHETIC
snapshot of the sandbox price sheet (`sandbox-prices-2026-10`). Every record is stored in an
`InMemoryRecommendationStore` and read back through the store (the same store the API serves).

Reproduce (about 1 minute, no network, fixed seeds, no wall clock):

```
uv run python tests/integration/recommendations/measure_detection.py
```

The suites that back the numbers (about 20 s and 40 s):

```
uv run pytest tests/integration/recommendations -q
uv run pytest services/workers/neurosphere_workers/recommendations -q
```

## Definitions

- An anomaly is **detected** for an agent when the stored recommendation of the matching kind lists
  the agent and its `evidence_status` is `sufficient`. A cold-start record ("insufficient
  history") is a bounded result, not a detection.
- A **false positive** is a detected agent that no manifest anomaly of any type names.
  **cross_type** counts detected agents that the manifest labels with a different anomaly type:
  the injected cost spikes multiply tokens and volume, so those agents genuinely also trip the
  latency rule. This is a real effect, reported apart, not hidden.
- Duplicate **precision** and **recall** compare stored `candidate_duplicate` subject pairs with
  the manifest's `duplicate_agent_candidates` pairs. Pairs between `review_floor` and
  `min_similarity` are `review_candidates`, reported and not stored as recommendations.

## Results

Sandbox generator: `custom` profile, cloud `commercial`, default bad-event rates, 7 days.
Counts are detected/total per run.

### Dense profile, 1 duplicate pair (the rules suite profile): 40 agents, 4 domains, ~20 traces/agent-day

| Seed | cost_spike | latency_regression | unused_agent | false positives | duplicates (predicted / TP / labelled) | projections emitted / skipped |
|------|-----------|--------------------|--------------|-----------------|----------------------------------------|-------------------------------|
| 3    | 3/3       | 3/3 (3 cross_type) | 3/3          | 0               | 1 / 1 / 1                              | 18 / 0                        |
| 11   | 3/3       | 3/3 (3 cross_type) | 3/3          | 0               | 1 / 1 / 1                              | 18 / 0                        |

### Dense profile, 3 duplicate pairs: 40 agents, 4 domains, ~20 traces/agent-day

| Seed | cost_spike | latency_regression | unused_agent | false positives | duplicates (predicted / TP / labelled) | projections emitted / skipped |
|------|-----------|--------------------|--------------|-----------------|----------------------------------------|-------------------------------|
| 3    | 3/3       | 2/3 (3 cross_type) | 3/3          | 0               | 3 / 3 / 3                              | 20 / 0                        |
| 11   | 3/3       | 3/3 (3 cross_type) | 3/3          | 0               | 3 / 3 / 3                              | 17 / 0                        |
| 7    | 3/3       | 2/3 (3 cross_type) | 3/3          | 0               | 3 / 3 / 3                              | 10 / 0                        |

Changing the number of duplicate pairs changes the generator's random stream, so the same seed
yields different agents; one latency anomaly per run is missed in two of five dense runs. This is
data density plus threshold, recorded by item 1 as well.

### Pilot density: 200 agents, 8 domains, ~2 traces/agent-day (5 cost spikes, 5 latency, 4 unused, 4 duplicate pairs)

This is the pilot's traffic density at reduced size. The full pilot profile (1000 agents, 20
domains) was NOT run.

| Seed | cost_spike | latency_regression | unused_agent | false positives | duplicates (predicted / TP / labelled) | projections emitted / skipped |
|------|-----------|--------------------|--------------|-----------------|----------------------------------------|-------------------------------|
| 3    | 5/5       | 0/5                | 4/4          | 1 (latency)     | 4 / 4 / 4 (14 review candidates)       | 84 / 0                        |
| 11   | 5/5       | 0/5 (4 cross_type) | 4/4          | 1 (unused)      | 4 / 4 / 4 (7 review candidates)        | 79 / 0                        |

## Limits stated plainly

- **Latency recall drops on the sparse pilot density.** With about 2 traces per agent per day, a
  daily latency median rests on a handful of requests; none of the five injected regressions was
  detected (0/5 on both seeds) and one unlabelled agent was flagged per seed. Cost-spike and
  unused-agent detection held at 100%. Latency detection needs denser telemetry or a tuned
  threshold; it is not claimed for the pilot profile.
- **The false positives at pilot density** (one latency on seed 3, one unused on seed 11) were not
  root-caused here. Item 1 recorded an unlabelled zero-event sub-agent being flagged unused at this
  density; whether that explains seed 11 was not verified.
- **Duplicate thresholds were tuned on the same pilot seeds** (`min_similarity` 0.9,
  `review_floor` 0.7, item 2). Precision and recall of 1.0 here are a pilot-set fit, not
  held-out evidence, and each run has only 1 to 4 labelled pairs. The acceptance target (at least
  80% precision) is a pilot-set target, not a general claim.
- **In-memory stores, not emulators.** No Cosmos recommendation store exists yet (OPEN), so
  RU cost, range and composite indexes, 429 behaviour and Entra are not exercised. The catalog
  read by the duplicate job is an in-memory repository loaded from the sandbox files.
- **Everything is synthetic.** The sandbox data, the price sheet `sandbox-prices-2026-10` (invented
  numbers, `synthetic: true`) and every projection derived from it. Projections are labelled
  estimates that cite the synthetic price version; they say nothing about real prices or savings.
- **No live calls**: no network, no cloud, no paid model calls, no Retail Prices API call.
  Government price applicability is untested (G01).
- The routing interface is the in-memory `ReviewRouter` stub; the real PRP-17 review queue and
  action executor do not exist yet. Execution is refused with `capability_unavailable` (409).
- A production `AgentSeriesSource` needs an agent dimension on the PRP-11 analytics contract and
  its adapters (OPEN, PRP-15 delta D1). The sandbox file reader is the only implementation.
