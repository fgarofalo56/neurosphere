# Product validation rubric (2026-11-06)

Purpose: find out what a NeuroSphere operator can actually do today against `docs/PRD.md` NS-01..NS-10,
independent of whether a PRP is marked shipped. A green test suite or a merged PR is not evidence that
a capability works for a user.

## Classification (one per capability)

| Class | Meaning |
|---|---|
| WORKS | A user can do it end to end through the UI or a documented API against the real backend path (real store, real ingest or a documented source), AND you ran it or ran a test that exercises the real path (not a mock) and saw it work. |
| PARTIAL | Part of the path is real and part is missing or unwired. Say exactly which part. |
| MOCK-ONLY | The UI renders, but only against `frontend/tests/mock-api/` or in-memory seed data; the real API route is absent, returns 503/empty, or no real data can reach it. |
| MISSING | Specified in the PRD or a PRP and not present in code. |

A claim of WORKS needs evidence: a command and its output, or a test name you ran and its result. Static
reading alone can justify PARTIAL, MOCK-ONLY or MISSING, never WORKS.

## For every capability also record: "Operator-configurable?"

How does an administrator turn this on or change it today?
`UI` / `API only` / `file or env only` / `IaC only` / `not configurable`. Name the file, env var or route.
The product owner's central complaint is that there is no admin console to wire the system up, so be exact.

## Trace method

For each capability follow the whole chain and cite `path:line` at each hop:
UI route (`frontend/src/app/route-manifest.json`, `frontend/src/features/<x>/`) -> API client call ->
backend router (`services/api/neurosphere_api/<x>/router.py`) -> store or service (`packages/core/...`) ->
where real data comes from (ingest, connector, worker role, seed script). Then check whether the mock API
(`frontend/tests/mock-api/server.ts`, `features/*.ts`) returns shapes or data the real API does not.

## Rules

- Read-only on source: do NOT edit any file except your own report under `docs/validation/`.
- Never read `.env` or `.env.*` (except `.env.example` is allowed but may be denied by a hook: do not retry).
- No Azure calls, no paid calls, no `az`, no `docker compose` (the compose project is shared; the
  orchestrator runs the stack). Use `127.0.0.1`, never `localhost`.
- Run only targeted tests: `uv run pytest <path> -q` or `pnpm --filter frontend exec vitest run <path>`.
  Prefer tests under `tests/integration` or `services/api/tests` that hit real routers over in-memory
  stores, but say which store the test used (in-memory twin vs Cosmos emulator).
- Python is `python`, never `python3`. Use `uv run` for repo code.
- Do not soften findings. "Mostly works" is not a class. If you could not verify, say UNVERIFIED and why.

## Report format (your own file, ~400-700 lines max)

1. A summary table: capability | PRD ref | PRP(s) and tracker status | class | operator-configurable? | evidence
2. Per-capability notes: the chain with `path:line`, what you ran, what is missing.
3. A "What an operator cannot do today" list for your area, in plain words.
4. Contradictions between PRP "shipped" status and reality.
5. Open questions you could not answer.
