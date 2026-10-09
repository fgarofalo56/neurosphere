---
name: prp-03-local-dev-environment-and-sandbox-generator
status: backlog
review: none
created: 2026-10-08
model: sonnet
phase: 0
ns: NS-10
depends_on: PRP-01
wave: W2
absorbs: new
---

# PRP-03: Local dev environment and sandbox generator

## Goal

Give every later PRP a reproducible, offline development stack and realistic synthetic data. The compose stack (Cosmos vNext emulator, Event Hubs emulator, Azurite) already exists as a starting point in `docker-compose.yml` and `infra/compose/eventhubs.config.json`; this PRP hardens it with profiles, an egress-blocked test network and helper configs. A deterministic fixture search index implements the `AuthorizedSearch` protocol for offline tests. A seeded synthetic generator under `sandbox/` replaces the deleted Artemis procurement generator (D3) and produces AI-governance entities only: agents and sub-agents, models, grounding sources, pseudonymized people, delegation traces, cost records, injected anomalies, and deliberately bad events (duplicates, out-of-order, malformed). A seed-and-replay CLI loads it into the emulators and pushes events to the Event Hubs emulator. A devcontainer and local-setup runbook make a new contributor productive. The audience is every implementer from PRP-05 on, plus the demo and sandbox mode (PRP-24). It runs now (wave W2) because ingestion, catalog, recommendations and dashboards cannot be tested without it, and because no production data may be used in demos or tests by default.

Requirement text fulfilled, quoted from `docs/PRD.md`:

> Branded static documentation/Pages site, API/SDK references, ADRs, setup/migration/security/operations/DR runbooks, walkthroughs and synthetic sandbox. (NS-10)

> Real connectors require credentials, consent and applicable licensing; synthetic mode is isolated and available without external credentials. (PRD section 4)

Binding from CLAUDE.md: "Synthetic sandbox is isolated; real ingestion is permitted only with authorized connectors/credentials and privacy policy. Never use production data in demos/tests by default."

## Acceptance criteria

- [ ] Item 1: `docker compose up -d --wait` brings all emulator services healthy in under 5 minutes on a clean machine (measured, recorded); a test attached to the egress-blocked network proves zero outbound calls; `make dev-up`, `dev-down`, `dev-reset` targets exist.
- [ ] Item 2: Given the same query and the same `IdentityScope`, when run twice (and across processes), then the ranked ID list is identical; a document outside the scope is never returned.
- [ ] Item 3: Generator output validates against every PRP-01 schema it touches; an anomaly manifest lists each injected anomaly (spike, latency regression, unused agent, duplicate agents) with IDs and windows; identical seed yields byte-identical output; output contains no procurement or Artemis terms and no real person data.
- [ ] Item 4: `make seed` is idempotent: a second run creates zero new documents and zero duplicate events (counted); replay pushes sandbox events (including the bad ones) to the `telemetry` hub of the emulator.
- [ ] Item 5: A new-user walkthrough from `docs/dev/local-setup.md` using only documented commands reaches a seeded stack and a green `verify-gates -Mode fast`; the devcontainer builds.
- [ ] PRP exit: `verify-gates -Mode full` green; `python scripts/validate_planning.py` clean for this file; no network call to a non-local host during any gate (egress test); no paid call anywhere.

## Clarifications (decided)

| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| 1 | Local dev approach (D8) | compose; in-memory fakes only; compose + devcontainer | Docker Compose with Azure emulators plus a devcontainer (this PRP delivers the devcontainer deferred in D8). |
| 2 | Legacy generator (D3) | adapt old; replace | The Artemis procurement generator (`data/synthetic_data.py`) is deleted and stays deleted. `sandbox/` is a new generator; do not restore or port procurement concepts (vendors, purchase orders, materials). |
| 3 | Live gates (D7) | per PRP | None. Everything is local; no `NS_LIVE_APPROVED` item exists here. |
| 4 | Model policy (D6) | Sonnet; Opus | Sonnet; no review pass required (`review: none`), done when touched tests pass and the walkthrough works. |
| 5 | Emulator limits | hide; document | Document in the runbook: Cosmos vNext has no auth enforcement, no sprocs/triggers/UDF, no range/composite/spatial indexes, no RU accounting; Event Hubs emulator is SAS only (no Entra), 1 namespace and 10 hubs max, no persistence across restarts, requires Azurite; Azurite Table API is preview. Cross-reference G12. |
| 6 | Compose profiles | single; profiles | Default profile: `cosmos`, `azurite`, `eventhubs`. Profile `app` is reserved for PRP-05 (api, workers; left commented with a pointer). Profile `test` adds the egress-blocked network and a probe container. |
| 7 | Image tags | pin; latest | Keep tags from ADR-0002 (`vnext-latest`, `latest`) because the emulators publish no stable pins; record the digests actually used in `docs/dev/local-setup.md` after first successful pull, and flag it as drift risk. |
| 8 | Event Hubs EULA | silent; explicit | `ACCEPT_EULA: "Y"` stays in compose with the existing comment; the runbook states the Microsoft emulator EULA applies. |
| 9 | Fixture search index | in-process; separate service | In-process Python implementation in `packages/core/neurosphere_core/search/fixture/` (deterministic BM25-style scoring or term-frequency; no randomness, no embeddings, no network). Ties broken by canonical ID ascending. |
| 10 | `AuthorizedSearch` protocol home | here; elsewhere | The protocol definition belongs with core primitives; if `neurosphere_core.search` has no protocol yet, item 2 defines it in `packages/core/neurosphere_core/search/protocol.py` and PRP-10 item 6 implements the Azure version against it. The protocol takes an `IdentityScope`, a `StructuredQuery`-style filter set and a `Budget`, never raw query text from a model. |
| 11 | Generator determinism | wall clock; seeded | Single `--seed` integer and a fixed `--epoch` start time; no `datetime.now()` and no `uuid4()` in output paths (derive IDs from seeded RNG). |
| 12 | Generator scale profiles | one; several | `tiny` (smoke, tens of agents), `pilot` (1k agents, matching the PRD pilot planning target; event volume parameterized), `custom`. The PRD enterprise (100k) and stress profiles are targets for PRP-21 load tests; the generator must be able to scale to them in streaming mode but this PRP does not run them. |
| 13 | People | realistic; pseudonymous | Pseudonymous principals only (stable hash-like pseudonyms from the seed); no names, emails, SSNs, addresses or phone numbers, even fake-looking real ones. |
| 14 | Cloud field in sandbox data | commercial only; both | Both `commercial` and `government` labelled data sets, never mixed in one output; a flag selects one. Government-labelled sandbox data is still synthetic and local. |
| 15 | Bad-event mix | none; configurable | Config percentages for duplicates, out-of-order (late by N seconds), malformed (schema-violating), and missing optional fields; defaults small and fixed; each bad event is listed in the manifest so PRP-07 tests can assert quarantine counts. |
| 16 | Seed target for Cosmos | create DB; reuse | Item 4 creates fresh databases and containers with a `sandbox-` prefix, never touches non-sandbox names (supports PRP-24 isolation). |
| 17 | Makefile ownership | shared; sectioned | Item 1 owns only `dev-*` targets in the existing `Makefile`; item 4 owns the `seed*` and `replay*` targets in the same file via a documented include, `scripts/sandbox/sandbox.mk`, which item 1 includes with one line. |

## Context manifest

### Files that matter

- `CLAUDE.md` - "Synthetic sandbox is isolated" and "No paid calls/cloud deployments without operator approval".
- `PRP.md` - section 2 (Event Hubs emulator transport for tests, AuthorizedSearch with local deterministic fixture index), section 3.
- `docs/PRD.md` - NS-01 envelope (generator output shape), NS-02 entities, NS-10, section 3 scale profiles (pilot 1k agents and 1k events per second as targets).
- `docs/ARCHITECTURE.md` - telemetry and projection flow (section 2): quarantine container, checkpoint store, outbox.
- `docs/RESEARCH-AND-GATES.md` - G12 emulator parity; emulator limits retrieved 2026-10-08.
- `docs/DECISIONS-LOG.md` - D3, D6, D7, D8, D9.
- `docker-compose.yml` - existing services: `cosmos` (vNext emulator, port 8081, http), `azurite` (ports 10000 to 10002, `--skipApiVersionCheck`), `eventhubs` (AMQP 5672, Kafka 9092, depends on healthy azurite, `ACCEPT_EULA`, mounts the config read-only). Project name `neurosphere`. Starting point; extend, do not rewrite.
- `infra/compose/eventhubs.config.json` - namespace `neurosphere-local`, hub `telemetry` (4 partitions; consumer groups `normalizer`, `aggregates`), hub `quarantine` (1 partition; group `replay`). The emulator allows at most 10 hubs; keep headroom.
- `Makefile` (exists, modified in working tree) - read first; add only the targets named in Clarification 17.
- `pyproject.toml` (root) - ruff, pyright, pytest markers `integration` and `live`.
- `.claude/hooks/config.ps1` - gate commands.
- `scripts/validate_planning.py`, `.env.example` (template only; never read `.env`).
- Created by PRP-00: workspace members and gates. Created by PRP-01: `neurosphere_contracts` generated models and `packages/contracts/schemas/` (telemetry, cost, catalog, scope, query), `tests/contracts/fixtures/` (examples to mirror).
- Not yet existing: `packages/core/neurosphere_core/clients/` (PRP-05, seed CLI uses SDKs directly with a local seam), `services/api` and `services/workers` Dockerfiles (PRP-05, PRP-13).

### Patterns to match

No product code exists yet, so these are rules, not file references.

- Pydantic v2 models with `model_config = ConfigDict(extra="forbid")`; the generator builds contract models from `neurosphere_contracts`, never ad hoc dicts.
- FastAPI routers per module under `services/api/neurosphere_api/<module>/router.py` (not used here).
- Async Azure SDK clients from `packages/core/neurosphere_core/clients` (PRP-05); until then, scripts use `azure-cosmos`, `azure-eventhub`, `azure-storage-blob` directly behind a small seam that PRP-05 can replace.
- Error taxonomy exceptions from `neurosphere_core.errors` (PRP-05).
- Tests beside packages plus cross-package suites in `tests/` (`tests/unit/`, `tests/integration/`).
- `pytest.mark.live` and `pytest.mark.integration` markers (declared in root `pyproject.toml`): anything needing the compose stack is `integration`; generator and search tests are offline unit tests.
- TypeScript strict with `@fluentui/react-components`; Vitest + Testing Library; Playwright under `frontend/tests/e2e` (not used here).

### Conventions

- ruff config in root `pyproject.toml`: line length 100, py312, `S` rules on (note `S311` flags `random`; the generator uses a seeded `random.Random` and documents the `noqa` with reason: not cryptographic); pyright standard.
- Conventional commits; commit scoped changes only after review; ask before push or deployment.
- Owned-file discipline; the `Makefile` is sectioned per Clarification 17.
- Evidence under `docs/evidence/<gate>/`; live scripts under `scripts/gates/` refuse without `NS_LIVE_APPROVED=1` (none here).
- Generated sandbox output goes under `./temp/sandbox/` or `sandbox/out/` and is gitignored; only golden mini-fixtures are committed.
- Forward slashes in commands; Python is `python`; Windows plus Git Bash: use `MSYS_NO_PATHCONV=1` when passing `/absolute` container paths.

### Gotchas

- Event Hubs has no DLQ: quarantine is an explicit container + replay CLI; checkpoints advance only after durable accept or quarantine. Metadata geo-DR copies neither payloads nor RBAC.
- `IdentityScope` is derived server-side; caller- or model-supplied `domain_id`/`customer_id` is ignored. Same scope object on REST, search, cache keys, exports, WebSocket, copilot tools, MCP.
- No LLM-generated SQL/Cypher/KQL/JS. Charts are a Vega-Lite subset (no `expr`, signals, external `url` data) rendered with `vega-interpreter` in a sandboxed iframe.
- Government is gated, not banned: disabled-with-reason from the capability matrix; separate endpoints (`login.microsoftonline.us`, `*.documents.azure.us`, `*.servicebus.usgovcloudapi.net`, `*.search.azure.us`). Never route Government data to Commercial.
- Fail closed: policy store outage returns 503. Privileged roles are scoped; no bypass.
- One action executor for button/chat/REST/MCP; same intent hash; permission and target version rechecked at execution; read-only connectors are advisory; no catalog-only pretend swaps.
- Costs: null/unknown never 0; estimated vs invoiced always distinct; projections cite price version. Provider billing freshness is not sub-10s.
- Catalog: raw events outside the graph; locks affect presented lineage not observations; traversals budgeted; ETag mismatch returns `stale_version`. Outbox is the projection baseline, not emulator change feed.
- Emulators: Event Hubs emulator lacks Entra, so producer identity is enforced at the ingest edge; Cosmos vNext emulator has no RU accounting, no sprocs/triggers/UDF, no range/composite/spatial indexes, so G03 emulator evidence is "bounded feasibility" only.
- `scripts/gates/*` refuse without `NS_LIVE_APPROVED=1`; missing live evidence is an open gate, never a skipped green test. No paid model calls in CI.
- No FedRAMP/ATO/parity claims. Availability, GA and authorization are separate matrix columns.
- Secrets via vault references; dev issuer only when `NS_ENV=local`; never read `.env`. Pseudonymize people; prompt/response bodies off by default; redact before archive and before any external transmission (judges, connectors).
- Hidden navigation is not authorization; the API must deny.
- Versions: Python 3.12, Node 24, TypeScript 6.0.x (not 7), Helm 4, MkDocs Material 9.7 (EOL 2026-11-05, evaluate Zensical), sigma 4 + graphology (never @cosmograph, CC-BY-NC), MCP SDK 2.x (spec 2026-07-28). See docs/adr/0002-stack-pins.md.
- CI contains no `|| true`; `scripts/validate_planning.py` fails if it does. Python is `python`, not `python3`.
- PRP-03 specific: the Event Hubs emulator needs Azurite healthy first and has no persistence; every `docker compose down` loses events. Seeding must be re-runnable from scratch; do not design anything that expects retained events.
- PRP-03 specific: the emulator connection strings are well-known development values documented by Microsoft. They still must not be committed as literals in new files and must not be copied from `.env`; scripts read them from environment variables with documented local defaults produced at runtime, and `.env.example` documents the variable names only. Never read `.env`.
- PRP-03 specific: because the Event Hubs emulator has no Entra, producer identity cannot be tested against it. The seed CLI pushes directly to the hub; identity enforcement is tested at the ingest edge in PRP-07, not here.
- PRP-03 specific: the Cosmos vNext emulator ignores authorization; do not write tests that pass only because auth is absent, and do not claim tenancy isolation from emulator runs.
- PRP-03 specific: the egress-blocked network must be `internal: true` in compose; verify with an actual probe (a container on that network attempting a connection to an external address must fail), not by reading the YAML.
- PRP-03 specific: `ruff` rule `S311` and `S324` will flag seeded RNG and hashing in the generator; use `random.Random(seed)` with an explained `# noqa: S311` and `hashlib.blake2b` for pseudonyms rather than weakening the rule globally.
- PRP-03 specific: the generator must not import from `services/*`; it depends on `neurosphere_contracts` only (and `neurosphere_core` types if stable). Generated IDs follow the PRP-01 canonical grammar `cloud:customer:source:type:id`.
- PRP-03 specific: duplicate-agent anomalies must be shared-source or overlap based (the PRD says duplicates are candidates for consolidation review, never auto-merged); label them as candidates in the manifest, not as ground truth merges.

### External references

Observed 2026-10-08 unless stated:

- Cosmos DB vNext Linux emulator (GA June 2026; limits): https://learn.microsoft.com/azure/cosmos-db/emulator-linux
- Event Hubs emulator (2026-08-26; SAS only, one namespace and ten hubs, no persistence, needs Azurite; GA status unverified): https://learn.microsoft.com/azure/event-hubs/overview-emulator
- Azurite (Table preview; no ADLS Gen2): https://learn.microsoft.com/azure/storage/common/storage-use-azurite
- Event Hubs metadata geo-DR (payloads and RBAC not copied; 2026-10-06): https://learn.microsoft.com/azure/event-hubs/event-hubs-geo-dr
- Cosmos hierarchical partition keys (2026-04-27; relevant to seeded container shapes): https://learn.microsoft.com/azure/cosmos-db/hierarchical-partition-keys
- ADR-0002 emulator rows (licences: Microsoft EULA for the two emulator images, MIT for Azurite): `docs/adr/0002-stack-pins.md`.
- Dev Containers specification: https://containers.dev/ (not yet observed; verify at implementation).
- Docker Compose profiles and `internal` networks: https://docs.docker.com/compose/ (not yet observed; verify at implementation).

## Implementation blueprint

### Item 1 — compose-stack  [P]
- Deliverable: extended `docker-compose.yml` with profiles (default emulators; `test` profile with an `internal: true` egress-blocked network and probe; `app` profile placeholders commented out for PRP-05), tuned healthchecks, named volumes only where the emulator supports them, and helper configs under `infra/compose/`; `dev-up`, `dev-down`, `dev-reset`, `dev-logs`, `dev-ps` targets in `Makefile`.
- Owned files (may edit): `docker-compose.yml`, `infra/compose/` (including `eventhubs.config.json`), `Makefile` (`dev-*` targets only), `tests/integration/compose/`.
- Must NOT touch: `packages/core/neurosphere_core/search/` (item 2); `sandbox/` (item 3); `scripts/sandbox/` including `sandbox.mk` (item 4); `.devcontainer/`, `docs/dev/` (item 5); root `pyproject.toml`; `docs/RESEARCH-AND-GATES.md`; `services/*/Dockerfile*` (PRP-05, PRP-13).
- Depends on: none
- Acceptance criteria:
  - `docker compose up -d --wait` reports all default services healthy in under 5 minutes (recorded in the completion note with machine specs).
  - With `--profile test`, a probe container on the internal network fails to reach an external address and reaches the emulators by service name (integration test).
  - Event Hubs config keeps `telemetry` and `quarantine` hubs and consumer groups; total hubs stay at most 10.
  - `make dev-reset` returns the stack to empty and healthy; no secret literal is added to the file (gitleaks clean).
- Pattern references: existing `docker-compose.yml` structure and header comment on emulator limits.
- Tests to write: `tests/integration/compose/test_stack_health.py`, `tests/integration/compose/test_egress_blocked.py` (both `integration`).

### Item 2 — fixture-search-index  [P]
- Deliverable: in-process deterministic implementation of the `AuthorizedSearch` protocol (index build from catalog entity documents, scoped filter applied before ranking, deterministic scoring, stable tie-break) plus the protocol definition if absent (Clarification 10).
- Owned files (may edit): `packages/core/neurosphere_core/search/__init__.py`, `packages/core/neurosphere_core/search/protocol.py`, `packages/core/neurosphere_core/search/fixture/`, `packages/core/tests/search/`.
- Must NOT touch: `packages/core/neurosphere_core/search/azure/` (PRP-10); other `neurosphere_core` subpackages (`errors`, `scope`, `paging`, `cloud`, `clients`, `capabilities`); `sandbox/` (item 3); contract schemas; `docker-compose.yml`.
- Depends on: none
- Acceptance criteria:
  - Same query and scope returns identical ranked IDs across repeated runs and across two separate processes (test spawns a subprocess).
  - A document whose domain is outside the supplied scope never appears, regardless of query terms (negative test with at least 10 cross-domain documents).
  - The index accepts only structured filters and a term string; there is no code path that evaluates caller-supplied expressions.
  - Budget exceeded (result limit, timeout) returns a partial result with a flag, not an unbounded list.
- Pattern references: PRP-01 `IdentityScope`, `StructuredQuery`, `Budget`, `Page` contracts.
- Tests to write: `packages/core/tests/search/test_fixture_determinism.py`, `test_fixture_scope_filter.py`, `test_fixture_budget.py`.

### Item 3 — synthetic-generator  [P]
- Deliverable: `sandbox/` package and CLI (`python -m sandbox.generate --seed N --profile tiny|pilot|custom --cloud commercial|government`) producing newline-delimited JSON for: Domains and Owners; Agents, sub-agents and AgentVersions; ModelDeployments; GroundingSources and Tools; pseudonymized Person principals; delegation traces (trace, span, parent span, tool calls, retries, errors, cancellation) as `TelemetryEvent`; `CostRecord` observations (estimated and invoiced, gateway, application and billing views of the same request to exercise de-duplication); declared and inferred relations; seeded anomalies (cost spike, latency regression, unused agent, duplicate agent candidates); and bad events (duplicates, out-of-order, malformed, missing optional fields); plus `anomaly-manifest.json` and a bad-event manifest.
- Owned files (may edit): `sandbox/` (code, config, README), `sandbox/tests/`.
- Must NOT touch: `scripts/sandbox/` (item 4); `packages/core/` including search (item 2); `packages/contracts/` (PRP-01); `docker-compose.yml` (item 1); `.devcontainer/`, `docs/dev/` (item 5); `sandbox/evaluation/` (PRP-16 adds it later; leave the path free); the deleted `data/` tree (do not recreate).
- Depends on: none
- Acceptance criteria:
  - Every emitted record validates against its PRP-01 schema; a validation test runs the `tiny` profile through the generated Pydantic models and the JSON Schemas.
  - Same seed and epoch produce byte-identical output (hash compared in test); different seeds differ.
  - The anomaly manifest lists each injected anomaly with ID, type, affected canonical IDs and time window; at least one of each type exists in `pilot`.
  - No procurement vocabulary (vendors, purchase orders, materials, Artemis) and no real or realistic personal data appears (deny-list test over output); people are pseudonymous principals only.
  - `pilot` profile generation completes within a documented time on the dev machine and streams (bounded memory).
- Pattern references: PRP-01 schemas and golden fixtures; PRD NS-01 envelope, NS-02 entities and relations.
- Tests to write: `sandbox/tests/test_determinism.py`, `test_schema_validity.py`, `test_anomaly_manifest.py`, `test_no_legacy_terms.py`, `test_bad_event_mix.py`.

### Item 4 — seed-and-replay-cli
- Deliverable: `scripts/sandbox/` CLI with `seed` (create `sandbox-` prefixed Cosmos databases and containers, load entities and relations, idempotent upserts by canonical ID), `replay` (push events to the `telemetry` hub of the Event Hubs emulator with rate control and ordering options, including the bad events) and `reset`; `scripts/sandbox/sandbox.mk` providing `seed`, `replay`, `seed-reset` make targets (included by the Makefile).
- Owned files (may edit): `scripts/sandbox/`, `tests/integration/sandbox/`.
- Must NOT touch: `sandbox/` generator code (item 3; consume its output only); `docker-compose.yml`, `infra/compose/`, `Makefile` content outside the one-line include owned by item 1; `packages/core/`; contract schemas; `.devcontainer/`, `docs/dev/`.
- Depends on: items 1, 3
- Acceptance criteria:
  - `make seed` run twice: the second run creates zero new documents and zero new events (counts asserted before and after).
  - Replay delivers the expected number of events to the `telemetry` hub (counted via a consumer using the `normalizer` group) including duplicates and malformed items exactly as listed in the bad-event manifest.
  - The CLI refuses to touch any database or container not prefixed `sandbox-`; refuses to run when the endpoint is not a local emulator address unless explicitly allowed (it never is in this PRP).
  - No connection string or key appears in logs or arguments.
- Pattern references: PRP-01 canonical IDs and etag fields; `docker-compose.yml` endpoints.
- Tests to write: `tests/integration/sandbox/test_seed_idempotent.py`, `test_replay_counts.py`, `test_prefix_guard.py` (integration marker; the prefix guard also has an offline unit variant).

### Item 5 — devcontainer-and-docs  [P]
- Deliverable: `.devcontainer/devcontainer.json` (Python 3.12, Node 24, uv, pnpm 11, Docker-outside-of-Docker or compose access, forwarded emulator ports, post-create running `uv sync --frozen` and `pnpm install --frozen-lockfile`) and `docs/dev/local-setup.md` runbook: prerequisites on Windows 11 with Git Bash, start and reset the stack, seed and replay, run gates, emulator limits table (Clarification 5), troubleshooting (port conflicts, EULA, Azurite health, memory), and the "never read `.env`" rule.
- Owned files (may edit): `.devcontainer/`, `docs/dev/local-setup.md`.
- Must NOT touch: `docker-compose.yml` and `infra/compose/` (item 1); `sandbox/`, `scripts/sandbox/` (items 3, 4); `README.md`, `CONTRIBUTING.md` (PRP-00 item 5); `.claude/hooks/config.ps1`; root config files.
- Depends on: item 1
- Acceptance criteria:
  - A new-user walkthrough using only commands in the runbook reaches: stack healthy, sandbox seeded, `verify-gates -Mode fast` green (walkthrough result recorded in the completion note).
  - The devcontainer builds and its post-create succeeds (build log excerpt recorded); if a container runtime was unavailable in the session, record the build as UNTESTED, not passed.
  - The runbook states emulator limits exactly as in this PRP and links G12.
  - The runbook contains no secret literal and no claim of production parity.
- Pattern references: `docs/ARCHITECTURE.md` section 2; ADR-0002 emulator rows.
- Tests to write: none (documentation); the walkthrough is the test.

## Validation gates

```
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode fast    # per item
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full    # before merge
python scripts/validate_planning.py
```

Feature-specific commands:

```
docker compose config --quiet
docker compose up -d --wait
uv run pytest tests/integration/compose tests/integration/sandbox -m integration -q
uv run pytest sandbox/tests packages/core/tests/search -q
python -m sandbox.generate --seed 1 --profile tiny --cloud commercial --out temp/sandbox
make seed
make seed
docker compose down
```

The two `make seed` runs are the idempotence check: the second must report zero created. No command needs `NS_LIVE_APPROVED=1`, and none contacts a non-local host.

## Live and open gates

| Gate | Effect of this PRP |
|---|---|
| G12 emulator parity | Narrowed by documenting emulator limits in the runbook and by egress and auth caveats in tests; stays OPEN until each PRP with a live item records emulator-versus-live deltas. |
| G03 graph benchmark | Not touched here; PRP-02 owns it. |
| G06 privacy and retention | Generator proves pseudonymous-only sandbox data; policy approval stays OPEN (PRP-23). |

If a live item did not run, record it OPEN in the completion note and in docs/RESEARCH-AND-GATES.md; never report it as a skipped green test.

## NOT building

- Application containers for api, workers and frontend (PRP-05, PRP-13); only commented placeholders.
- Real ingestion, real connectors, or any production or customer data path.
- Sandbox mode in the UI and API isolation enforcement (PRP-24); only the `sandbox-` naming discipline.
- Evaluation datasets and rubrics (`sandbox/evaluation/`, PRP-16).
- Load profiles at enterprise or stress scale (PRP-21).
- The Azure AI Search implementation of `AuthorizedSearch` (PRP-10).
- Any recreation of the Artemis procurement data, DAB/Kong gateway or zero-move scripts (deleted by D3).
- Any paid, cloud or external network call.

## Definition of Ready check

- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [x] All clarification questions are decided, not guessed

## Completion note (filled at ship)

- Date:
- Merged commits:
- Deviations from blueprint and why:
- Descoped items:
- Measured: stack healthy time, `pilot` generation time, seed run counts:
- Walkthrough and devcontainer build result (or UNTESTED):
- Open gates and follow-ups:
