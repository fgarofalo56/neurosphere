# Parallel build reference (shared by PRP-11, 15, 18, 21, 23 and PRP-36 to PRP-137)

Every PRP in waves W11 to W39 links here instead of repeating this. Read it once
at the start of a session. The wave plan, merge order and kickoff prompts are in
`PRPs/EXECUTION-PLAN.md`.

## 1. Session start

1. `git fetch origin && git switch -c <branch from the PRP frontmatter> origin/main`
   (agent worktrees branch from `main`; if the PRP says it builds on an
   integration branch, merge that first).
2. Read the PRP, then only the files its "Files to read first" list names.
3. Do not read `.env*`, `secrets/**` or credentials. `.env.example` cannot be
   edited by an agent: list every new `NS_*` variable in the PRP completion note
   under "Env vars for the operator" and in the runbook the PRP names.
4. No paid call, cloud deployment or live gate without `NS_LIVE_APPROVED=1` and
   operator approval in the session. A live item that did not run is written
   OPEN in the completion note.

## 2. File ownership tiers

A PRP edits only what its `## Ownership` block lists. Three tiers apply to
shared files.

**Tier 1, single owner per wave.** Editing existing logic in these files is
allowed only for the PRP that `PRPs/EXECUTION-PLAN.md` names as the wave owner.
Any other PRP that needs a change there declares a final item marked
`[serial-after: PRP-NN]` and does it only after that PRP has merged and the
branch is rebased.

- Contracts: `packages/contracts/schemas/**` and its generated Python and
  TypeScript output (`python packages/contracts/scripts/generate.py`).
- Stores: `packages/core/neurosphere_core/stores/containers.py`,
  `infra/compose/cosmos-containers.json`, `infra/demo/modules/cosmos-data.bicep`,
  `infra/bicep/modules/cosmos.bicep`.
- API composition bodies: `services/api/neurosphere_api/runtime/builders/*.py`
  (existing modules), `runtime/compose.py`, `runtime/planes.py`, `main.py`,
  `app.py`, `authz/dependencies.py`.
- Worker composition bodies:
  `services/workers/neurosphere_workers/runtime/factories.py` (existing builder
  functions).
- Deploy and build: `docker-compose.yml`, `Makefile`, `infra/helm/**`,
  `infra/demo/main.bicep`, `infra/appservice/main.bicep`,
  `infra/bicep/modules/**`, every `Dockerfile`, `.grype.yaml`,
  `.github/workflows/*.yml`, `pyproject.toml`, `uv.lock`, `pnpm-lock.yaml`,
  `package.json`, `docs/licenses.md`, `docs/adr/0002-stack-pins.md`.
- Frontend shell: `frontend/src/app/{Shell,Providers,App,domain}.tsx`,
  `frontend/tests/mock-api/server.ts`.

**Tier 2, additive lines by anyone.** A PRP may add new lines (never change or
reorder existing ones) to these registries. Conflicts are one-line and are
resolved at rebase by keeping both sides.

- `services/api/neurosphere_api/routers.py` (`REGISTERED`)
- `services/api/neurosphere_api/runtime/builders/__init__.py`
  (`default_builders`), `runtime/status.py` (`REQUIRED_COMPONENTS`,
  `OPTIONAL_COMPONENTS`), `runtime/settings.py` (new fields only)
- `services/api/neurosphere_api/authz/routes.py` (route allowlists; the app
  refuses to boot on an undeclared route)
- `packages/core/neurosphere_core/auth/scope/permissions.py` (new permissions)
- `services/workers/neurosphere_workers/runtime/roles.py` (`ROLE_NAMES`),
  the `BUILDERS` table at the end of `runtime/factories.py` (new builder
  functions go in a new module and are imported there), worker
  `runtime/settings.py` (new fields only)
- `frontend/src/app/appRoutes.ts`, `frontend/src/app/route-manifest.json`,
  `frontend/src/app/workspaceNav.ts`,
  `frontend/tests/mock-api/features/index.ts`,
  `frontend/tests/e2e/a11y/route-samples.ts`,
  `frontend/tests/real-stack/routes.spec.ts`
- Route and permission inventories that must list every new route:
  `services/api/tests/authz/test_route_inventory.py`,
  `services/api/tests/authz/test_startup_route_check.py`,
  `services/api/tests/runtime_routes/manifest_calls.py`,
  `tests/integration/real_stack/test_manifest_routes.py`,
  `packages/core/tests/auth/scope/test_roles.py`,
  `tests/security/authz/test_privileged_roles.py`
- `mkdocs.yml` (nav entries)

**Tier 3, generated or integrator-owned. Never commit these from a PRP branch
before the merge step.** The session regenerates them as its last commit, after
rebasing on the current `main`, immediately before merge.

| File | Regenerate with |
|---|---|
| `services/api/openapi.json` | `uv run python -m neurosphere_api.openapi_export` (drift test `services/api/tests/test_openapi_drift.py`) |
| `docs/reference/**` and `SOURCE_STAMP.json` | `uv run python docs/reference/generate.py` |
| `PRPs/PRP-MASTER-neurosphere.md` status table | `python scripts/prp_status.py --write` |
| `PRPs/INDEX.md` | `python -S -E ~/.claude/kits/orchestrated-prp/prp_index.py build` (CI checks membership, section, priority, order and review through `validate_planning.py`) |
| `PRPs/EXECUTION-PLAN.md` | `python scripts/prp_execution_plan.py --write` (after a PRP file moves or its frontmatter or Ownership block changes; CI runs `--check`) |
| `changelog.d/<PRP file stem>.md` | written by the PRP in its close-out commit; assembled into `CHANGELOG.md` only at release (`scripts/changelog_assemble.py`). Never edit `CHANGELOG.md` in a PRP branch |
| `docs/RESEARCH-AND-GATES.md` | hand-edited; only the row the PRP names, in the close-out commit only |
| Visual baselines | `pnpm --filter @neurosphere/frontend visual:update` (Docker only; baselines are Linux) |

## 3. Commands that define done

Run from the repo root through bash. `python`, never `python3`.

```bash
# Python: lint, format, types (repo-wide, as CI does), targeted tests
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q <the suites the PRP names, all in ONE invocation>

# Frontend
pnpm --filter @neurosphere/frontend lint
pnpm --filter @neurosphere/frontend typecheck
pnpm --filter @neurosphere/frontend test
pnpm --filter @neurosphere/frontend format
pnpm --filter @neurosphere/frontend test:e2e        # Playwright on the mock API

# Contracts, OpenAPI, planning
python packages/contracts/scripts/generate.py --check
uv run pytest -q services/api/tests/test_openapi_drift.py tests/docs/test_reference_coverage.py
python scripts/validate_planning.py
python scripts/prp_status.py --check

# Full local gate (lint, typecheck, tests, build)
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```

There is no `.claude/hooks/run-tests.ps1` in this repo. The `~/` spelling of the
gate path is deliberate (bash expands it; `$env:USERPROFILE` does not survive).

Done for a PRP means: every acceptance criterion has a named passing test or a
filed evidence file; the commands above pass for what the PRP touched; the PR is
open and CI is green including the non-required `contracts`, `frontend-e2e`,
`helm` and `security` jobs; live items are evidenced or written OPEN.

## 4. Known traps

- Suites marked `integration` are skipped by the CI `python` job. A suite that
  must run in CI is either unmarked or runs in a compose job. Before pushing,
  find cross-tests by grepping tests for the module and file names you changed,
  not only the suites you added.
- Same-named test directories with `__init__.py` shadow each other in one
  pytest session: give a new test directory a unique name and run touched
  suites together.
- Emulators: use `127.0.0.1`, not `localhost`. The compose project name is
  shared across worktrees, so only one session at a time may run
  `docker compose` or `make stack-up`; the plan marks which PRP in a wave holds
  the stack. Playwright needs unique `NS_E2E_APP_PORT` and `NS_MOCK_API_PORT`
  per worktree.
- A new workspace package must be copied into all five `uv --frozen`
  Dockerfiles, and every new dependency needs a licence row
  (`scripts/licenses_report.py`) and an ADR-0002 pin.
- CodeQL fails PRs on: logging a name that looks like a secret, hostname
  substring checks (`endswith("vault.azure.net")` without a leading dot),
  PEP 695 generics in nested functions.
- A contract model used as `response_model` renames `openapi.json` components.
  Tests that take `next(iter(set))` flake on hash seed.
- Fluent dialog tests: query with `hidden: true` (Tabster sets `aria-hidden`).
- Git Bash mangles absolute paths: prefix `MSYS_NO_PATHCONV=1` for `az` and for
  `uv run` commands that take `/subscriptions/...` arguments, but not for
  `pnpm`. Commit messages go through `git commit -F temp/msg.txt`.
- `main` requires an up-to-date branch and has no merge queue. Merges within a
  wave are serial: rebase, regenerate Tier 3 files, wait for CI, merge.
- `prp_index check` fails if two PRPs are in `PRPs/active/` unless each has
  `allow_parallel: true`. Every PRP in this plan sets it.

## 5. PRP file rules (enforced by `scripts/validate_planning.py` and `prp_index.py check`)

- File name `PRP-NN-kebab-slug.md`, two-digit id; `name` equals the file stem.
- Frontmatter keys: `name`, `status`, `priority` (P0 to P3), `order` (integer),
  `review` (`required` or `none`), `created` (YYYY-MM-DD), `model`,
  `orchestrator_model`, `implementer_model` (`sonnet`, `opus`, `haiku`),
  `phase`, `ns`, `depends_on` (inline list of full file stems), `wave`,
  `branch`, `allow_parallel: true`, optional `issues: [ints]`.
- Body must contain `## Implementation blueprint`, the text `Owned files` and a
  `verify-gates.ps1` gate command, with balanced code fences.
- Every PRP id mentioned in `PRPs/PRP-MASTER-neurosphere.md` must have a file.

## 6. Close-out

1. Rebase on `main`; regenerate Tier 3 files; run section 3.
2. Write the changelog fragment `changelog.d/<PRP file stem>.md`; never edit
   `CHANGELOG.md`. Fill `## Completion note`: date, PR, deviations, descoped items,
   OPEN gates, "Env vars for the operator", follow-up issue numbers.
3. `/prp:prp-close` moves the file to `PRPs/shipped/` and sets `shipped:`.
4. Close the issues listed in the PRP's `issues:` frontmatter that the PR
   fixed; leave operator-only ones open.
5. Product check before closing: can an operator configure and use the
   capability without editing files or calling raw APIs? If not, say so in the
   completion note and file the gap.
