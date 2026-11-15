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
  history", or since item 7 "too few request durations") is a bounded result, not a detection
  and not a false positive; it is counted separately.
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
| 3    | 3/3       | 3/3 (3 cross_type) | 3/3          | 0               | 3 / 3 / 3                              | 20 / 0                        |
| 11   | 3/3       | 3/3 (3 cross_type) | 3/3          | 0               | 3 / 3 / 3                              | 17 / 0                        |
| 7    | 3/3       | 3/3 (3 cross_type) | 3/3          | 0               | 3 / 3 / 3                              | 10 / 0                        |
| 5 (held out) | 3/3 | 3/3 (3 cross_type) | 3/3        | 0               | 4 / 3 / 3 (precision 0.75)             | 13 / 0                        |

Before item 7 (daily-median latency rule) seeds 3 and 7 of this profile detected 2/3 latency
regressions; the pooled-window rule detects 3/3 on all four seeds. Seed 5 was added as a held-out
seed (no threshold was set on it). Its duplicate row shows one extra predicted pair
(precision 0.75): duplicate detection is not part of item 7 and is unchanged.

### Pilot density: 200 agents, 8 domains, ~2 traces/agent-day (5 cost spikes, 5 latency, 4 unused, 4 duplicate pairs)

This is the pilot's traffic density at reduced size. The full pilot profile (1000 agents, 20
domains) was NOT run.

Latency columns: `detected / injected`, then injected regressions reported as
`insufficient_evidence` (a record with no score), then **silent misses** (injected, neither
detected nor reported; must be 0). Insufficient-evidence records are not detections and not false
positives; those on unlabelled agents are counted separately as `insufficient (unlabelled)`.

| Seed | cost_spike | latency detected | latency insufficient (injected) | latency silent misses | latency false positives (sufficient evidence) | insufficient (unlabelled) | unused_agent | unused false positives | duplicates (predicted / TP / labelled) | projections emitted / skipped |
|------|-----------|------------------|-------------------------------|----------------------|-----------------------------------------------|---------------------------|--------------|------------------------|----------------------------------------|-------------------------------|
| 3    | 5/5       | 0/5              | 5                             | 0                    | 1                                             | 62                        | 4/4          | 0                      | 4 / 4 / 4 (14 review candidates)       | 84 / 0                        |
| 11   | 5/5       | 3/5              | 2                             | 0                    | 2                                             | 65                        | 4/4          | 1                      | 4 / 4 / 4 (7 review candidates)        | 79 / 0                        |
| 5 (held out) | 5/5 | 3/5            | 2                             | 0                    | 4                                             | 54                        | 4/4          | 0                      | 4 / 4 / 4 (11 review candidates)       | 81 / 0                        |

Cross-type latency flags (cost-spike agents, whose 12x token injection genuinely lengthens their
durations): 3, 4 and 5 on the three seeds; reported apart, not counted as false positives.

Before item 7 (daily-median rule): 0/5 detected on seeds 3 and 11, all silent, plus one latency
and one unused unlabelled flag. After: no injected regression is silent. The rule detects
3 of 10 on the two tuned seeds and 3 of 5 on the held-out seed, and reports the rest as
insufficient evidence. It did NOT improve false alarms: sufficient-evidence latency false
positives went from 1 per seed to 1, 2 and 4.

## Limits stated plainly

- **Latency on sparse data is mostly "not enough evidence", by design.** Item 7 replaced the
  daily-median latency rule (version 1.0.0) with a pooled-window rule (version 2.0.0): request
  durations are pooled over the 3-day baseline and the 4-day recent window and the pooled p50s are
  compared at ratio 2.0, with a floor of `min_window_requests = 8` durations in EACH window. At
  ~2 traces/agent-day most agents have 4 to 12 request durations per window, so the floor leaves
  them with an `insufficient_evidence` record (no score, `uncertainty.method = not_estimable`,
  threshold and observed counts stated). Only 3 of 15 injected regressions at pilot density were
  detected; the other 12 were reported as insufficient evidence, none silently.
- **Insufficient-evidence records are emitted for every active agent below the floor** (54 to 65
  per run), not only suspicious ones, because a regression on 1 to 4 observations can show no sign
  at all; gating on a hint would have left one injected regression silent on seed 11 (measured
  with a 1.5 hint gate during development). The price is volume (about 60 extra advisory records
  per 200 agents); a consumer should filter on `evidence_status`.
- **What was tuned, on which seeds.** The floor of 8 was chosen after looking at request counts on
  pilot seeds 3 and 11 (ratio 2.0 is item 1's untouched default); seed 5 (pilot density and dense)
  was not used to choose anything. Ratio 2.5 was tried and rejected: it cuts sufficient-evidence
  false alarms to 0, 1 and 1 on seeds 3, 11 and 5 but loses a dense-profile regression on two
  runs (dense seeds 3 and 7: 2/3), which the dense acceptance forbids.
- **Sufficient-evidence false alarms remain (1, 2 and 4 per pilot seed).** Request durations are
  heavy tailed (a single agent's pooled window spans 3.9 s to 45 s with no regression), so a
  median of 8 to 15 samples crosses a 2x ratio by chance in roughly 3% of unaffected agents. A
  3x regression with 8 to 12 samples per window can also fall under 2x (power is limited): the
  rule does not claim otherwise. The 2.0 ratio is not a statistical test.
- **The two unlabelled flags (old rule) are explained.**
  - Seed 3, `a-000096` latency: the old rule compared daily medians of 3 to 4 requests; recent
    days 24.0 s and 35.9 s exceeded the limit of 22.5 s (2x the baseline median day of 11.25 s) on single heavy-tail
    requests. Pooled over the windows (12 baseline, 15 recent requests) the p50 ratio is 1.84, so
    the new rule does not flag it: noise, not a regression. The seed-3 flag under the new rule is a
    different agent (`a-000119`, deprecated, bimodal baseline 3.6 s to 27.9 s, p50 ratio 2.38):
    also chance.
  - Seed 11, `a-000195` unused: an **unlabelled true effect**. It is an active sub-agent
    (`delegates_to` target of the latency-regression parent `a-000009`) with 0 telemetry events on
    all 7 covered days (the source has events every day). The parent itself produced only about 5
    traces in the week and no delegation to the child is observed in the data. The manifest labels only solo agents as unused, so the
    flag is correct about the data and unlabelled by construction. It is kept.
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

## Round 2: held-out re-measurement (2026-11-15)

Reproduce with `uv run python tests/integration/recommendations/measure_detection.py` (about 4
minutes, in-memory, fixed seeds). The harness now labels every row `held_out`. Tuning seeds are
1, 2, 3, 7 and 11 (3, 7 and 11 were used in round 1, 1 and 2 were added and inspected in round
2); held-out seeds are 5, 13 and 17 and were not used to choose any threshold, ratio or floor.

No threshold was changed in round 2. The duplicate scores of every true pair on the five tuning
seeds range from 0.932 to 1.0 and no false pair appears on them, so the tuning seeds give no
evidence for a different `min_similarity` (raising it to 0.95 would lose true pairs at 0.932 and
0.948). The held-out false pairs score 0.974 (seed 5) and 0.920 twice (seed 13); the 0.974 pair is
above three true pairs on other seeds (0.932, 0.948, 0.954), so no score threshold separates them.
Tuning against the held-out seeds would defeat their purpose, so the criterion is amended to the
measured numbers instead (the lane A alternative).

### Dense profile, 3 duplicate pairs (40 agents, 4 domains, ~20 traces/agent-day)

| Seed | held out | cost_spike | latency | unused | duplicates (predicted / TP / labelled) | precision | recall |
|------|----------|-----------|---------|--------|----------------------------------------|-----------|--------|
| 1    | no  | 3/3 | 3/3 | 3/3 | 3 / 3 / 3 | 1.0  | 1.0 |
| 2    | no  | 3/3 | 3/3 | 3/3 | 3 / 3 / 3 | 1.0  | 1.0 |
| 3    | no  | 3/3 | 3/3 | 3/3 | 3 / 3 / 3 | 1.0  | 1.0 |
| 7    | no  | 3/3 | 3/3 | 3/3 | 3 / 3 / 3 | 1.0  | 1.0 |
| 11   | no  | 3/3 | 3/3 | 3/3 | 3 / 3 / 3 | 1.0  | 1.0 |
| 5    | yes | 3/3 | 3/3 | 3/3 | 4 / 3 / 3 | 0.75 | 1.0 |
| 13   | yes | 3/3 | 2/3 (1 silent miss) | 3/3 | 5 / 3 / 3 | 0.60 | 1.0 |
| 17   | yes | 3/3 | 3/3 | 3/3 | 3 / 3 / 3 | 1.0  | 1.0 |

Duplicate precision on the dense held-out seeds is 0.75, 0.60 and 1.0: the 0.80 target is NOT met
on two of three seeds, recall is 1.0 everywhere. Zero unlabelled false positives for the cost,
latency and unused rules on every dense seed. A new finding: dense held-out seed 13 has one
latency regression that is neither detected nor reported (a silent miss); the dense 3/3 claim of
round 1 holds on 7 of 8 dense seeds, not all. Both are OPEN quality items, not fixed here.

### Pilot density (200 agents, 8 domains, ~2 traces/agent-day)

| Seed | held out | cost_spike | latency detected | latency insufficient (injected) | latency silent misses | latency false alarms | unused | unused FP | duplicates P / R |
|------|----------|-----------|------------------|-------------------------------|----------------------|----------------------|--------|-----------|------------------|
| 3    | no  | 5/5 | 0/5 | 5 | 0 | 1 | 4/4 | 0 | 1.0 / 1.0 |
| 11   | no  | 5/5 | 3/5 | 2 | 0 | 2 | 4/4 | 1 | 1.0 / 1.0 |
| 5    | yes | 5/5 | 3/5 | 2 | 0 | 4 | 4/4 | 0 | 1.0 / 1.0 |
| 13   | yes | 5/5 | 2/5 | 3 | 0 | 1 | 4/4 | 0 | 1.0 / 1.0 |
| 17   | yes | 5/5 | 4/5 | 1 | 0 | 0 | 4/4 | 0 | 1.0 / 1.0 |

Held-out pilot latency: 3, 2 and 4 of 5 detected with 4, 1 and 0 false alarms, and no silent miss.
The assumption target (at least 3 of 5 and at most 1 false alarm per seed) is met on one of three
held-out seeds (17). The measured numbers replace the target: 9 of 15 detected on held-out seeds
(60 percent), 5 false alarms in total, 0 silent misses. The rule is unchanged from round 1
(version 2.0.0, ratio 2.0, floor 8 durations per window); lowering false alarms by raising the
ratio was already measured in round 1 to cost a dense-profile regression.

Next step if quality matters before hosting: evaluate mutual-best matching for duplicate pairs
(each agent in at most one candidate pair) and a multiple-comparison correction for the latency
ratio on FRESH seeds (not 5, 13, 17, which this section has now looked at).

## Round 2: production series source (archive)

`ArchiveSeriesSource` (`rules/archive_source.py`) reads the redacted archive window and shares
the bucketing, dedupe and coverage rules with `SandboxSeriesSource` (`SeriesAccumulator`). The
parity test serves the same generated sandbox documents as files and as archive blobs (in-memory
fake container) and requires equal series on seeds 3 and 11; the pipeline test requires the same
stored recommendation ids from `run_pipeline` and `run_pipeline_archive`. NOT measured: archive
listing sizing and RU cost on a real storage account and Cosmos (OPEN, G07 and G12), the hosted
role and a real-stack run (OPEN, PRP-58). The listing is bounded (`ArchiveReader.max_blobs`,
20000 by default); at that bound coverage is reported unknown and the run records
`archive_truncated`.
