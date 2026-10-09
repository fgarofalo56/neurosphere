# NeuroSphere

Customer-hosted AI ecosystem governance for Azure Commercial and Azure
Government: telemetry and cost ledger, versioned catalog with curated
relationships, evidence-backed recommendations and quality evaluation,
human-in-the-loop review, live ecosystem map and session replay, governed
copilot and report creation, MCP server/client, deployment reuse, and an ATO
evidence accelerator.

## Status

Planning baseline v1.1 with repository hygiene in place. No product services,
cloud adapters, deployments or media exist yet. NeuroSphere is **not** FedRAMP
authorized and makes no ATO or Commercial/Government parity claim. This
repository is private.

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

```bash
uv sync                               # Python 3.12 toolchain
pnpm install                          # Node 24 workspace (members arrive with PRP-04)
bash scripts/install-git-hooks.sh     # secret and PII guards, required
cp .env.example .env                  # placeholders only
docker compose up -d --wait           # Cosmos, Event Hubs and Azurite emulators
make gates                            # the definition of done
```

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

## License

MIT (see `LICENSE`). Product name, branding and dependency licences need review
before distribution.
