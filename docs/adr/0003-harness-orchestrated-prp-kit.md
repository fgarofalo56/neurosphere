# ADR-0003: Development harness is the orchestrated-PRP kit

- Status: accepted
- Date: 2026-10-08
- Deciders: Frank Garofalo

## Context

PRP.md v1.1 §5 described a bespoke long-running harness: a `docs/build/tasks.json`
manifest, a `PROGRESS.md` ledger, and a run loop that locks a task, implements,
tests and stops. The operator's other repositories already use the
orchestrated-PRP kit (`PRPs/{backlog,active,shipped,templates}`, a per-repo gate
config in `.claude/hooks/config.ps1`, the global `verify-gates.ps1` runner, and
the `/prp:prp-create` / `/prp:prp-execute` commands with worktree-isolated
implementers, a WIP limit of 4, and optional independent review). Two harness
conventions in one repo would drift.

## Decision

Use the orchestrated-PRP kit only.

- One PRP per epic in `PRPs/backlog/`, written against
  `PRPs/templates/prp-template.md`, with owned-file declarations per work item.
- `PRPs/PRP-MASTER-neurosphere.md` fixes execution order, parallel waves, model
  assignment and phase gates. It is the file a fresh session reads first.
- Gates are the commands in `.claude/hooks/config.ps1`; an empty required gate
  fails, by design.
- Progress is the PRP file's `status` and its completion note, plus git history.
  No `tasks.json`, no `PROGRESS.md`.
- Model policy: Sonnet by default; Opus for contracts/schemas, identity and
  audit, the action executor and MCP security; Haiku for verify passes.

## Consequences

- PRP.md §4–§6 become a pointer to the master index; §1–§3 remain the binding
  preamble every split PRP inherits.
- `CLAUDE.md` and `AGENTS.md` describe the kit loop, not the tasks.json loop.
- `scripts/validate_planning.py` enforces that every PRP in the master index
  exists and that every NS requirement maps to at least one PRP.
- A session runs one PRP. Chaining PRPs in one session is a cost bug, not rigour.
