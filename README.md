# NeuroSphere

Customer-hosted AI ecosystem governance for Azure Commercial and Azure
Government: telemetry and cost ledger, versioned catalog with curated
relationships, evidence-backed recommendations and quality evaluation,
human-in-the-loop review, live ecosystem map and session replay, governed
copilot and report creation, MCP server/client, deployment reuse, and an ATO
evidence accelerator.

## Status

Planning baseline v1.2 plus the PRP-00 toolchain: a uv workspace (`packages/core`,
`packages/contracts/python`, `services/api`, `services/workers`), a pnpm
workspace (`frontend`, `packages/contracts/ts`) and the verification gates. Each
member is a stub with a smoke test; no product features, cloud adapters,
deployments or media exist yet. NeuroSphere is **not** FedRAMP authorized and
makes no ATO or Commercial/Government parity claim. This repository is private.

## Start here

| Read | For |
|---|---|
| `PRPs/PRP-MASTER-neurosphere.md` | Execution order, waves, model per PRP, phase gates |
| `docs/PRD.md` | Requirements NS-01 to NS-10 |
| `PRP.md` | Binding delivery contract, stack and boundaries, contract rules |
| `docs/ARCHITECTURE.md` | Decisions, trade-offs, five Mermaid source diagrams |
| `docs/RESEARCH-AND-GATES.md` | First-party evidence and the open gate register |
| `docs/adr/` and `docs/DECISIONS-LOG.md` | Why things are the way they are |
| `CLAUDE.md`, `AGENTS.md` | Coding-agent rules |

Historical demo material lives only in git history (`21ab22b`, `9fbf5f4`) and
is not build authority.

## Quick start

On the operator's Windows setup (Git Bash) the interpreter is `python`, not
`python3` (the latter hits the Microsoft Store shim). Prerequisites: uv, Node 24,
pnpm 11, Docker; pins in `docs/adr/0002-stack-pins.md`.

```bash
uv sync --frozen                      # Python 3.12 toolchain and all uv workspace members
pnpm install --frozen-lockfile        # Node 24 workspace
bash scripts/install-git-hooks.sh     # secret and PII guards, required
cp .env.example .env                  # placeholders only; never commit real values
docker compose up -d --wait           # Cosmos, Event Hubs and Azurite emulators only, no paid calls
```

Then run the gates. The fast gate is the per-item check; the full gate is the
definition of done:

```bash
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode fast
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```

The `~/` spelling is deliberate (it works from bash). The gates run the commands
of record in `.claude/hooks/config.ps1`; you can run the same pieces directly:

```bash
uv run ruff check .                   # Python lint
uv run pyright                        # Python types
uv run pytest -q                      # Python tests (nothing collected counts as failure)
pnpm lint && pnpm typecheck && pnpm test && pnpm build   # Node workspace
python scripts/validate_planning.py   # planning alignment (not a product test)
python scripts/render_mermaid.py      # render the five ARCHITECTURE.md diagrams to docs/diagrams/
```

`scripts/licenses_report.py --check` (dependency licence report) arrives with
PRP-00 item 4 and is not part of this quick start yet.

Known issue: when last tried, `docker compose up -d --wait` exited with the
Azurite container reported unhealthy (its `nc`-based healthcheck) while Cosmos
started healthy. The gates above do not depend on the emulators.

`make gates` wraps the full gate. Stop the emulators with `docker compose down -v`.

Run one PRP per session: `/prp:prp-execute PRPs/backlog/PRP-NN-<name>.md`.

## Layout

```
PRPs/                 master index, backlog/, active/, shipped/, templates/
docs/                 PRD, architecture, research gates, adr/, decisions log
packages/             contracts/ (JSON schemas + generated types), core/ (shared Python lib)   [PRP-00+]
services/             api/ (FastAPI), workers/                                                   [PRP-05+]
frontend/             Vite + React 19 + Fluent UI v9                                              [PRP-04+]
connectors/           sdk-python/, sdk-ts/, reference/                                           [PRP-09+]
infra/                compose/, bicep/, helm/, appservice/, observability/, dr/                  [PRP-08+]
sandbox/              synthetic data generator                                                    [PRP-03+]
tests/                contracts/, integration/, e2e/, load/, security/
scripts/              validate_planning.py, install-git-hooks.sh, gates/ (operator-approved)
.githooks/            pre-commit and pre-push secret guards (core.hooksPath)
.claude/hooks/        config.ps1 gate commands of record
```

## Scope and stack

Azure Commercial and Government from one codebase; Event Hubs ingestion with
explicit quarantine; Cosmos DB NoSQL operational catalog with bounded graph
queries; Fabric, Synapse or Azure Databricks analytics behind one adapter
contract; Entra ID with server-side scope; Azure AI Search behind an authorized
search contract; one durable action executor for buttons, chat, REST and MCP.
AKS enterprise or App Service smaller profile. Pins and licences: `docs/adr/0002-stack-pins.md`.

Synthetic sandbox is isolated and needs no credentials. Real ingestion requires
consented connectors. Live or paid gates run only with operator approval and
`NS_LIVE_APPROVED=1`; unrun gates are reported as open, never as green.

## Validation

`python scripts/validate_planning.py` checks document alignment, PRP coverage
and CI hygiene. It is not a product or production-readiness test.

Live or paid gates (real Azure, paid models, region or DR checks) never run by
default. They need explicit operator approval and `NS_LIVE_APPROVED=1`; a live
gate that did not run is reported **OPEN** in `docs/RESEARCH-AND-GATES.md`,
never as green.

## License

MIT (see `LICENSE`). Product name, branding and dependency licences need review
before distribution.
