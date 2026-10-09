---
name: prp-00-toolchain-workspaces-and-gates
status: active
review: required
created: 2026-10-08
model: sonnet
phase: 0
ns: NS-07, NS-08, NS-10
depends_on: none
wave: W0
absorbs: P0.3 remainder, G08, G10
---

# PRP-00: Toolchain, workspaces and gates

## Goal

Turn the repository from "hygiene only" into a buildable monorepo skeleton so every later PRP has real members to put code in and real gates that can fail. Repository hygiene is ALREADY DONE and is not part of this PRP: secret-scan hooks and CI (`.githooks/`, `.gitleaks.toml`, `.github/workflows/secret-scan.yml`, `codeql.yml`), `CODEOWNERS`, issue and PR templates, Dependabot, the kit hooks under `.claude/hooks/`, `docs/DECISIONS-LOG.md`, ADR-0002 and `scripts/validate_planning.py` all exist. What ships here is: a uv workspace with four stub Python members, a pnpm workspace with a frontend and a contracts-ts stub, the five architecture diagrams rendered and gated in CI (closing G10), a dependency and licence register covering every lockfile entry (extending G08, which is NARROWED), and a README and CONTRIBUTING that describe commands that actually work. The audience is every implementer of PRP-01 onward, who need `verify-gates -Mode fast` to mean something. It runs first (wave W0) because a green gate over an empty workspace is the failure mode this project must not ship.

Requirement text this PRP supports (NS-07, NS-08 and NS-10 are foundations here, fully delivered by later PRPs):

> Provision missing approved services with idempotent IaC after plan approval. (NS-07)

> Private networking/default-deny egress, approved endpoints, threat modeling, prompt-injection isolation, supply-chain scanning, secret rotation and incident response are foundational, not final-phase additions. (NS-08)

> Branded static documentation/Pages site, API/SDK references, ADRs, setup/migration/security/operations/DR runbooks, walkthroughs and synthetic sandbox. (NS-10)

PRP.md section 2 requires: "Versions are pinned in docs/adr/0002-stack-pins.md and the lockfiles; no floating latest packages in production."

## Acceptance criteria

- [ ] Item 1: Given a clean checkout, when `uv sync --frozen` runs, then it exits 0 with the four members resolved; a deliberately failing pytest and a deliberate ruff error each make `verify-gates.ps1 -Mode fast` exit non-zero, evidence captured, then both removed.
- [ ] Item 2: `pnpm install --frozen-lockfile && pnpm lint && pnpm typecheck && pnpm test` pass with no `|| true`; `$BuildCmd` is set and `'build'` is removed from `$OptionalGates` in `.claude/hooks/config.ps1`, so an empty build now fails the run.
- [ ] Item 3: Five SVGs exist at `docs/diagrams/NN-<name>.svg`, one per Mermaid block in `docs/ARCHITECTURE.md`; a syntax error injected into one diagram fails the new CI job (proved, then reverted); G10 row updated to CLOSED with evidence.
- [ ] Item 4: Every dependency in `uv.lock` and `pnpm-lock.yaml` appears in the ADR-0002 appendix and `docs/licenses.md` with name, version, licence and EOL/support note; a non-permissive licence (copyleft, non-commercial, EULA) fails CI unless on the script allowlist; the CI diff check fails when `docs/licenses.md` is stale.
- [ ] Item 5: A new-user walkthrough from README.md using only documented commands reaches a green `verify-gates -Mode fast`.
- [ ] PRP exit: `verify-gates.ps1 -Mode full` passes with lint, typecheck, tests AND build all executing (none skipped); `python scripts/validate_planning.py` reports no failure for this file; `git grep -n "|| true" -- .github/workflows` prints nothing.

## Clarifications (decided)

| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| 1 | Is repository hygiene (hooks, CI, secret scan, docs scaffolding) in scope? | redo; skip | Not in scope. Already done; this PRP must not edit `.githooks/`, `.gitleaks.toml`, `secret-scan.yml`, `codeql.yml`, `CODEOWNERS`, `dependabot.yml`. |
| 2 | Harness (D2) | kit only; kit + tasks.json | Orchestrated-PRP kit only. No `tasks.json`. |
| 3 | Stack pins (D5) | accept; adjust | ADR-0002 binds: Python 3.12 target (3.13 allowed by `requires-python`), uv 0.12, Node 24 LTS, pnpm 11.x, TypeScript 6.0.x not 7, ESLint 10 flat config only. |
| 4 | Model policy (D6) | Sonnet default; Opus everywhere | Sonnet implements; review is required (one pass, approve unless blocking). |
| 5 | Shared library (D11) | shared lib; duplicate | `packages/core` is a uv workspace member from day one; `services/workers` must never import `services/api`. |
| 6 | Does the root `pyproject.toml` get edited? | free edit; minimal | Item 1 edits only two spots: uncomment the `[tool.uv.workspace]` block (currently commented, members `packages/*`, `services/*`, `connectors/sdk-python`) and extend the pyright `include`. Nothing else in root. **Amended 2026-10-09 (user-approved):** Item 1 may also set pytest `testpaths` to include `packages` and `services` and add the workspace members to the root dev group, because otherwise member tests are never collected by the gate. |
| 7 | Workspace members glob versus the stub list | glob as written; explicit | `packages/contracts/python` is nested two levels so it is added to `members` explicitly. `connectors/sdk-python` has no `pyproject.toml` yet; if uv rejects the missing path, remove it from `members` and let PRP-09 re-add it. |
| 8 | Stub tests | none; one trivial test per member | One trivial import test per Python member and one Vitest smoke test, so a gate cannot pass by collecting nothing. Pytest exit code 5 (nothing collected) counts as a gate failure. |
| 9 | Mermaid renderer | mermaid-cli; custom | `@mermaid-js/mermaid-cli`, driven by `scripts/render_mermaid.py`. Chromium download in CI is acceptable; no outbound calls beyond package install. |
| 10 | Licence policy | allow all; allowlist | Permissive by default (MIT, BSD, Apache-2.0, ISC, PSF; MPL-2.0 dev-only). Copyleft, non-commercial (CC-BY-NC) and EULA entries fail unless on the script allowlist with a reason. The Cosmos and Event Hubs emulators are Microsoft EULA images, not lockfile dependencies; they are recorded in the ADR appendix as runtime tooling. |
| 11 | Live gates | per PRP | None in this PRP. Nothing here needs a cloud account (D7 does not apply). |

## Context manifest

### Files that matter

- `PRP.md` - binding preamble sections 1 to 3 (delivery contract, stack, contracts first).
- `docs/PRD.md` - NS-07, NS-08, NS-10 text quoted above.
- `docs/ARCHITECTURE.md` - source of the five Mermaid blocks to render (sections 1 to 5; section 6 has none).
- `docs/RESEARCH-AND-GATES.md` - G08 (NARROWED), G10 (OPEN, becomes CLOSED here), G11 (CLOSED).
- `docs/adr/0002-stack-pins.md` - version pins; item 4 appends an appendix section only.
- `pyproject.toml` (root) - ruff (line 100, py312, S rules), pyright, pytest markers `live` and `integration`, `[tool.uv] package = false`, and the commented `[tool.uv.workspace]` block with `members = ["packages/*", "services/*", "connectors/sdk-python"]` that item 1 must uncomment.
- `.claude/hooks/config.ps1` - sets `$LintAllCmd = "uv run ruff check ."`, `$TypecheckCmd = "uv run pyright"`, `$TestCmd = "uv run pytest -q"`, `$BuildCmd = ""` and the line `$OptionalGates = @('build')   # no build artefact until the frontend lands in PRP-04` that item 2 must flip. The runner treats an empty gate not listed in `$OptionalGates` as FAIL.
- `package.json`, `pnpm-workspace.yaml`, `.node-version`, `.python-version`, `uv.lock` (root, exist now) - extend, do not replace.
- `.github/workflows/ci.yml` - existing CI; items 3 and 4 each add one bounded piece.
- `scripts/validate_planning.py` - fails on `|| true` in any workflow and on credential-shaped tracked paths.
- `.env.example` - template only; never read `.env`.
- `docker-compose.yml`, `infra/compose/eventhubs.config.json` - not touched here (PRP-03).

### Patterns to match

No product code exists yet, so these are rules, not file references.

- Pydantic v2 models with `model_config = ConfigDict(extra="forbid")`.
- FastAPI routers per module under `services/api/neurosphere_api/<module>/router.py`.
- Async Azure SDK clients from `packages/core/neurosphere_core/clients`.
- Error taxonomy exceptions from `neurosphere_core.errors`.
- Tests beside packages plus cross-package suites in `tests/`.
- `pytest.mark.live` and `pytest.mark.integration` markers (declared in root `pyproject.toml`, run with `--strict-markers`).
- TypeScript strict with `@fluentui/react-components`; Vitest + Testing Library; Playwright under `frontend/tests/e2e`.

### Conventions

- ruff config in root `pyproject.toml`: line length 100, py312, `S` (bandit) rules on; pyright standard.
- Conventional commits; commit scoped changes only after review; ask before push or deployment.
- Owned-file discipline: an item edits only its declared paths; shared files are sequenced, never parallelized.
- Evidence lives under `docs/evidence/<gate>/`; live scripts under `scripts/gates/` refuse to run without `NS_LIVE_APPROVED=1`.
- Forward slashes in every gate command; Python is `python`, not `python3`; temp files go in `./temp/`.

### Gotchas

- Event Hubs has no DLQ: quarantine is an explicit container + replay CLI; checkpoints advance only after durable accept or quarantine. Metadata geo-DR copies neither payloads nor RBAC.
- `IdentityScope` is derived server-side; caller- or model-supplied `domain_id`/`customer_id` is ignored. Same scope object on REST, search, cache keys, exports, WebSocket, copilot tools, MCP.
- No LLM-generated SQL/Cypher/KQL/JS. Charts are a Vega-Lite subset (no `expr`, signals, external `url` data) rendered with `vega-interpreter` in a sandboxed iframe.
- Government is gated, not banned: disabled-with-reason from the capability matrix; separate endpoints (`login.microsoftonline.us`, `*.documents.azure.us`, `*.servicebus.usgovcloudapi.net`, `*.search.azure.us`). Never route Government data to Commercial.
- Fail closed: policy store outage returns 503. Privileged roles are scoped; no bypass.
- One action executor for button/chat/REST/MCP; same intent hash; permission and target version rechecked at execution; read-only connectors are advisory; no catalog-only pretend swaps.
- Costs: null/unknown never 0; estimated vs invoiced always distinct; projections cite price version. Provider billing freshness is not sub-10s.
- Catalog: raw events outside the graph; locks affect presented lineage not observations; traversals budgeted; ETag mismatch returns `stale_version`. Outbox is the projection baseline, not emulator change feed.
- Emulators: Event Hubs emulator lacks Entra, so producer identity is enforced at the ingest edge; Cosmos vNext emulator has no RU accounting, no sprocs/triggers/UDF, no range/composite/spatial indexes, so G03 emulator evidence is "bounded feasibility" only.
- `scripts/gates/*` refuse without `NS_LIVE_APPROVED=1`; missing live evidence is an open gate, never a skipped green test. No paid model calls in CI.
- No FedRAMP/ATO/parity claims. Availability, GA and authorization are separate matrix columns.
- Secrets via vault references; dev issuer only when `NS_ENV=local`; never read `.env`. Pseudonymize people; prompt/response bodies off by default; redact before archive and before any external transmission (judges, connectors).
- Hidden navigation is not authorization; the API must deny.
- Versions: Python 3.12, Node 24, TypeScript 6.0.x (not 7), Helm 4, MkDocs Material 9.7 (EOL 2026-11-05, evaluate Zensical), sigma 4 + graphology (never @cosmograph, CC-BY-NC), MCP SDK 2.x (spec 2026-07-28). See docs/adr/0002-stack-pins.md.
- CI contains no `|| true`; `scripts/validate_planning.py` fails if it does. Python is `python`, not `python3`.
- PRP-00 specific: a gate that does nothing exits 0 and looks like PASS. After flipping `$OptionalGates`, run `verify-gates -Mode full` once with a deliberately empty `$BuildCmd` to prove it now fails, then restore.
- PRP-00 specific: `uv.lock` and `pnpm-lock.yaml` are regenerated only by their owning item (items 1 and 2). Items 4 and 5 read them and never rewrite them.
- PRP-00 specific: `.claude/hooks/config.ps1` is dot-sourced by the runner. Keep it to variable assignments: no `Set-StrictMode`, no side effects. A multi-step build must be a script run as a child process, not a chained one-liner.
- PRP-00 specific: pyright `include` must list the new member dirs or the typecheck gate silently covers nothing new.
- PRP-00 specific: mermaid-cli needs headless Chromium; on CI pass the no-sandbox puppeteer config deliberately and document it. Do not weaken the job with `continue-on-error`.
- PRP-00 specific: `docs/ARCHITECTURE.md` must keep exactly five Mermaid blocks; `scripts/validate_planning.py` asserts it. Do not edit diagrams to make rendering pass without noting the change.

### External references

- uv workspaces: https://docs.astral.sh/uv/concepts/projects/workspaces/ (not yet observed; verify at implementation).
- ADR-0002 sources, observed 2026-10-08: Python https://devguide.python.org/versions/, uv https://pypi.org/project/uv/, Node https://github.com/nodejs/Release, pnpm https://www.npmjs.com/package/pnpm, Helm EOL https://helm.sh/blog/helm-v3-end-of-life/, MkDocs Material https://squidfunk.github.io/mkdocs-material/ (EOL scheduled 2026-11-05).
- TypeScript 7 incompatible with typescript-eslint 8.71: recorded in `docs/RESEARCH-AND-GATES.md` (retrieved 2026-10-08); pin TS 6.0.x.
- Vega CSP note, relevant to the vega-interpreter dependency review: https://vega.github.io/vega/usage/#csp (2026-10-08).
- mermaid-cli: https://github.com/mermaid-js/mermaid-cli (tool named by the decomposition; record version and Chromium requirement in the ADR-0002 appendix when pinned).

## Implementation blueprint

### Item 1 — python-workspace  [P]
- Deliverable: uv workspace members `packages/core`, `packages/contracts/python`, `services/api`, `services/workers`, each with a stub `pyproject.toml` (name, version `0.0.0`, `requires-python = ">=3.12"`, pins from ADR-0002) and an `__init__.py`; root `[tool.uv.workspace]` uncommented; pyright include extended; `uv.lock` regenerated; one trivial import test per member.
- Owned files (may edit): `packages/core/pyproject.toml`, `packages/core/neurosphere_core/__init__.py`, `packages/contracts/python/pyproject.toml`, `services/api/pyproject.toml`, `services/api/neurosphere_api/__init__.py`, `services/workers/pyproject.toml`, `services/workers/neurosphere_workers/__init__.py`, root `pyproject.toml` (workspace block and pyright include lines only), `uv.lock`, `packages/core/tests/test_import.py`, `services/api/tests/test_import.py`, `services/workers/tests/test_import.py`.
- Must NOT touch: anything under `frontend/`, `packages/contracts/ts/`, `pnpm-lock.yaml`, `tsconfig.base.json` (item 2); `docs/diagrams/`, `scripts/render_mermaid.py` (item 3); `docs/adr/`, `docs/licenses.md`, `scripts/licenses_report.py` (item 4); `README.md`, `CONTRIBUTING.md` (item 5); `.claude/hooks/config.ps1`; `docker-compose.yml`; ruff, pytest and uv settings in root `pyproject.toml`; `docs/RESEARCH-AND-GATES.md`.
- Depends on: none
- Acceptance criteria:
  - `uv sync --frozen` exits 0 and lists all four members.
  - `uv run pytest -q`, `uv run pyright` and `uv run ruff check .` pass with the three stub tests collected.
  - Completion note records proof that a deliberately failing test and a deliberate ruff error each make `verify-gates.ps1 -Mode fast` exit non-zero (both removed afterwards).
  - Import names are `neurosphere_core`, `neurosphere_api`, `neurosphere_workers`; workers declare no dependency on api.
- Pattern references: root `pyproject.toml` ruff and pytest sections; ADR-0002 backend table.
- Tests to write: `packages/core/tests/test_import.py`, `services/api/tests/test_import.py`, `services/workers/tests/test_import.py`.

### Item 2 — node-workspace  [P]
- Deliverable: `frontend/package.json` stub (Vite, React 19, TypeScript 6.0.x, Fluent UI v9, Vitest, ESLint flat config, Prettier) with scripts `lint`, `typecheck`, `test`, `build`; `packages/contracts/ts/package.json` stub; `tsconfig.base.json`; `pnpm-lock.yaml`; `$BuildCmd` set and `'build'` dropped from `$OptionalGates` in `.claude/hooks/config.ps1`.
- Owned files (may edit): `frontend/package.json`, `frontend/tsconfig.json`, `frontend/eslint.config.js`, `frontend/.prettierrc`, `frontend/src/smoke.test.ts`, `packages/contracts/ts/package.json`, `tsconfig.base.json`, `pnpm-lock.yaml`, `.claude/hooks/config.ps1` (the `$BuildCmd` and `$OptionalGates` lines only; listed here because the decomposition makes item 2 flip them).
- Must NOT touch: any Python member or `uv.lock` (item 1); `frontend/src/app/`, `frontend/src/design-system/`, `frontend/vite.config.ts`, `frontend/index.html` (PRP-04); `docs/diagrams/` (item 3); `docs/adr/`, `docs/licenses.md` (item 4); `README.md`, `CONTRIBUTING.md` (item 5); root `pyproject.toml`; root `package.json` and `pnpm-workspace.yaml` unless a member must be registered (record any such edit in the completion note); every other line of `.claude/hooks/config.ps1`.
- Depends on: none
- Acceptance criteria:
  - `pnpm install --frozen-lockfile && pnpm lint && pnpm typecheck && pnpm test` pass; no `|| true` in scripts or workflows.
  - `verify-gates.ps1 -Mode full` runs the build gate (not SKIP); with `$BuildCmd` emptied it fails (proved, then restored).
  - `tsc` resolves TypeScript 6.0.x; ESLint uses flat config only.
  - `@cosmograph/*` appears nowhere in `pnpm-lock.yaml` (CC-BY-NC).
- Pattern references: ADR-0002 frontend table; `.claude/hooks/config.ps1` header comments on child-process gates.
- Tests to write: `frontend/src/smoke.test.ts` (Vitest; asserts the runner executes).

### Item 3 — mermaid-render-gate  [P]
- Deliverable: `scripts/render_mermaid.py` extracts the five Mermaid blocks from `docs/ARCHITECTURE.md` and renders them to `docs/diagrams/NN-<name>.svg` through `@mermaid-js/mermaid-cli`; a new CI job fails on any parser error; G10 closed.
- Owned files (may edit): `docs/diagrams/`, `scripts/render_mermaid.py`, `.github/workflows/ci.yml` (one new job only), `docs/RESEARCH-AND-GATES.md` (G10 row only), `tests/test_render_mermaid.py`.
- Must NOT touch: `docs/ARCHITECTURE.md` content; `package.json` dependency blocks and lockfiles owned by items 1 and 2 (invoke mermaid-cli through a pinned `pnpm dlx`, or record a root dev-dependency edit in the completion note); other jobs and steps in `ci.yml`, including the planning-job step item 4 adds; every other row of `docs/RESEARCH-AND-GATES.md`.
- Depends on: none
- Acceptance criteria:
  - Five SVGs committed, numbered `01-` to `05-` in section order of `docs/ARCHITECTURE.md`.
  - A syntax error injected into one diagram makes the CI job fail (proved on a branch, then reverted).
  - The script exits non-zero if the block count is not 5 and names the failing block.
  - G10 row reads CLOSED with date and SVG path; nothing is claimed rendered that was not.
- Pattern references: `scripts/validate_planning.py` (script style, exit codes).
- Tests to write: `tests/test_render_mermaid.py` (block extraction and count; needs no Chromium).

### Item 4 — version-and-license-register
- Deliverable: ADR-0002 appendix covering every dependency in `uv.lock` and `pnpm-lock.yaml`; `scripts/licenses_report.py` generating `docs/licenses.md` from the lockfiles with an allowlist; a CI step in the planning job that regenerates and diffs.
- Owned files (may edit): `docs/adr/0002-stack-pins.md` (appendix section only), `docs/licenses.md`, `scripts/licenses_report.py`, `.github/workflows/ci.yml` (one step in the planning job), `tests/test_licenses_report.py`, `tests/fixtures/licenses/`.
- Must NOT touch: ADR-0002 decision tables above the appendix; item 3's CI job; lockfiles; `docs/RESEARCH-AND-GATES.md` (G08 stays NARROWED; note progress in the completion note); `pyproject.toml`; `package.json`.
- Depends on: items 1, 2 (lockfiles final); sequence after item 3 merges because both edit `ci.yml`.
- Acceptance criteria:
  - Every lockfile dependency appears with licence; an unresolvable licence is reported `UNKNOWN` and fails CI, never defaulted to permissive.
  - A non-permissive licence (copyleft, non-commercial, EULA) fails CI unless on the allowlist with a reason.
  - `hypothesis` (MPL-2.0) appears as dev-only; a fixture lockfile containing `@cosmograph/*` fails the check.
  - Re-running with no lockfile change yields no diff.
- Pattern references: ADR-0002 table columns (component, pin, licence, source, note).
- Tests to write: `tests/test_licenses_report.py` using fixture lockfiles under `tests/fixtures/licenses/`.

### Item 5 — contributing-and-readme-refresh
- Deliverable: README quick start and CONTRIBUTING updated to the real members and commands (`uv sync --frozen`, `pnpm install --frozen-lockfile`, gate commands, running the planning validator, how live gates are approved).
- Owned files (may edit): `CONTRIBUTING.md`, `README.md`.
- Must NOT touch: any file owned by items 1 to 4; `CLAUDE.md`, `AGENTS.md`, `PRP.md`, `docs/PRD.md`; root config files.
- Depends on: items 1, 2
- Acceptance criteria:
  - A walkthrough executed from README.md alone, using only documented commands, ends in a green `verify-gates.ps1 -Mode fast`.
  - No claim of FedRAMP, ATO or parity; the deleted Artemis or zero-move demo is not described as current.
  - README states that Python is `python`, not `python3`, on the operator's Windows setup.
- Pattern references: existing `README.md` structure.
- Tests to write: none (documentation); covered by `python scripts/validate_planning.py`, which checks the Mermaid-count claim.

## Validation gates

```
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode fast    # per item
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full    # before merge
python scripts/validate_planning.py
```

Feature-specific commands:

```
uv sync --frozen
uv run pytest -q
uv run pyright
uv run ruff check .
pnpm install --frozen-lockfile
pnpm lint
pnpm typecheck
pnpm test
python scripts/render_mermaid.py
python scripts/licenses_report.py --check
git grep -n "|| true" -- .github/workflows
```

The last command must print nothing. No command here needs `NS_LIVE_APPROVED=1`.

## Live and open gates

| Gate | Effect of this PRP |
|---|---|
| G08 dependency and licence versions | Stays NARROWED. Item 4 extends the register to every lockfile dependency; MCP authorization-spec tests belong to PRP-22. |
| G10 Mermaid parser and render | Closed by item 3 with five committed SVGs and a CI job that fails on parser error. |
| G11 stack pins | Already CLOSED; re-verified when item 4 touches ADR-0002. |

If a live item did not run, record it OPEN in the completion note and in docs/RESEARCH-AND-GATES.md; never report it as a skipped green test.

## NOT building

- Repository hygiene already done: hooks, secret scanning, CodeQL, CODEOWNERS, templates, Dependabot.
- Any product code, schemas or tests beyond stubs (PRP-01 and later).
- Frontend app shell, design system, routing, auth (PRP-04).
- Dockerfiles, release workflow, container publishing (PRP-13).
- Supply-chain scanning gates (SBOM, Trivy, pip-audit as blocking) beyond the licence check (PRP-12).
- Docs site build or the MkDocs Material versus Zensical choice (PRP-25).
- Any cloud resource, paid call or deployment.

## Definition of Ready check

- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [x] All clarification questions are decided, not guessed

## Completion note (filled at ship)

- Date:
- Merged commits:
- Deviations from blueprint and why:
- Descoped items:
- Evidence paths (failing-gate proofs, CI run links):
- Open gates and follow-ups:
