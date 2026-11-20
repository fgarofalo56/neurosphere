# Local development setup

This runbook gets a contributor from a clean machine to a healthy local emulator stack, seeded with synthetic data, and a green fast gate run. Everything here is local and offline: Azure emulators only, no paid calls, no cloud deployment.

The emulators are development tools. Nothing in this stack is production-equivalent, and results from it make no claim of production parity (see [Emulator limits](#emulator-limits)).

## Rules that always apply

- **Never read `.env`** (or any `.env.*` other than `.env.example`), credentials files, or secrets. `.env.example` documents variable names only.
- No secret literals in files, prompts or logs. Scripts read connection settings from environment variables with documented local defaults produced at runtime.
- Python is `python`, not `python3`.
- Synthetic sandbox data is isolated; do not point the stack at production data.

## Prerequisites (Windows 11 + Git Bash)

| Tool | Version | Note |
|---|---|---|
| Docker Desktop (WSL 2 backend) | current | Needs several GB of memory, see [Troubleshooting](#troubleshooting) |
| Git for Windows (Git Bash) | current | Use POSIX syntax: forward slashes, `/dev/null`, `$VAR` |
| Python | 3.12 | See [ADR-0002](../adr/0002-stack-pins.md) |
| uv | 0.12 | |
| Node.js | 24 LTS | |
| pnpm | 11.x | |
| make | any | Provided with Git Bash tooling or via your package manager |
| PowerShell | 5.1+ | Needed only to run `verify-gates.ps1` |

Pins are authoritative in [ADR-0002](../adr/0002-stack-pins.md).

### One-time setup

Clone the repository first (`git clone https://github.com/fgarofalo56/neurosphere.git`, then `cd neurosphere`) and run everything below from its root. Node must be 24.x; a newer Node only prints `Unsupported engine` warnings from pnpm.

```bash
uv sync && pnpm install && bash scripts/install-git-hooks.sh
```

The git hooks (`.githooks/`, wired via `core.hooksPath`) are the local secret guard; CI is the backstop.

### Devcontainer alternative

Open the repository in a devcontainer (`.devcontainer/devcontainer.json`): Python 3.12, Node 24, uv, pnpm 11 and Docker-outside-of-Docker are provided, the emulator ports are forwarded, and post-create runs `uv sync --frozen` and `pnpm install --frozen-lockfile`. The emulators run on the host Docker engine, so start them with `make dev-up` from inside the container.

## Start and reset the stack

```bash
make dev-up      # start cosmos, azurite, eventhubs and wait for health
make dev-down    # stop and drop volumes
make dev-reset   # down -v + up: empty, healthy stack
make dev-logs    # tail emulator logs
```

Default profile services and ports:

| Service | Ports | Purpose |
|---|---|---|
| `cosmos` | 8081 | Cosmos DB vNext Linux emulator (NoSQL API, HTTP) |
| `azurite` | 10000, 10001, 10002 | Blob, Queue, Table |
| `eventhubs` | 5672 (AMQP), 9092 (Kafka) | Event Hubs emulator; needs Azurite healthy first |

The Event Hubs emulator has no persistence: every `docker compose down` (and `make dev-down`) loses its events. Seeding is designed to be re-runnable from scratch.

## Seed and replay synthetic data

```bash
make seed        # generate deterministic sandbox data, load Cosmos and the telemetry hub (idempotent)
make replay      # push synthetic events (incl. bad ones) to the telemetry hub
make seed-reset  # drop sandbox-* Cosmos DBs, restart Event Hubs emulator (empty hub); run make seed again to re-seed
```

These targets are the documented contract of the seed-and-replay CLI. Seeding creates fresh `sandbox-` prefixed databases and containers and never touches other names. Output is deterministic for a given `--seed`.

## Run gates

```bash
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode fast
```

The `~/` spelling is deliberate: it runs through bash, where `$env:USERPROFILE\...` would expand `$env` to empty. Planning alignment check: `python scripts/validate_planning.py`.

## Local demo (mock API)

`pnpm demo` (from the repo root, or `pnpm --filter @neurosphere/frontend demo`) starts the e2e mock API and the Vite dev server in `demo` mode, waits until both are healthy, then prints the URL (default `http://127.0.0.1:5180`). It needs no Docker, no Azure and no tenant.

| Env var | Default | Meaning |
|---|---|---|
| `NS_DEMO_APP_PORT` | `5180` | Vite app port (strict: fails if taken) |
| `NS_DEMO_API_PORT` | `5181` | Mock API port; also passed to the app as `VITE_NS_DEMO_API_PORT` |

What is stubbed: sign-in is the same fake MSAL instance the e2e suite uses (a fixed "E2E User", no redirects), the runtime config points at the mock API instead of `public/config.json`, and every response is synthetic fixture data from `frontend/tests/mock-api/server.ts`. A persistent "Demo data, mock API" banner is shown on every page so a demo is never mistaken for a real environment.

The demo starts the mock with `NS_MOCK_PROFILE=demo`, a richer fixture profile (30 days of cost, latency, error and coverage points per currency and kind, with some unknown and incomplete points; a 30-node topology; more recommendations, reports, review items, intents and MCP servers) so every route shows data on a first visit. It is also why the signed-in persona is `Steward` (the stub MSAL instance takes a role list, default `Viewer` for e2e). Authorization is identical to the e2e profile, so the demo never shows access the product would not grant: admin-only pages (MCP administration) and the other personas' workspaces show the access-denied state by design. The default e2e profile is unchanged. The UI style (Ops console or Enterprise Fluent) is switched from the account menu; a deployment default can be set with the optional `defaultUiStyle` key in `config.json`. `tests/e2e/demo-audit.spec.ts` starts its own demo-mode app and mock on ports 5318 and 5319 and checks every route in `route-manifest.json` (an explicit allowlist of routes must show the access-denied state).

It never ships: the demo branch sits behind `import.meta.env.MODE === "demo"` and is tree-shaken from production builds. `frontend/tests/prod-exclusion/no-demo-in-prod.test.ts` builds for production and fails if the banner or stub sign-in appears, and fails if the Dockerfile, nginx config or Helm chart mention a demo flag.

Stop it with Ctrl+C; both child processes are stopped. If a port is busy, set the env vars above to free ones.

## Real local sign-in

Sign in to the locally running app with your own Entra account. Two things are needed, and they are different: the app registration (so Entra issues a token the API accepts) and a policy-store grant (so the API lets you do anything).

**App roles only drive navigation display. Authority comes from the policy store.** Without step 3 the pages show but every API call answers 403.

1. Get your object id: `az ad signed-in-user show --query id -o tsv`.
2. Prepare the app registration. Dry-run first (Graph GETs only, prints a before/after diff of redirect URIs and role values), then apply with operator approval. Use your own `<app-id>` and `<tenant-id>`; they are never committed.

   ```bash
   python scripts/gates/p29_entra_local.py --app-id <app-id> --tenant-id <tenant-id>
   NS_LIVE_APPROVED=1 python scripts/gates/p29_entra_local.py --app-id <app-id> --tenant-id <tenant-id> --apply --assign-self admin
   ```

   It adds the `spa` redirect URIs `http://localhost:5173` and `http://localhost:8080`, the five app roles, and sets `requestedAccessTokenVersion` to 2. It only merges and is safe to re-run.
3. Grant yourself a role in the local policy store (emulator must be up and seeded, `NS_AUTH_TENANT_ID=<tenant-id>` exported):

   ```bash
   make grant-operator OPERATOR_OID=<object-id> OPERATOR_ROLE=admin
   ```

   or `python scripts/sandbox/sbx_grant_operator.py --object-id <object-id> --role admin`. It refuses a non-loopback Cosmos endpoint and uses the same pseudonym key resolver as the API.
4. Sign in. The grant is time-bound for privileged roles (30 days); re-run step 3 to renew.

## Real stack

The whole platform on your machine: the nginx edge with the built SPA (`http://localhost:8080`), the API, the workers and the three emulators, with a real Entra sign-in. Emulators only, no paid calls. It needs the app registration and grant from "Real local sign-in" above.

1. Export the two ids of your `neurosphere-api-dev` app registration (your own values; they are never committed, and compose has no default for them). The tenant id is `az account show --query tenantId -o tsv`; the client id is `az ad app list --display-name neurosphere-api-dev --query "[0].appId" -o tsv`:

   ```bash
   export NS_ENTRA_TENANT_ID=<tenant-id>
   export NS_ENTRA_CLIENT_ID=<client-id>
   ```

2. Start it: `make stack-up`. It checks both variables, generates the sandbox data (`make sandbox-generate`, mounted read-only into the workers for the `recommendations` and `evaluation` roles), starts the emulators (`docker compose up -d --wait`), then seeds from the host against `127.0.0.1`: first the sandbox seed (creates the isolated `sandbox-neurosphere` database behind `/sandbox`), then `seed-stack --grants-only` (the worker principal's domain grants, nothing else), and only then `docker compose --profile app up -d --wait --build`, because the evaluation role refuses to start until its pilot domain is granted (`evaluation_pilot_domain_out_of_scope`, #205). The full stack seed then runs with the same tenant and worker object id as the workers (the seed refuses non-loopback hosts, so it is a host step, not a compose service). Add `OPERATOR_OID=<your-object-id>` to also grant yourself admin in the same step. Re-running is safe; the seed is idempotent.
3. Grant yourself a role (policy-store grant, step 3 of "Real local sign-in") if you did not pass `OPERATOR_OID`: `make grant-operator OPERATOR_OID=<object-id> OPERATOR_ROLE=admin`.
4. Open `http://localhost:8080` and sign in. `curl -fsS http://127.0.0.1:8080/readyz` answers through the edge (200 `ready`).
5. Stop it: `make stack-down` (stops the whole project, emulators included; `make dev-up` brings the emulators back).

Good to know:

- Copilot is `disabled` here, so the assistant answers 503 `copilot_unconfigured`. That is expected until a model endpoint is configured (PRP-32).
- Port 8080 busy? `NS_FRONTEND_PORT=8082 make stack-up`, and register `http://localhost:8082` as a SPA redirect URI.
- Every worker role in `all` reports ready (workers publish no host port: `docker compose exec workers python -c "import urllib.request as u; print(u.urlopen('http://127.0.0.1:8090/readyz').read().decode())"`). Use `make stack-up`, not a bare `docker compose --profile app up`: it generates the sandbox directory the workers mount and seeds the sandbox database first (it passes `--no-events`: since the replay envelope fix (#162) the sandbox events would land in the ledger, and the stack seed publishes its own world only into an empty ledger).
- The seed rebases its generated world to the run time: the newest event is 30 minutes old and everything sits inside the profile's days (4 for `small`), so the overview cost tile and trace replay have data. It also writes the catalog entities (agents, grounding sources, model deployments, people) through the catalog repository, so the map has nodes. With `OPERATOR_OID` it saves a report owned by you; the analyst persona's reports stay private to that persona (no visibility rule is widened).
- Re-running the seed is a no-op, including on a later day: it recovers the first run's time shift from the ledger, regenerates identical ids and windows, and creates nothing. The data therefore does not re-age; it just gets older. For fresh data run `make stack-down` and `docker compose down -v`, then `make stack-up`. A stack seeded by an older version keeps its 2026-10-01..04 dates until you do.
- Event Hubs backlog: `test_catalog_discovery` and `test_evaluation_loop` (in `tests/integration/real_stack`) need an EMPTY Event Hubs emulator; a backlog from an earlier seed or replay makes them fail. Reset it with `make seed-reset` (drops the sandbox databases and restarts the `eventhubs` emulator), or `make dev-reset` for everything. `test_seed` uses its own database and deletes it, so it is repeatable; it asserts `skipped_existing == 0` on its first run because the seed counts entities the projection workers wrote during the run as seeded, not as pre-existing (#211).
- `make replay` sends the generated telemetry wrapped in the ingestion envelope (`HubMessage`), like the seed; unparseable lines stay raw, so they are still quarantined (#162).
- Checks: `uv run pytest -q services/api/tests/runtime_routes` (no emulators), and with the stack up and seeded `NS_PROBE_COSMOS_URL=http://127.0.0.1:8081/ MSYS_NO_PATHCONV=1 uv run pytest -q -m integration tests/integration/compose tests/integration/real_stack`. The browser run is a manual gate: `NS_REAL_STACK_PORT=8080 pnpm --filter @neurosphere/frontend exec playwright test -c playwright.real-stack.config.ts --headed` (a window opens; complete the Entra sign-in).
- Headless browser run without Entra (PRP-38 item 6, the CI job `real-stack-browser`): with only the emulators up (`docker compose up -d --wait`), `NS_REAL_STACK_MODE=ci NS_E2E_APP_PORT=5300 NS_STAND_IN_API_PORT=8765 pnpm --filter @neurosphere/frontend exec playwright test -c playwright.real-stack.config.ts`. It starts `tests/integration/real_stack/serve_stand_in_api.py` (the composed API and workers over the emulators, trusting an in-memory dev issuer; test-only, database `ns_browser_flows`) and `vite`, seeds the stack, builds the MSAL cache with msal's `loadExternalTokens`, then runs the route walk and the catalog, quality, actions and copilot flow specs. The copilot flow asserts the typed `copilot_unconfigured` 503 because no model is configured.

## Demo profile

The real stack with a curated, believable world and the features that are merely off by default turned on against local backends. Synthetic data only, local and CI only: the `demo-world` profile is never loaded into a hosted environment, and the seed refuses `--hosted` with it.

1. Export the two Entra ids as in "Real stack" and sign in to the Azure CLI (`az login`).
2. Start it with your own object id so your sign-in is granted: `make demo-up OPERATOR_OID=$(az ad signed-in-user show --query id -o tsv)`. This is `make stack-up` with `SEED_PROFILE=demo-world` and `infra/dev/demo-profile.env` applied; the ordering is the same. Start from empty emulators (`docker compose down -v` first): a stack seeded earlier by another profile or by a test suite makes this seed a no-op.
3. Check it: `make demo-check`. It calls the backing API of every route in `frontend/src/app/route-manifest.json` as you (the token comes from `az account get-access-token`, is held in memory and is never printed or written), and fails on an empty page that is not in the `demo_expected_empty` allow-list in `scripts/sandbox/sbx_demo_check.py`. It also reads `/api/v1/admin/system/status` and the demo-world expectations. `--json` prints the same report as JSON; `--wait-seconds` bounds how long it waits for agent health.
4. Stop it: `make demo-down`.

What the world contains (ids and names are stable and listed in `sandbox/demo/README.md`): 32 named agents in four domains (finance, support, human resources, security operations) with descriptions, tags, capabilities, owners and versions; 7 services, 16 tools, 4 model deployments, one MCP server and 15 data assets with classification, sensitivity categories and EU or US residency; `owned_by`, `uses_model`, `invokes`, `reads`, `writes`, `depends_on`, `grounded_by` and `delegates_to` edges; four agents that exist only in telemetry and show up as discovered drafts; and one scripted incident in which `payments-gateway` fails during the last hour of the seeded window and its five downstream agents degrade while the other 27 do not.

What is real and what is fake:

- Producer store (`NS_INGEST_PRODUCER_STORE=true`): real. Producers are read from the admin store in the Cosmos emulator instead of the mounted file.
- MCP server: real and mounted on the API at `https://127.0.0.1:8000/mcp` as its resource URL; it validates real Entra tokens. No MCP client is started for you.
- Deployment scan (`NS_SCAN_ENABLED=true`): the feature is on and reports enabled, but its scope is a synthetic all-zero subscription and the API container has no Azure sign-in, so no real resource is scanned.
- Lifecycle (`NS_LIFECYCLE_MODE=dry_run`): real evaluation of the rules, dry-run only. Nothing is executed.
- Detector recommendations (`NS_WORKER_REC_SOURCE=archive`): real detectors over the archived demo telemetry.
- Worker roles: all roles run. The connector roles (billing export, gateway poll, Foundry discovery) are configured but idle because they have no source to read.
- Stored feature settings (`scan`, `mcp_server`, `search`, `copilot`, `write_targets`): real rows written through the same validation and audit as the settings PUT route. `search`, `copilot` and both write targets are stored disabled with placeholder names; nothing calls those hosts.
- Write targets: advisory only. The Azure management host cannot be pointed at a loopback fake (the cloud profile and the client factory refuse a non-cloud host), so there is no local fake and apply stays OPEN.
- Copilot: off. `NS_DEMO_COPILOT_MODE=disabled`, the routes answer 503 `copilot_unconfigured`, and `make demo-check` reports `pending_prp_78`. PRP-78 adds the recorded mode and flips this switch. For a real endpoint, set `NS_COPILOT_MODE` and the `NS_COPILOT_*` values as in `docs/runbooks/copilot.md`; an exported `NS_COPILOT_MODE` wins over the demo switch.
- Evaluation: the pilot domain is the demo finance domain (`NS_WORKER_EVAL_PILOT_DOMAIN_ID`), because the default pilot domain does not exist in the demo world.
- Sign-in: real Entra. In the demo world your object id is granted `admin` and, as four more explicit grants over the demo domains, each of the other persona roles, so one sign-in opens the role-gated pages (workspaces, audit, review queues). `make stack-up` with the `small` profile still grants `admin` only.

Good to know:

- The data arrives over time. The seed pushes about 8,500 telemetry and cost events through the Event Hubs emulator; ingestion and then the aggregates role drain them in event order, oldest first, so the most recent hours (the incident included) land last. The seed waits five minutes and then warns; `uv run python scripts/sandbox/sbx_demo_check.py --wait-seconds <n>` or a later `make demo-check` picks up the rest.
- The overview's "today" tile uses the current UTC day. The newest seeded event is 30 minutes older than the seed run, so after the next UTC midnight that tile is empty until you reset and seed again, as with any seeded stack.
- Reset: `make demo-down`, `docker compose down -v`, then `make demo-up`. `make seed-reset` and `make dev-reset` also drop the data. Stored settings live only in the local `admin_config` container.

## Emulator limits

Document and respect these. They are the known gaps between the emulators and the real services; the parity gate is [G12 in RESEARCH-AND-GATES.md](../RESEARCH-AND-GATES.md).

| Emulator | Limits |
|---|---|
| Cosmos DB vNext | No auth enforcement; no sprocs/triggers/UDF; no range/composite/spatial indexes; no RU accounting |
| Event Hubs | SAS only (no Entra); 1 namespace and 10 hubs max; no persistence across restarts; requires Azurite |
| Azurite | Table API is preview |

Consequences: do not write tests that pass only because auth is absent, and do not claim tenancy isolation from emulator runs. Producer identity is enforced at the ingest edge, not by the Event Hubs emulator. Emulator evidence for gates is "bounded feasibility" only; every item with a live component records emulator-versus-live deltas.

## Image digests

Tags follow ADR-0002 (`vnext-latest`, `latest`) because the emulators publish no stable pins. Floating tags are a **drift risk**: a new pull can change behaviour without any repository change.

| Image | Tag | Digest |
|---|---|---|
| Cosmos DB vNext emulator | `vnext-latest` | `sha256:4535ddbd27bba762f3e068f7585feb0022a2559ceccc9394b23aa38d91d77c38` |
| Azurite | `latest` | `sha256:830430c1da1a2d537e08f3e6764dd1f5ae00cf0346bcaf625b968ec3f0971fd5` |
| Event Hubs emulator | `latest` | `sha256:be413f0d59541621879e6d197d73f64f3b3ac5fa45861641fdc1430252b8b44b` |

Record digests with `docker image inspect --format '{{index .RepoDigests 0}}' <image>`.

## Microsoft emulator EULA

The Event Hubs emulator image requires accepting the Microsoft emulator license terms. `docker-compose.yml` sets `ACCEPT_EULA: "Y"` for that service; by running the stack you are operating under those terms, which apply to your use of the emulator images.

## Troubleshooting

- **Port conflict** (`bind: address already in use`): another process holds 8081, 10000-10002, 5672 or 9092. Find it with `netstat -ano | findstr :8081`, stop it, then `make dev-up`.
- **EULA error from `eventhubs`**: confirm `ACCEPT_EULA` is set to `Y` in the compose file and that you accept the Microsoft terms above.
- **`eventhubs` never becomes healthy**: it depends on Azurite. Check `docker compose ps` and `make dev-logs`; Azurite must report healthy first. Restart with `make dev-down && make dev-up`.
- **Azurite unhealthy**: its healthcheck probes port 10000. Look for a port clash or a crashed container in the logs.
- **Cosmos emulator slow or exiting**: the emulator is memory hungry. Raise the Docker Desktop / WSL 2 memory limit (`.wslconfig`) and close other containers.
- **Events missing after a restart**: expected; the Event Hubs emulator does not persist. Re-run the seed and replay steps.
- **A path looks mangled in Git Bash**: prefix the command with `MSYS_NO_PATHCONV=1`.
