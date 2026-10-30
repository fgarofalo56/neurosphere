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

## 2. One-time setup

```bash
uv sync && pnpm install && bash scripts/install-git-hooks.sh
```

## 3. Fastest path: demo with a mock API (no Docker)

```bash
pnpm demo
```

It prints a local URL (default `http://127.0.0.1:5180`). The banner "Demo data, mock API" is always shown. Stop with Ctrl+C.

## 4. Emulator stack with seeded data

```bash
make dev-up
make dev-ps
make seed
```

`make dev-up` starts Cosmos, Azurite and the Event Hubs emulator and waits for health. `make seed` generates deterministic synthetic data and loads it (idempotent).

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

## 7. Stop

```bash
make stack-down
make dev-down
```

## Hosted (Azure) deployment

Hosted demo steps are in [hosted-demo.md](../deploy/hosted-demo.md) and the requirements in [AZURE-DEPLOYMENT.md](../AZURE-DEPLOYMENT.md). They need operator approval and an approved subscription; this runbook does not repeat them. Cloud and region availability, feature maturity and authorization are separate gates, see [RESEARCH-AND-GATES.md](../RESEARCH-AND-GATES.md).
