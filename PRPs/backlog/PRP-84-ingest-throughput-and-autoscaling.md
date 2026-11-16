---
name: PRP-84-ingest-throughput-and-autoscaling
status: backlog
priority: P1
order: 75
review: required
created: 2026-11-16
model: sonnet
orchestrator_model: sonnet
implementer_model: sonnet
phase: 7
ns: NS-01, NS-05
depends_on: [PRP-58-hosted-data-path-and-environment-hardening, PRP-67-hosted-environment-hardening, PRP-79-agent-sdk-and-telemetry-onboarding]
wave: W23
branch: prp-84-ingest-throughput
allow_parallel: true
issues: []
---

# PRP-84: Ingest throughput, back-pressure, autoscaling and end-to-end latency measurement

## Goal
Close the engineering gap between the measured ingest edge and the original PRD's performance bar, and make the remaining distance measurable. Ships: a multi-process ingest edge with bounded in-flight work and an explicit 429 when overloaded; publisher tuning; opt-in autoscaling in the Helm chart (HPA for the API, KEDA on Event Hubs lag for the ingestion worker pool, disruption budgets); an end-to-end event-to-graph latency probe (post at the edge, observe in the catalog and on the map WebSocket), not just edge request latency; load profiles for 1k and 10k events per second that record replicas, partitions and lag beside the latency numbers; and a local compose re-measurement against the 2026-11-15 baseline. It is for the SRE and operator who need to know what the platform sustains and how it scales, and for PRP-66, which runs the real-Azure profiles. All targets below are things to measure and report, never promises; a number that was not measured on real Azure is reported OPEN.

Out of scope: running the 1k and 10k profiles on real Azure and the sized environment for them (operator-gated, PRP-66; the hosted data path they need is PRP-58); App Service autoscale rules in `infra/demo` (item 7, `[serial-after: PRP-82]`); OTLP protobuf and gzip, quarantine read API and the Entra producer authenticator (PRP-79); per-domain read-side admission (PRP-21, shipped, unchanged); map rendering performance (PRP-77); catalog and recommender latency profiles (PRP-72); the 50k and 150k stress profile (stays OPEN).

## Why
- Original PRD 5a acceptance criteria: "End-to-end ingestion latency p95 < 5s under 10k events/sec load" and "Back-pressure handling and autoscaling consumers"; section 3 metric "Telemetry event-to-graph-update latency (p95) < 5s" (`git show 9fbf5f4c:docs/PRD.md`). v1.2 replaced the bar with planning targets: "pilot 1k agents/1k events per second; enterprise 100k agents/10k sustained events per second ... Planning targets, to be measured rather than guaranteed" (`docs/PRD.md:50-51`). This PRP restores the engineering work and keeps v1.2's honesty about targets.
- Measured: about 120-125 events/s with request p95 12-13 s on one uvicorn worker against the Event Hubs emulator on a laptop; both profile runs failed the 1k pilot bar and the tail is bimodal (`docs/evidence/G07/pilot/README.md`). Roughly an 8x gap to the pilot and about 80x to the enterprise target, on emulators. The ceiling is one process and one emulator, not yet a statement about the product.
- The edge is single-process by default: `services/api/Dockerfile:52` runs `uvicorn --factory ... neurosphere_api.main:create` with no worker count, and the publisher sends one batch per partition key sequentially (`services/api/neurosphere_api/ingest/publisher.py:30-45`).
- No back-pressure on ingest beyond the per-producer in-process token bucket (`services/api/neurosphere_api/ingest/settings.py:30-31`, 20 rps, burst 40, per process); read-side admission control does not cover ingest (gap analysis 5a "Back-pressure and autoscaling consumers"; `packages/core/neurosphere_core/admission/`).
- No autoscaling anywhere under `infra/`: Helm replicas are fixed (`infra/helm/values.yaml:183,194,209`), there is no HPA, KEDA or disruption budget template (`infra/helm/templates/` has only deployment, ingress, networkpolicy, secretproviderclass, service, serviceaccount), and the worker `roles` default is empty (idle, `values.yaml:200`).
- Event-to-graph latency is only measured for a segment: aggregate handler to WebSocket receipt, p95 about 2.0 s over 30 events (`tests/load/map_freshness/test_freshness_p95.py` and its docstring: Event Hubs transport and the ingest edge are excluded; `docs/evidence/G07/map/p95.json`).

## Acceptance criteria
- [ ] Given `WEB_CONCURRENCY=N` (uvicorn's own variable, no Dockerfile change), When the API starts in a compose run, Then N edge processes serve ingest and `/readyz` is healthy; the runbook states which state is per process (token bucket, producer snapshot, realtime poller) and the effective limits that follow.
- [ ] Given more concurrent ingest requests than `NS_INGEST_MAX_IN_FLIGHT`, Then excess requests get 429 with `Retry-After` and reason `ingest_overloaded` immediately, nothing is published for them, memory stays bounded, and an `overloaded` counter is exported beside the existing ingest counters; Given the limit is unset, Then behaviour is as today (existing `services/api/tests/ingest` passes unchanged).
- [ ] Given publish groups for several partition keys, Then they are sent concurrently up to `NS_INGEST_PUBLISH_CONCURRENCY`, per-key order is preserved, and a failure in one group fails the request with the existing transient error without losing accepted counts.
- [ ] Given `autoscaling.enabled=true`, When `helm template` renders with the CI values, Then it emits an HPA for the API (CPU target, min and max), a KEDA `ScaledObject` for the ingestion worker pool (Event Hubs trigger with blob checkpoint settings, min, max, lag threshold), and PodDisruptionBudgets; Given `autoscaling.enabled=false` (default), Then the render is byte-identical to today except documented additions.
- [ ] Given `workers.pools`, Then ingestion, projections and aggregates scale as one pool while roles that must run once (timers, lifecycle, evaluation, actions) stay at one replica; the chart fails with a clear message if a single-instance role is placed in a scalable pool (the role safety list is verified from worker code in item 3, not assumed).
- [ ] Given the e2e probe, When it runs against the compose stack with background load, Then it reports p50, p95, p99 and max of event-to-graph latency for both observation points (new agent visible via the catalog; metric delta on the map WebSocket), the count of probes that never arrived within the timeout, and the measurement definition; the probe never fails a run for being slow, it records `meets_target` as data (as `map_freshness` does).
- [ ] Given the 1k and 10k profiles, Then the runner emits evidence JSON holding: environment label, git sha, profile, duration, achieved events/s, accepted/429/error counts, edge request p50/p95/p99, e2e latency, edge replicas and workers per pool over time, partition count, consumer lag samples, and the measured-versus-target table with the target quoted from the original PRD and v1.2; no threshold is tuned to a result.
- [ ] Given a local compose re-run of the pilot profile after items 1 and 2, Then the result is committed under `docs/evidence/G07/ingest/` with the 2026-11-15 baseline beside it, whatever it shows, including a failure; G07 stays OPEN unless a real-Azure run meets the bar.
- [ ] `docs/runbooks/ingest-scaling.md` lists the knobs (worker count, in-flight limit, publish concurrency, partition count, pool sizes, KEDA threshold), the exact operator commands for the real-Azure 1k and 10k runs, and states that they were not run.
- PRP exit: touched suites, `tests/unit/infra` Helm render, ruff, pyright, `validate_planning.py` pass; PR open with CI green; the real-Azure profiles reported OPEN (PRP-66).

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| 1 | How the edge goes multi-process | Change the Dockerfile CMD; `WEB_CONCURRENCY` | `WEB_CONCURRENCY` (uvicorn reads it as the `--workers` default). No Dockerfile edit, so PRP-79's Dockerfile ownership in W22 is not touched. |
| 2 | Per-producer rate limit across processes | Shared limiter in Cosmos; per-process buckets documented | ASSUMPTION: per-process buckets, documented as effective rate = per-process rate times processes (and times replicas). A shared limiter would add a store hop on the hottest path; revisit only if measurement shows abuse. |
| 3 | Back-pressure signal | Unbounded queue; in-flight cap with 429 | In-flight cap, 429 plus `Retry-After`; never an unbounded in-process queue. |
| 4 | Worker scaling signal | CPU; Event Hubs lag | KEDA on Event Hubs lag for the ingestion pool (CPU for the API). ASSUMPTION: KEDA is installed by the operator; the chart renders the `ScaledObject` only when enabled and does not install KEDA. The scaler's checkpoint settings must match what `ingestion/consumer.py` writes (blob checkpoint store); verify against KEDA documentation at execution (UNVERIFIED here). |
| 5 | Scaling bound by partitions | Ignore; document | Consumers per consumer group cannot exceed the partition count (demo Bicep default `partitionCount = 4`, `infra/demo/modules/messaging-data.bicep:21`; compose hub 4 partitions, `infra/compose/eventhubs.config.json`). The chart caps `maxReplicas` of the ingestion pool at the configured partition count and the runbook says how to raise partitions (a hub recreate, operator-gated). |
| 6 | What "event-to-graph" means | Edge response time; visible in catalog or map | Two observation points: catalog entity visible for a probe-only new agent (projection path) and metric delta on the WebSocket (aggregate path). Both reported; neither is called "the" number until PRP-66 chooses. |
| 7 | Targets | Gate on them; report them | Report. Quote 5 s e2e p95 at 10k events/s (original PRD) and the v1.2 planning targets; mark `meets_target` as data. |
| 8 | App Service autoscale | Edit `infra/demo` here | `[serial-after: PRP-82]` item 7, optional; PRP-82 holds `infra/demo/**` in W21. |

## Context manifest

### Files to read first
- `docs/evidence/G07/pilot/README.md` - baseline numbers, run recipe, the admission caveat.
- `services/api/neurosphere_api/ingest/{router,service,publisher,settings,reasons,limits}.py` - edge path, token bucket, publish grouping, reason families.
- `services/workers/neurosphere_workers/ingestion/consumer.py` and `settings.py` - Event Hubs consumer with blob checkpoints, `max_batch_size` (`:26`).
- `services/workers/neurosphere_workers/runtime/settings.py` - roles, `NS_WORKER_ROLES`; read which roles are safe at replicas above one.
- `tests/load/profiles/{definitions,runner,run_profile,locustfile,evidence,compose_pilot}.py` and `README.md` - profiles, locust isolation rule, evidence format.
- `tests/load/map_freshness/test_freshness_p95.py` - measurement definition style, WebSocket subscriber harness.
- `infra/helm/templates/deployment.yaml`, `values.yaml` (`api`, `workers`, `frontend`, `workers.roles`), `infra/helm/ci/values-ci.yaml`, `tests/unit/infra/test_helm_render.py`.
- `packages/core/neurosphere_core/admission/` and `docs/runbooks/ingest.md` - what admission covers and what it does not.
- `docs/ARCHITECTURE.md` ingestion section and `docs/evidence/G07/` layout.

### Interfaces consumed
- Shipped: `IngestService.authorize`, `Publisher` protocol, `HubMessage.partition_key()`, ingest counters and reason families (PRP-46), per-producer limiter, producer store (PRP-41), worker roles and checkpoint store, `tests/load/profiles` (PRP-21), realtime WebSocket (`/api/v1/realtime/ws`) and `AggregateDeltaSource`.
- PRP-58: hosted parameters for worker roles and the store switch, Helm role switches (names it added to `values.yaml` and the deployment template); PRP-67: Helm probe values and `deployment.yaml` edits (read both before editing the same template).
- PRP-79 (W22, merged first): `ingest/encoding.py`, `ingest/limits.py` and the gzip-aware `_read` in `ingest/router.py`. This PRP edits `router.py` only to call the back-pressure check after the body is read and to map `ingest_overloaded` to 429; it does not edit `_read`, `encoding.py`, `limits.py` or the Dockerfiles (PRP-79 Tier 1) and rebases on PRP-79's `router.py`.
- PRP-63/PRP-82 for the deployed environment the operator runs against (not edited here).

### Interfaces provided
- Settings `NS_INGEST_MAX_IN_FLIGHT`, `NS_INGEST_PUBLISH_CONCURRENCY` (both default unset/1, behaviour unchanged); response reason `ingest_overloaded` (HTTP 429, `Retry-After`); counter `ingest_overloaded_total`.
- Helm values `autoscaling.enabled` (default false), `autoscaling.api.{minReplicas,maxReplicas,cpuUtilization}`, `autoscaling.workers.ingestion.{minReplicas,maxReplicas,lagThreshold}`, `workers.pools[]` {name, roles, replicas}, `podDisruptionBudget.enabled`; templates `hpa.yaml`, `keda-scaledobject.yaml`, `pdb.yaml`.
- `tests/load/ingest_e2e/` (`probe.py`, `harness.py`, `profiles.py`, `run_ingest_e2e.py`, `evidence.py`): CLI `uv run python tests/load/ingest_e2e/run_ingest_e2e.py {pilot-1k|enterprise-10k} --host ...`; evidence schema `ingest-e2e/v1`.
- `docs/runbooks/ingest-scaling.md`; evidence directory `docs/evidence/G07/ingest/`.

### Patterns to match
- Frozen settings with `NS_INGEST_` prefix and `extra="forbid"`: `ingest/settings.py:25-26`.
- Measured-not-asserted harness with JSON evidence and recorded exclusions: `tests/load/map_freshness/test_freshness_p95.py` (docstring), `tests/load/profiles/evidence.py`.
- Locust as isolated subprocess, no import in the pytest session: `tests/load/profiles/README.md` "Layout and the locust isolation rule".
- Helm conditional templates and CI value fixtures: `infra/helm/templates/deployment.yaml:6-20`, `tests/unit/infra/test_helm_render.py`.
- Reason-code families with counters and no message text: `ingest/reasons.py`.

### Gotchas
- Processes multiply per-process state: token buckets, the producer-store refresher task, the realtime aggregate poller, startup hooks (stored settings, migrations). Test that startup is idempotent with `WEB_CONCURRENCY=2` and that readiness does not flap. Do not run multi-process with in-memory backends (`NS_ENV=local` without Cosmos): documents are per process.
- Helm `api.resources.limits.cpu` is `"1"` (`values.yaml:189`): more processes need more CPU; document and size defaults (do not change values for non-autoscaling installs without a golden update).
- Worker roles in one pod: `workers.roles` is one list per Deployment. Splitting pools means more than one worker Deployment; keep the default single Deployment byte-identical when `workers.pools` is empty.
- The emulator is the limit locally: Event Hubs vNext emulator throughput and the shared Windows host dominated the 2026-11-15 run; do not read local numbers as product capacity. Use `127.0.0.1`, not `localhost` (emulator IPv6 trap; memory). Random WinError 10055 socket failures on Windows during the full suite are TIME_WAIT churn, not a leak (memory).
- Probes must use unique agent ids per probe and a dedicated probe producer so they do not alias real agents; remove nothing from the catalog afterwards (drafts are inert) and say so in the evidence.
- Live runs need `NS_LIVE_APPROVED=1`, spend approval and a named sized environment (`requires_explicit_target`, `_check_host` in `definitions.py:163`); the load profile refuses non-loopback hosts without it.
- Same-named test directories shadow each other: new tests live in `services/api/tests/ingest_throughput` and `tests/unit/ingest_scaling`.
Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - services/api/neurosphere_api/ingest/publisher.py
  - services/api/neurosphere_api/ingest/service.py
  - services/api/neurosphere_api/ingest/settings.py
  - services/api/neurosphere_api/ingest/reasons.py
  - services/api/neurosphere_api/ingest/router.py
  - services/api/tests/ingest_throughput/**
  - tests/load/ingest_e2e/**
  - tests/unit/ingest_scaling/**
  - infra/helm/templates/hpa.yaml
  - infra/helm/templates/keda-scaledobject.yaml
  - infra/helm/templates/pdb.yaml
  - infra/helm/ci/values-autoscale.yaml
  - docs/runbooks/ingest-scaling.md
  - docs/evidence/G07/ingest/**
tier1:
  - infra/helm/**
tier2_appends:
  - services/api/neurosphere_api/runtime/status.py
  - mkdocs.yml
must_not_touch:
  - services/api/Dockerfile
  - docker-compose.yml
  - packages/contracts/**
  - services/api/neurosphere_api/ingest/auth.py
  - services/api/neurosphere_api/ingest/bootstrap.py
  - services/api/neurosphere_api/ingest/producer_store.py
  - services/api/neurosphere_api/ingest/otlp_mapping.py
  - services/api/neurosphere_api/ingest/cloudevents.py
  - services/workers/neurosphere_workers/ingestion/pipeline.py
  - tests/load/profiles/definitions.py
  - infra/demo/**
  - infra/appservice/**
  - infra/bicep/modules/**
```

## Implementation blueprint

Parallelization: items 1, 3 and 4 [P] (edge code, Helm and the probe share no file). Item 2 after 1 (same ingest files for the settings). Item 5 after 4. Item 6 after 1, 2 and 5 (needs the stack and the runner). Item 7 after 3. Item 8 last. Item 7b is `[serial-after: PRP-82]`.

### Item 1 - Back-pressure and publisher tuning  [P]
- Deliverable: `NS_INGEST_MAX_IN_FLIGHT` (semaphore-style bound at the service entry, non-blocking acquire, 429 `ingest_overloaded` with `Retry-After`, counter), `NS_INGEST_PUBLISH_CONCURRENCY` (gather over partition-key groups with a bound; per-key batches stay ordered), reason code added to the reason family, router mapping, status of the setting in `/readyz` composition detail left unchanged.
- Owned files: `services/api/neurosphere_api/ingest/{publisher,service,settings,reasons,router}.py`, `services/api/tests/ingest_throughput/test_backpressure.py`, `test_publish_concurrency.py`.
- Must NOT touch: `auth.py`, `bootstrap.py`, `producer_store.py`, `otlp_mapping.py`.
- Depends on: PRP-58, PRP-67 merged.
- Acceptance criteria: the second and third criteria; existing `services/api/tests/ingest` unchanged; 429 body is the typed error with no payload echo.
- Tests: `services/api/tests/ingest_throughput`, `services/api/tests/ingest`.
- Pattern references: `ingest/limits.py:51-70`, `ingest/reasons.py`, `ingest/publisher.py:30-45`.

### Item 2 - Multi-process edge, proven and documented
- Deliverable: a compose override `tests/load/ingest_e2e/compose.multiworker.yml` (sets `WEB_CONCURRENCY` for the `api` service only; the root compose file is not edited), a startup-idempotence test with two app instances over shared in-memory stores for the cache-per-process state, and the per-process state table in the runbook draft.
- Owned files: `tests/load/ingest_e2e/compose.multiworker.yml`, `services/api/tests/ingest_throughput/test_multi_instance.py`.
- Must NOT touch: `docker-compose.yml`, `services/api/Dockerfile`.
- Depends on: item 1.
- Acceptance criteria: first criterion; two instances accept events concurrently without duplicate checkpoints or crashed refreshers.
- Tests: `services/api/tests/ingest_throughput/test_multi_instance.py`.
- Pattern references: `services/api/tests/ingest/test_bootstrap.py`, `tests/integration/ingestion/support.py`.

### Item 3 - Helm autoscaling and worker pools  [P]
- Deliverable: `hpa.yaml`, `keda-scaledobject.yaml`, `pdb.yaml` guarded by `autoscaling.enabled` and `podDisruptionBudget.enabled`; `workers.pools` support in the deployment template (default empty keeps one Deployment byte-identical); role safety list taken from worker code (which roles tolerate more than one replica) with a `fail` message for a single-instance role in a scalable pool; `values.yaml` additions and `infra/helm/ci/values-autoscale.yaml`; `maxReplicas` for the ingestion pool capped by a `partitions` value.
- Owned files: `infra/helm/templates/{hpa,keda-scaledobject,pdb}.yaml`, `infra/helm/templates/deployment.yaml` (pool loop only), `infra/helm/values.yaml`, `infra/helm/ci/values-autoscale.yaml`, `tests/unit/ingest_scaling/test_helm_autoscaling.py`.
- Must NOT touch: `networkpolicy.yaml` semantics, probe values PRP-67 added, `infra/helm/values-government.yaml` beyond mirrored keys.
- Depends on: PRP-58 and PRP-67 merged (same template).
- Acceptance criteria: fourth and fifth criteria; `tests/unit/infra/test_helm_render.py` still passes unchanged; where `helm` is missing the new tests skip by the existing rule (CI has helm).
- Tests: `tests/unit/ingest_scaling`, `tests/unit/infra`.
- Pattern references: `infra/helm/templates/deployment.yaml:6-20,184-200`, `tests/unit/infra/test_helm_render.py`.

### Item 4 - End-to-end event-to-graph probe  [P]
- Deliverable: `tests/load/ingest_e2e/probe.py` posting a marker event for a unique probe agent through a dedicated probe producer, then polling the catalog entity route and a WebSocket subscriber for the metric delta until a timeout; `harness.py` running probes at a fixed low rate beside background load (locust run as the existing isolated subprocess); `evidence.py` writing the `ingest-e2e/v1` JSON with definition, exclusions (browser render excluded) and `meets_target` as data.
- Owned files: `tests/load/ingest_e2e/{probe,harness,evidence}.py`, `tests/load/ingest_e2e/__init__.py`, `tests/load/ingest_e2e/test_probe_logic.py`, `tests/load/ingest_e2e/test_evidence_format.py`.
- Must NOT touch: `tests/load/profiles/**`, `tests/load/map_freshness/**` (imitate, import nothing that monkeypatches).
- Depends on: none.
- Acceptance criteria: sixth criterion; the probe logic is tested against fakes with controlled delays (percentiles computed exactly); no gevent import in the pytest session.
- Tests: `tests/load/ingest_e2e` (offline tests only).
- Pattern references: `tests/load/map_freshness/test_freshness_p95.py`, `tests/load/profiles/evidence.py`.

### Item 5 - 1k and 10k profile runner
- Deliverable: `profiles.py` wrapping `PILOT` and `ENTERPRISE` from `tests/load/profiles/definitions.py` without editing it (adds ramp stages, probe rate, sampling of replica counts, partition count and consumer lag from operator-supplied commands or the compose emulator), `run_ingest_e2e.py` CLI with `--dry-run`, refusal rules identical to `run_profile.py` (non-loopback needs `NS_LIVE_APPROVED=1` and `--environment-label`), measured-versus-target table in the evidence.
- Owned files: `tests/load/ingest_e2e/{profiles,run_ingest_e2e}.py`, `tests/load/ingest_e2e/test_profiles_wrapper.py`, `tests/load/ingest_e2e/test_refusals.py`.
- Must NOT touch: `tests/load/profiles/definitions.py`.
- Depends on: item 4.
- Acceptance criteria: seventh criterion; dry-run prints the plan and exits 0 without a network call; a real host without the approval variable exits 2.
- Tests: `tests/load/ingest_e2e`.
- Pattern references: `tests/load/profiles/run_profile.py:38-60`, `tests/load/profiles/test_profiles_definition.py`.

### Item 6 - Local compose re-measurement
- Deliverable: run the pilot profile on the compose stack with `WEB_CONCURRENCY` 1, 2 and 4 (via the override) and the e2e probe, commit the evidence JSON and a README with the baseline beside it and an honest reading (emulator and shared-host limits; failed bars stated as failed).
- Owned files: `docs/evidence/G07/ingest/**`.
- Must NOT touch: other `docs/evidence/**`.
- Depends on: items 1, 2, 4 and 5; Docker available. If Docker is not available, write the README saying the run did not happen and leave the directory without numbers.
- Acceptance criteria: eighth criterion; no number in the README that is not in a committed JSON file.
- Tests: `tests/load/ingest_e2e/test_evidence_format.py` validates the committed JSON against the schema.
- Pattern references: `docs/evidence/G07/pilot/README.md`.

### Item 7 - Scaling runbook and operator handoff
- Deliverable: `docs/runbooks/ingest-scaling.md` (knobs, effective-rate arithmetic, partitions bound, KEDA install prerequisite, the exact commands for the real-Azure 1k and 10k runs with `NS_LIVE_APPROVED=1`, named environment, spend row, VPN and evidence directory, what to hand to PRP-66). 7b `[serial-after: PRP-82]`, optional: App Service autoscale rules in `infra/demo/main.bicep` and `infra/appservice/main.bicep` behind a parameter that defaults off; skip and report if PRP-82 has not merged.
- Owned files: `docs/runbooks/ingest-scaling.md`, `tests/unit/ingest_scaling/test_runbook_commands.py`; 7b: Bicep lines named above only.
- Depends on: items 3 and 5; 7b on PRP-82.
- Acceptance criteria: ninth criterion; every command in the runbook parses against the real CLIs offline; no real id, host or subscription appears.
- Tests: `tests/unit/ingest_scaling/test_runbook_commands.py`, `tests/docs`.
- Pattern references: `tests/unit/hosted_demo/test_runbook_commands.py`.

### Item 8 - Integration and close-out
- Deliverable: `runtime/status.py` and `mkdocs.yml` Tier-2 lines if any component or nav entry is added; regenerate Tier-3 if the ingest 429 changed the OpenAPI document (`services/api/openapi.json`, `docs/reference/**`); changelog fragment `changelog.d/PRP-84-ingest-throughput-and-autoscaling.md`; completion note with the measured numbers, the OPEN real-Azure gates and the product check (can an operator turn on autoscaling and read a real e2e latency without editing files?).
- Owned files: Tier-2 lines, Tier-3 files per reference section 2, this PRP file, the changelog fragment.
- Depends on: items 1-7.
- Acceptance criteria: validation gates pass; CI green.

## Validation gates
```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q services/api/tests/ingest services/api/tests/ingest_throughput services/api/tests/runtime_api tests/load/ingest_e2e tests/load/profiles tests/unit/ingest_scaling tests/unit/infra tests/integration/ingestion services/api/tests/test_openapi_drift.py tests/docs
python scripts/prp_status.py --check
python scripts/validate_planning.py
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```
Local, not CI (Docker, emulators): `docker compose --profile app up -d --wait --build`, then `uv run python tests/load/ingest_e2e/run_ingest_e2e.py pilot-1k --dry-run` and the real run; record the output.

## Migration and rollback
No data migration. New settings default to today's behaviour; autoscaling templates render only with `autoscaling.enabled=true`; `workers.pools` empty keeps the single worker Deployment. Roll back by unsetting `WEB_CONCURRENCY`, `NS_INGEST_MAX_IN_FLIGHT` and `autoscaling.enabled`, or reverting the PR. Probe agents left in a catalog are inert `draft` entities (documented).

## Live and open gates
OPEN and operator-gated (`NS_LIVE_APPROVED=1`, approved spend, a named sized environment on real Event Hubs and Cosmos, VPN where the data plane is private), handed to PRP-66 with the commands from item 7: pilot 1k events/s profile on real Azure; enterprise 10k events/s profile; the e2e latency number on real Azure; KEDA behaviour on a real cluster; Event Hubs partition count change. The enterprise and stress bars (10k, 50k sustained, 150k burst) stay OPEN until those runs; G07 stays OPEN. The local compose numbers are reported as emulator and shared-host results, not capacity.

## NOT building
Real-Azure runs or a sized environment; OTLP protobuf and gzip, quarantine read API, Entra producer auth (PRP-79); a shared cross-process rate limiter; admission control on the ingest path via the domain quota policy; Kafka, ClickHouse or any non-Event-Hubs broker (PRP-85 and later own portability); a promise that 10k events/s at p95 under 5 s is met; the stress profile; autoscaling of Cosmos throughput.

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [ ] All clarification questions are decided, not guessed (rows 2 and 4 are ASSUMPTIONS for plan approval)

## Execution state
| Item | Status | Branch/worktree | Notes |
|---|---|---|---|
| 1 | todo | | |
| 2 | todo | | |
| 3 | todo | | |
| 4 | todo | | |
| 5 | todo | | |
| 6 | todo | | needs Docker |
| 7 | todo | | 7b serial-after PRP-82 |
| 8 | todo | | |

## Completion note (filled at ship)
- Date and PR:
- Deviations:
- Descoped items:
- OPEN gates:
- Env vars for the operator:
- Follow-up issue numbers:
- Product check (can an operator use it without editing files):
