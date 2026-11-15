# Load profiles (PRP-21 item 1, gate G07)

Locust suites for the **pilot**, **enterprise** and **stress** profiles against the ingest edge
(`POST /v1/ingest/events`, `/v1/ingest/otlp/traces`, `/v1/ingest/otlp/metrics`). Synthetic
data only. Every number is a **provisional planning target** from PRD section 3, measured and
never guaranteed.

| Profile | Agents | Sustained events/s | Burst | Other | Runs |
|---|---|---|---|---|---|
| pilot | 1,000 | 1,000 | - | - | compose (emulators), CI-capable, no paid calls |
| enterprise | 100,000 | 10,000 | - | - | **operator only**, sized environment you name - OPEN |
| stress | 1,000,000 entities | 50,000 | 150,000 | 10M relationships; "subject to partition/cost validation" | **operator only** - OPEN |

A green pilot is never evidence for enterprise or stress. The 1M entities / 10M relationships
figures are recorded in the profile but not driven by this ingest suite.

## Layout and the locust isolation rule

Importing locust gevent-monkeypatches the process, which would break the shared asyncio pytest
session. Only `locustfile.py` imports it, and no test imports that file. Everything else
(`definitions.py`, `scenarios.py`, `evidence.py`, `runner.py`, `compose_pilot.py`) is plain
Python. Locust is pinned in `requirements.txt` (not in `pyproject.toml`/`uv.lock`) and runs as an
isolated subprocess:

```
uv run --isolated --no-project --with-requirements tests/load/profiles/requirements.txt \
    locust -f tests/load/profiles/locustfile.py --headless ...
```

**Licence:** locust 2.47.0 is MIT (ADR-0002 row; k6 was rejected: AGPL-3.0).

## Scenarios

- `baseline_skew`: domains drawn with one hot domain at `skew_multiple` times the median domain
  weight (default 50x, configurable, `--skew-multiple`). This is the noisy-neighbor shape.
- `hot_key`: one producer, one source (one Event Hubs partition key `customer|source`), one agent.
- `fan_out`: a single batch spanning `fan_out_width` distinct domains and agents.
- `multi_domain`: a permission-heavy producer registered for 8 sources; each event is checked
  against the larger registration. (Read-side multi-domain users are not driven here.)
- `otlp_traces`: OTLP/JSON spans. The edge maps no domain from OTLP, so these events are reported
  as `unattributed`.
- `otlp_metrics`: OTLP/JSON delta-sum token metrics (`gen_ai.usage.input_tokens`), one event per
  data point, also `unattributed`.

Latency is per POST (one batch of 25 events). Achieved rate is accepted events divided by wall
time. Thresholds (all provisional): achieved events/s >= the profile rate, error ratio <= 1%,
request p95 <= 2000 ms (the PRD has no ingest latency figure; this reuses the dashboard target as
a placeholder). Pass/fail is recorded as data; nothing is tuned to the result.

## Run

Pilot against the composed API (PRP-21 round 2): the compose `api` container (profile `app`) now
registers a dev ingest producer and runs with per-domain admission on, so `--compose-api` targets
it (results in `docs/evidence/G07/pilot/`; ingest is not charged by admission):

```
docker compose up -d --wait
NS_ENTRA_TENANT_ID=<any-guid> NS_ENTRA_CLIENT_ID=<any-guid> docker compose --profile app up -d --wait --build api
uv run python tests/load/profiles/run_profile.py pilot --compose-api --duration 60 --users 20
```

Pilot against compose emulators only (starts a **local** uvicorn API with the ingest edge; round 1,
`docs/evidence/G07/load/`):

```
docker compose up -d --wait
uv run python tests/load/profiles/run_profile.py pilot --duration 60 --evidence-dir docs/evidence/G07/load
docker compose --profile app down
```

Options: `--users`, `--skew-multiple`, `--suffix`. Producer secrets are generated per run; only
sha256 hashes reach disk. Test (integration, 20 s, writes to a tmp dir):
`uv run pytest -m integration tests/load/profiles/test_pilot_compose.py`.

Enterprise / stress: **never started by CI or a test.** They refuse to start without `--host` and
`--environment-label` (no default to any cloud or localhost). The operator registers producers on
the target edge and passes their credentials in memory:

```
NS_LOAD_CREDENTIALS_JSON='[{"producer_id":"...","secret":"...","customer_id":"...","cloud":"commercial","sources":["..."]}]' \
uv run python tests/load/profiles/run_profile.py enterprise \
    --host https://<target> --environment-label "<sized environment name>" --duration 600
```

`--dry-run` prints the resolved command without starting anything.

## Evidence

`docs/evidence/G07/load/<profile>-<date>[suffix].json`: measured rate, p50/p95/p99, error counts
by type, duration, users, thresholds with pass/fail, environment label, method, date, git SHA,
per-scenario and per-domain tallies and emulator limits (G12). The pilot environment label is
"compose (emulators), bounded feasibility only - not capacity evidence (G12)".

## Status

- Pilot: run on compose; results and the observed ceiling are in the evidence files.
- Enterprise, stress: **OPEN** until an operator runs them at a sized environment with partition
  and cost approval. G07 stays OPEN.
