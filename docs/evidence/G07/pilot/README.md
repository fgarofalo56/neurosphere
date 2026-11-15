# G07 pilot on the composed API, admission on (PRP-21 round 2 item 4)

Environment label: **compose, bounded feasibility** (emulators; client and server share one
Windows laptop). Not capacity evidence (G12). All data is synthetic. Targets are provisional PRD
planning targets, measured and never guaranteed.

## What ran

- Date 2026-11-15. The compose `api` container (profile `app`, one uvicorn worker, `NS_ENV=local`)
  with `NS_ADMISSION_ENABLED=true` and `NS_ADMISSION_POLICY_FILE=/etc/neurosphere/admission-quotas.json`
  (`infra/dev/admission-quotas.dev.json`), the Event Hubs emulator sink, and the dev ingest
  producer the container registers (`infra/dev/ingest-producers.dev.json`, one producer).
- Pilot profile (1k agents, 1k events/s target), 60 s, 20 locust users, batches of 25 events,
  scenarios `baseline_skew`, `hot_key`, `fan_out`, `multi_domain`, `otlp_traces`, `otlp_metrics`.
- Run 1 `pilot-2026-11-15-users20.json`: skew multiple 50 (profile default).
- Run 2 `pilot-2026-11-15-users20-skew200.json`: skew multiple 200 (noisy neighbor).
- `git_sha` in each file is the commit the working tree was based on; the pilot changes of this
  item were uncommitted when the runs started.

## Result: the provisional thresholds FAILED

| Run | Achieved events/s | Error ratio | Request p50 / p95 | Thresholds passed |
|---|---|---|---|---|
| skew 50 | 125 | 0% | 210 ms / 12,000 ms | error ratio only (1 of 3) |
| skew 200 | 120 | 0% | 220 ms / 13,000 ms | error ratio only (1 of 3) |

The composed API plus the emulator accepted about 120 events/s, roughly an eighth of the 1k target
and below round 1's 185 events/s at 20 users (different run, same laptop class, one worker).
Latency is bimodal: most batches return in 200 to 1,000 ms and a tail sits at 8 to 13 s, which is
what the p95 shows. This is a ceiling of this setup (one worker, one emulator, shared host), not a
statement about the product. No threshold was tuned. G07 stays OPEN.

## Noisy-neighbor behaviour under the skew scenario

The skew shape held: the hottest domain (`dom-0000`) carried 37x the median domain in run 1 and
84x in run 2, all of it accepted. Nothing was rejected or throttled in either run: no 429 from the
ingest edge's per-producer limiter (about 5 requests/s is below its 20 rps) and no 5xx.

**Per-domain admission was not exercised by this run, and its admitted/throttled counts per
domain are OPEN against the composed API.** Admission is charged by `require(...)` on
authenticated routes; the ingest edge authenticates producers separately and keeps its own
limiter, so no request here was charged to a domain bucket (the evidence says so under
`environment_notes.admission_charges_ingest`). Driving authenticated read traffic at the composed
API needs a real Entra token and the real-stack recipe, which is a live gate not run here.
What is measured for admission is in process, with a fake clock:
`services/api/tests/admission_api/test_admission_dependency.py` (a noisy domain gets 429 with
`Retry-After` while another domain still succeeds; denied requests are not charged) and
`packages/core/tests/admission/test_noisy_neighbor.py` (a domain at 20x the median is throttled,
the others see zero rejections).

## Still OPEN

- Per-domain admitted/throttled counts on the composed API (needs Entra token traffic).
- Pilot at the 1k events/s target has not been met on compose.
- Enterprise and stress profiles, failover, geo-replication, production restore, AI Search
  rebuild and invoiced-cost evidence (#108, operator only, PRP-64).
- The 2 s p95 threshold is a provisional placeholder; the owner has not set an ingest latency target.

## Reproduce

```
docker compose up -d --wait
NS_ENTRA_TENANT_ID=<any-guid> NS_ENTRA_CLIENT_ID=<any-guid> docker compose --profile app up -d --wait --build api
uv run python tests/load/profiles/run_profile.py pilot --compose-api --duration 60 --users 20 --suffix=-users20
uv run python tests/load/profiles/run_profile.py pilot --compose-api --duration 60 --users 20 --skew-multiple 200 --suffix=-users20-skew200
docker compose --profile app down
```
