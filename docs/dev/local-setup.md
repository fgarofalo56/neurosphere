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
