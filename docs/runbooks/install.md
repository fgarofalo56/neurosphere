# Install runbook

> **Status: DRAFT.** Not yet validated by an independent new-user test. See [new-user-test.md](new-user-test.md). An author walking their own steps does not count.

This runbook takes a person with only the published docs from a clean machine to a healthy local stack with synthetic data. Everything is local and uses emulators: no paid calls, no cloud deployment. Emulators are not production-equivalent.

Style and extra detail live in [Local development setup](../dev/local-setup.md); this runbook is the ordered path and links there instead of repeating it.

## Rules

- Never read or commit `.env`; `.env.example` lists variable names only.
- Python is `python`, not `python3`. Use forward slashes in every path.
- Synthetic sandbox data only. Do not point the stack at production data.

## 1. Prerequisites

Docker Desktop, Git (Git Bash on Windows), Python 3.12, uv, Node.js 24 LTS, pnpm 11, make. Exact pins: [ADR-0002](../adr/0002-stack-pins.md).

Check what you have before you start:

```bash
docker --version
git --version
python --version
uv --version
node --version
make --version
```

Also run `pnpm --version` (it should print 11.x).

Node must be 24.x: the repository declares `>=24 <25`, and a newer Node (for example 26) prints `Unsupported engine` warnings from every pnpm command. The demo and lint worked on a newer Node in the automated run, but that is not a supported setup. Python may be newer than 3.12 on the host; `uv sync` provisions the interpreter the project needs. Docker Desktop must be running before section 4.

## 2. Get the code and do the one-time setup

Clone the repository, then run the setup from its root. Every later command assumes you are in that directory.

```bash
git clone https://github.com/fgarofalo56/neurosphere.git
cd neurosphere
```

```bash
uv sync && pnpm install && bash scripts/install-git-hooks.sh
```

## 3. Fastest path: demo with a mock API (no Docker)

```bash
pnpm demo
```

It prints a local URL (default `http://127.0.0.1:5180`) once the app and the mock API (port 5181, which has no page of its own) are up; this takes under a minute. Open the URL in a browser: the banner "Demo data, mock API" is always shown. Stop with Ctrl+C. If a port is busy, set `NS_DEMO_APP_PORT` and `NS_DEMO_API_PORT` as described in [local-setup.md](../dev/local-setup.md).

## 4. Emulator stack with seeded data

```bash
make dev-up
make dev-ps
make seed
```

`make dev-up` starts Cosmos, Azurite and the Event Hubs emulator and waits for health. `make seed` generates deterministic synthetic data and loads it (idempotent).

If emulators of this project are already running (for example from another checkout), `make dev-up` recreates a container whose compose definition changed. A recreated Event Hubs emulator loses its events, so run `make seed` again afterwards.

Healthy means every service in `make dev-ps` is healthy. If not, `make dev-logs`, then `make dev-reset` to start empty.

## 5. Full local platform (real Entra sign-in)

This needs your own Entra app registration and policy-store grant. Follow "Real local sign-in" and "Real stack" in [local-setup.md](../dev/local-setup.md); those steps use placeholders for tenant and client ids that you supply and never commit. In short:

```bash
make stack-up
curl -fsS http://127.0.0.1:8080/readyz
```

`make stack-up` refuses to run until `NS_ENTRA_TENANT_ID` and `NS_ENTRA_CLIENT_ID` are exported. Copilot answers `503 copilot_unconfigured` locally until a model endpoint is configured; that is expected.

## 6. Verify

```bash
python scripts/validate_planning.py
make lint
make test
```

`make test` runs the whole Python suite and takes more than ten minutes on a laptop. For a quick check, `python scripts/validate_planning.py` and `make lint` are enough.

## 7. Stop

```bash
make stack-down
make dev-down
```

`make stack-down` already stops the emulators. `make dev-down` stops them and drops their volumes, so the next `make dev-up` starts empty. Skip it if you want to keep the data.

## Hosted (Azure) deployment

Hosted demo steps are in [hosted-demo.md](../deploy/hosted-demo.md) and the requirements in [AZURE-DEPLOYMENT.md](https://github.com/fgarofalo56/neurosphere/blob/main/docs/AZURE-DEPLOYMENT.md). They need operator approval and an approved subscription; this runbook does not repeat them. Cloud and region availability, feature maturity and authorization are separate gates, see [RESEARCH-AND-GATES.md](../RESEARCH-AND-GATES.md).
