# Claude Code — NeuroSphere
## Read order and authority
Read PRPs/PRP-MASTER-neurosphere.md first, then docs/PRD.md, PRP.md (binding preamble), docs/ARCHITECTURE.md and docs/RESEARCH-AND-GATES.md before implementation. These v1.2 documents are the build authority. Never treat git-history demo material, prior whitepapers or a previous chat claim as current build authority.
## Mission
Customer-hosted Azure Commercial/Government AI governance: telemetry/cost, versioned catalog/curated relationships, recommendations/evaluation, HITL, live map/session replay, governed copilot/report creation, MCP, deployment reuse and ATO evidence accelerator.
## Hard constraints
- Fabric, Synapse and Azure Databricks are deployment choices behind adapters; unsupported cloud/region/feature combinations are disabled, not globally banned. Never bridge Government data to Commercial to fill gaps.
- Synthetic sandbox is isolated; real ingestion is permitted only with authorized connectors/credentials and privacy policy. Never use production data in demos/tests by default.
- Authorization is enforced at every query/tool/export/push/action path. Privileged users have scoped permissions, never an unrestricted bypass.
- Buttons/chat/MCP use the same durable action executor. Confirm exact target/version/diff, recheck permission, honor approvals, audit and verify actual changes. No pretend model swaps that only edit catalog metadata.
- Do not claim FedRAMP authorization, ATO, compliance parity or zero future refactoring. Availability, feature maturity and authorization are separate gates.
- No arbitrary LLM-generated SQL/Cypher/JavaScript execution. Use bounded structured tools and sandboxed declarative charts.
- No secrets in files/prompts/logs; vault/managed identity in production. Do not read .env or credentials. No paid calls/cloud deployments without operator approval; live gates need `NS_LIVE_APPROVED=1` and are reported OPEN when they did not run.
- Preserve user changes; no force push, git reset --hard, unattended destructive commands or unauthorized modifications of shared enterprise resources.
## Work loop
One PRP per session. Read Git status and the master index status table, take the next PRP whose dependencies are shipped, and run it with `/prp:prp-execute PRPs/backlog/<file>.md`. Each work item edits only its owned files; shared files are sequenced, never parallel-edited. Use targeted tests, schema/adapter/authorization tests and lint; CI may not suppress failures (`|| true` fails the planning validator). Commit scoped changes only when gates pass; ask before push/deployment.
Model policy: Sonnet by default; Opus for PRP-01 contracts, PRP-06 identity/audit, PRP-12 threat model, PRP-17 action executor, PRP-22 MCP; Haiku for verify passes. Items marked `review: required` get one independent review pass.
## Completion rules
Document planning is not product implementation. A passing planner/reviewer or 'no changes to ship' is not completion. Every task needs changed files, executable tests and evidence. Provider-specific live tests/region authorization/DR require actual approved environments; report untested gates as open. Render Mermaid and produce media before claiming those assets exist.

## Project notes

<!-- Per-repo facts: stack, how to run it, deployment gotchas.
     Gate commands live in .claude/hooks/config.ps1, NOT here.
     The orchestration constitution (operating mode, verification, asking vs
     proceeding, WIP limit) is global, in ~/.claude/CLAUDE.md. Do not copy it
     here - duplicating it is how constitutions drift. -->

- Stack: Python 3.12 + uv + FastAPI + Pydantic v2; Node 24 + pnpm + React 19 + Vite + TS 6.0 + Fluent UI v9; Cosmos NoSQL, Event Hubs, Azure AI Search, Bicep + Helm 4. Pins: docs/adr/0002-stack-pins.md.
- Run locally: `uv sync && pnpm install && bash scripts/install-git-hooks.sh && docker compose up -d --wait` (emulators only, no paid calls). `python`, never `python3`.
- Gates: `powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full`
  (The `~/` spelling is deliberate: agents run this through **bash**, where
  `$env:USERPROFILE\...` expands `$env` to empty and exits 127 before any
  gate runs. Do not "correct" it back.)
- Planning alignment: `python scripts/validate_planning.py` (also runs under pytest).
- Secret guards: `.githooks/` via core.hooksPath locally; `.github/workflows/secret-scan.yml` in CI is the backstop.
