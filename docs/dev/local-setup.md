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

The demo starts the mock with `NS_MOCK_PROFILE=demo`, a richer fixture profile (30 days of cost, latency, error and coverage points per currency and kind, with some unknown and incomplete points; a 30-node topology; more recommendations, reports, review items, intents and MCP servers) so every route shows data on a first visit. It is also why the signed-in persona is `Steward` (the stub MSAL instance takes a role list, default `Viewer` for e2e) and why the demo mock lets that persona open the placeholder workspaces and MCP administration. The default e2e profile is unchanged. The UI style (Ops console or Enterprise Fluent) is switched from the account menu; a deployment default can be set with the optional `defaultUiStyle` key in `config.json`. `tests/e2e/demo-audit.spec.ts` starts its own demo-mode app and mock on ports 5312 and 5313 and checks every route in `route-manifest.json`.

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

2. Start it: `make stack-up`. It checks both variables, generates the sandbox data (`make sandbox-generate`, mounted read-only into the workers for the `recommendations` and `evaluation` roles), runs `docker compose --profile app up -d --wait --build`, then seeds from the host against `127.0.0.1`: first the sandbox seed (creates the isolated `sandbox-neurosphere` database behind `/sandbox`), then the stack seed with the same tenant and worker object id as the workers (the seed refuses non-loopback hosts, so it is a host step, not a compose service). Add `OPERATOR_OID=<your-object-id>` to also grant yourself admin in the same step. Re-running is safe; the seed is idempotent.
3. Grant yourself a role (policy-store grant, step 3 of "Real local sign-in") if you did not pass `OPERATOR_OID`: `make grant-operator OPERATOR_OID=<object-id> OPERATOR_ROLE=admin`.
4. Open `http://localhost:8080` and sign in. `curl -fsS http://127.0.0.1:8080/readyz` answers through the edge (200 `ready`).
5. Stop it: `make stack-down` (stops the whole project, emulators included; `make dev-up` brings the emulators back).

Good to know:

- Copilot is `disabled` here, so the assistant answers 503 `copilot_unconfigured`. That is expected until a model endpoint is configured (PRP-32).
- Port 8080 busy? `NS_FRONTEND_PORT=8082 make stack-up`, and register `http://localhost:8082` as a SPA redirect URI.
- Every worker role in `all` reports ready (workers publish no host port: `docker compose exec workers python -c "import urllib.request as u; print(u.urlopen('http://127.0.0.1:8090/readyz').read().decode())"`). Use `make stack-up`, not a bare `docker compose --profile app up`: it generates the sandbox directory the workers mount and seeds the sandbox database first (the stack seed expects the sandbox events to be on the hub already, never the reverse).
- The seed rebases its generated world to the run time: the newest event is 30 minutes old and everything sits inside the profile's days (4 for `small`), so the overview cost tile and trace replay have data. It also writes the catalog entities (agents, grounding sources, model deployments, people) through the catalog repository, so the map has nodes. With `OPERATOR_OID` it saves a report owned by you; the analyst persona's reports stay private to that persona (no visibility rule is widened).
- Re-running the seed is a no-op, including on a later day: it recovers the first run's time shift from the ledger, regenerates identical ids and windows, and creates nothing. The data therefore does not re-age; it just gets older. For fresh data run `make stack-down` and `docker compose down -v`, then `make stack-up`. A stack seeded by an older version keeps its 2026-10-01..04 dates until you do.
- Checks: `uv run pytest -q services/api/tests/runtime_routes` (no emulators), and with the stack up and seeded `NS_PROBE_COSMOS_URL=http://127.0.0.1:8081/ MSYS_NO_PATHCONV=1 uv run pytest -q -m integration tests/integration/compose tests/integration/real_stack`. The browser run is a manual gate: `NS_REAL_STACK_PORT=8080 pnpm --filter @neurosphere/frontend exec playwright test -c playwright.real-stack.config.ts --headed` (a window opens; complete the Entra sign-in).

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
