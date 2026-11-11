# Evaluation loop on the compose emulators (2026-11-11)

Scope: **emulator, bounded feasibility, not a live claim.** Cosmos, Event Hubs and Azurite from
`docker compose` (127.0.0.1), the API and the `ingestion` + `evaluation` worker roles in-process,
fixture judge, synthetic sandbox data only. Nothing here is a Government, hosted or FedRAMP claim,
and the live judge gate (G16) stays OPEN. Test: `tests/integration/real_stack/test_evaluation_loop.py`
(`pytest.mark.integration`, never runs in CI).

Test-only settings versus compose: `NS_WORKER_EVAL_CALIBRATION_SAMPLE_CAP=30`,
`NS_WORKER_EVAL_RATE=1.0` (compose keeps the 0.1 default), periodic intervals set long so each
freshly built role runs each stage exactly once (tick 1, tick 2).

| Measure | Value |
|---|---|
| Sandbox spans pushed through the ingest edge | 600 (classifications: {'None': 62, 'cui': 79, 'internal': 292, 'public': 99, 'restricted': 68}) |
| Archive blobs written | 600 |
| Ingest to archive | 49.9 s |
| Tick 1 (online + offline + sample) | 9.3 s |
| `evaluation_dispute` items opened | 30 |
| Calibration-sample reads OK / payload withheld | 30 / 0 (classes withheld: {}) |
| Items decided (approved / rejected) | 24 (8 / 16) |
| Tick 2 (labels + calibration + pilot results) | 6.1 s |
| Pilot grounded rate | 0.719 (n=32, method wilson_score) |
| Interval | [0.546, 0.844] at level 0.95 |
| Target label | pilot-set target: at least 90% |
| Trend calibration states (all dimensions) | ['calibrated'] |
| `missing_labels` (judged / labelled / missing) | {'judged': 32, 'labelled': 24, 'missing': 8} |
| Online coverage (sampled / population) | 32 / [10, 16, 16, 8] over 4 strata |
| Cohen's kappa | not exposed by `/quality`; held in the stored calibration report only |
| Out-of-scope caller | `/quality` 403, `/calibration-samples` 403 |

Reviewer: a `domain_steward` on the pilot domain (holds `catalog.curate`; not an admin, not a maker).
Role states at tick end: tick 1 {'evaluation': 'running:None'}; tick 2 {'evaluation': 'running:None'}.

## Gaps found

- Not a product defect: the 8 restricted pilot items are never judged (fail-closed guard), so none was sampled for review and the payload-withheld branch of the calibration-samples route is covered only by the API unit tests, not by this loop.

## Emulator versus live (G12)

The emulators accept any token and do no RU accounting; the HITL, evaluation and policy stores are
real Cosmos containers on the emulator, so query shapes and partitioning are exercised, but latency
and throttling are not representative. The judge is the recorded-fixture judge: the pilot rate shows
the pipeline works end to end, not that a model meets the 90% pilot-set target.
