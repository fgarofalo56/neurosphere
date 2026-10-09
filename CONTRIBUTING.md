# Contributing to NeuroSphere

## Setup (once per clone)

```bash
uv sync --frozen                 # Python 3.12 toolchain from .python-version; uv workspace members, creates .venv
pnpm install --frozen-lockfile   # Node 24 from .node-version; pnpm workspace (frontend, packages/contracts/ts)
bash scripts/install-git-hooks.sh   # secret/PII guards via core.hooksPath; required
cp .env.example .env             # placeholders only; never commit .env
docker compose up -d --wait      # Cosmos, Event Hubs, Azurite emulators only; no paid calls
```

`python` not `python3` on the operator's Windows setup. Run PowerShell via a
`.ps1` file, not inline. Lockfiles (`uv.lock`, `pnpm-lock.yaml`) are committed;
change dependencies deliberately and commit the lockfile with them.

## Definition of done

Nothing is done unless this passed **in the session that claims it**, with raw
output shown. `-Mode fast` is the per-item check; `-Mode full` is the PRP exit:

```
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode fast
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```

The gate commands live in `.claude/hooks/config.ps1` and run lint (ruff,
`pnpm lint`), typecheck (pyright, `pnpm typecheck`), tests (pytest, `pnpm test`)
and build (`pnpm build`). Equivalent direct commands:

```
uv run ruff check . && uv run pyright && uv run pytest -q
pnpm lint && pnpm typecheck && pnpm test && pnpm build
python scripts/validate_planning.py     # planning alignment; also runs under pytest
python scripts/render_mermaid.py        # renders the five ARCHITECTURE.md diagrams
```

`scripts/licenses_report.py --check` arrives with PRP-00 item 4; until it lands
it is not a gate. CI runs the same gates plus secret scanning, CodeQL and
dependency audits. CI may never contain `|| true`;
`scripts/validate_planning.py` fails if it does.

Live Azure or paid-model gates run only with explicit operator approval and
`NS_LIVE_APPROVED=1` (set it for that run only; never commit it). A live gate that has not run is reported as **open** in
`docs/RESEARCH-AND-GATES.md`, never as a skipped green test.

## Workflow

1. Work comes from a PRP in `PRPs/backlog/`. Order and model choice are fixed by
   `PRPs/PRP-MASTER-neurosphere.md`. Run one PRP per session with
   `/prp:prp-execute PRPs/backlog/<file>.md`.
2. Each work item edits only its declared owned files. Shared-file conflicts
   are sequenced, never parallelised.
3. Branch from `main`; conventional commits (`feat(catalog): ...`,
   `chore(repo): ...`, `docs(prp): ...`). Reference the PRP id and item.
4. Open a PR using the template. Paste gate output. Link evidence paths.
5. Pushing, deploying and anything that costs money require operator approval.

## Review

Items marked `review: required` in their PRP get one independent review pass
(never the author). Approve unless a blocking defect exists: wrong behaviour,
security, data loss, broken contract. Everything else is a follow-up issue.

## Documentation

- Architecture decisions: `docs/adr/` (MADR). Add an ADR when a choice is hard
  to reverse.
- Gate evidence: `docs/evidence/<gate>/` plus a `gate-evidence` issue.
- Never claim FedRAMP authorization, ATO, or Commercial/Government parity.
  Availability, feature GA and authorization are separate facts.
