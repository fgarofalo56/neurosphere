---
name: PRP-52-ci-and-infrastructure-hardening
status: shipped
shipped: 2026-11-16
pr: 302
priority: P2
order: 39
review: required
created: 2026-11-14
model: sonnet
orchestrator_model: sonnet
implementer_model: sonnet
phase: 6
ns: NS-08, NS-09
depends_on: []
wave: W16
branch: prp-52-ci-infra-hardening
allow_parallel: true
issues: [245, 66, 67, 68, 69, 171, 215]
---

# PRP-52: CI and infrastructure hardening

## Goal
Pay down the CI, supply-chain and infrastructure debt that earlier PRPs filed as non-blocking follow-ups, and unblock the two open Dependabot pull requests. Concretely: harden `security.yml` (#66), finish the network baseline (#67), render the DFD diagrams in CI (#68), add an APIM rate limit for the UI-to-API ingress (#69 Bicep part), harden the egress-compose job and fold its copied skip helper into one (#215), remove `sqlite-libs` from the runtime images instead of ignoring its CVEs (#171), make the licence register survive dependency bumps so PRs #197 and #198 can pass, fail CI when a licence row was carried forward (PRP-00 leftover), and require `NS_CLOUD` in the Helm chart (PRP-13 leftover). It is for the maintainers and for every later PRP whose PR runs through these workflows. This PRP holds the Tier-1 files for workflows, Bicep modules, Helm and Dockerfiles in wave W16, so no other W16 PRP edits them.

Out of scope: the real-stack compose job (PRP-38, new workflow `real-stack.yml`); the hosted delivery workflow (PRP-63); the hosted App Service and demo Bicep (PRP-58, `infra/appservice` and `infra/demo`); the `NS_CLOUD` requirement for the App Service profile (see item 2, handed to PRP-58 unless the orchestrator grants the file); branch-protection changes such as requiring the `contracts`, `frontend-e2e`, `helm`, `security` or `egress-compose` checks (operator action, listed under Live and open gates); the Government region allowlist alignment (PRP-59); a Dependabot rebase or merge (GitHub writes by the operator); a live Bicep what-if (operator, PRP-64).

## Why
- `.github/workflows/security.yml:94` runs `docker build -f "${{ matrix.dockerfile }}"` with the matrix value interpolated into the shell, `:77` and `:113` duplicate the syft/trivy/grype install block, and `trivy fs` has no `--include-dev-deps`; there is no aggregator job although the image matrix is skipped when no Dockerfile exists (#66). The last bullet of #66 (images now exist and the scan path runs) is already true: the `image api/docs-assistant/frontend` checks pass on PR #197.
- `infra/bicep/modules/network/main.bicep:82-92` has `DenyAllInbound` (priority 4096) with no `AzureLoadBalancer` allow; `infra/bicep/modules/main.bicep:186` calls the network module without exposing `vnetAddressPrefix`; `infra/helm/values.yaml:130` has `egressAllowlist: []` with no documented Entra and Azure Monitor egress (#67). The first bullet of #67 (Helm tests skipping in CI) is fixed: `ci.yml:40-49` installs Helm 4 and `az bicep`.
- `scripts/render_mermaid.py:94` requires exactly five blocks of `docs/ARCHITECTURE.md`, and the CI step at `ci.yml:249-272` renders only that source, so `docs/security/dfd/*.md` is never checked (#68).
- `infra/bicep/modules/apim.bicep` defines only the service (resources at `:44`, outputs `:67-73`) and no policy; `docs/security/threat-model.md:101,388` records the missing UI-to-API rate limit as a gap (#69). The reuse mode must not touch a shared gateway (`apim.bicep:11-12`).
- `_skip_or_fail` is copied four times (`tests/unit/government_profile/test_no_commercial_endpoints.py:67`, `test_sovereign_hosts.py:304`, `tests/unit/infra/test_apim_v2_diagnostics_mcp_front.py:42`, `test_helm_render.py:38`) while the unit-tested original is `tests/security/egress/ci_gate.py`; the `egress-compose` job (`ci.yml:231-247`) has no `if: failure()` log dump (#215).
- `neurosphere_core.analytics.base.stub` imports `sqlite3` at module top (`packages/core/neurosphere_core/analytics/base/stub.py:27`) and `analytics/base/__init__.py:60` imports the stub, so any import of the analytics package loads `sqlite3`. `.grype.yaml:11-25` ignores four `sqlite-libs` CVEs and the Dockerfiles do not remove the package (#171).
- Dependabot PR #197 (npm) fails `regenerate licence register` with `FAIL npm:@rolldown/binding-*@1.2.16: licence UNKNOWN`: platform-specific packages cannot be read locally and the carry-forward in `scripts/licenses_report.py:21-25,460` keys on the exact name and version, so a bump is UNKNOWN. PR #198 (uv) fails the same job with `datamodel-code-generator@0.91.0` UNKNOWN and fails `contracts` because the bump changes generated code: the pin `==0.86.0` is deliberate (`packages/contracts/python/pyproject.toml:13-16`, read by `test_generate.py`).
- PRP-00 review follow-up (`PRPs/shipped/PRP-00-toolchain-workspaces-and-gates.md:265`): "fail CI if any licence row was carried forward". PRP-13 follow-up (a): the Helm chart and App Service profile do not require `NS_CLOUD` (`infra/helm/values.yaml:42` `env: {}`; only `values-government.yaml:18` sets it).

## Acceptance criteria
- [x] `security.yml`: no `${{ }}` interpolation of `matrix.*` inside `run:` (values pass through `env:` and are quoted); one script `scripts/ci/install-scanners.sh` (new) installs syft, trivy and grype by pinned version and sha256 and both jobs call it; `trivy fs` runs with `--include-dev-deps`; an aggregator job `images (all scans)` fails when the discover step found images but a scan job was skipped or failed, and passes when no image exists (#66). `actionlint` output shown.
- [x] Network: Given the network module, when it compiles (`az bicep build`), then an `AllowAzureLoadBalancerInbound` rule (priority below 4096) exists and `vnetAddressPrefix` is a root parameter of `modules/main.bicep` with the current value as default; `tests/security/network/test_bicep_network.py` pins both (#67).
- [x] Helm: `values.yaml` documents (comments next to `networkPolicy.egressAllowlist`) the egress that workload identity and Azure Monitor need, with a copy-paste example entry commented out; the chart fails to render without `env.NS_CLOUD` (`required`), `ci/values-ci.yaml` and `values-government.yaml` set it, and a Helm render test asserts the failure and the success (PRP-13 leftover (a), Helm half).
- [x] DFD: `python scripts/render_mermaid.py --source docs/security/dfd` (or the multi-source mode the implementer designs) renders every block in `docs/security/dfd/*.md` and fails on a parser error; `ci.yml`'s `mermaid` job runs it; the ARCHITECTURE five-block rule is unchanged (#68). Unit test in `tests/test_render_mermaid.py`.
- [x] APIM: `apim.bicep` takes an optional `uiApiRateLimitCalls` (default 0 = no policy) and, only when the service is created (never in reuse mode) and the value is above 0, applies a service-level `rate-limit-by-key` policy loaded from `infra/bicep/modules/policies/apim-ui-ingress.xml` (new); a test pins the "never in reuse mode" rule; `docs/security/threat-model.md` is NOT edited here (PRP-36 ran first; record the change in the completion note so PRP-48's owner updates the row) (#69).
- [x] Egress: `ci.yml` `egress-compose` has an `if: failure()` step that dumps `docker compose logs` (bounded, no secrets); the four `_skip_or_fail` copies are replaced by one shared, unit-tested helper (or, if no shared import path exists without a `pyproject.toml` change, by a drift test that fails when a copy differs from `tests/security/egress/ci_gate.py`); the `"no service"` marker risk is removed by matching the busybox message exactly; the nslookup assertion falls back to the output text (#215).
- [x] Images: Given `docker build` of `services/api/Dockerfile`, `services/workers/Dockerfile` and `services/docs-assistant/Dockerfile`, then the final image has no `sqlite-libs` apk, `python -c "import neurosphere_core.analytics"` succeeds in it, and the four `sqlite-libs` ignore rules are removed from `.grype.yaml` with Grype still passing (#171). This needs the lazy `sqlite3` import in `stub.py` (item 5, `[serial-after: PRP-11]`).
- [x] Licences: Given the bumped lockfiles of PRs #197 and #198 (checked out into a scratch worktree, not pushed), `python scripts/licenses_report.py --check` reports no UNKNOWN licence for the `@rolldown/binding-*` family and for `datamodel-code-generator`; resolution is by a cited rule (a documented platform-family map anchored on the installed sibling package, and the same `uv sync` selection as the python CI job), never by defaulting to permissive.
- [x] Carried-forward rows: when `CI` is set, `licenses_report.py --check` fails if any row was resolved by carry-forward and is not listed in a named, cited allowlist; the first CI run's real count is recorded in the PR (PRP-00 leftover).
- [x] `.github/dependabot.yml` ignores version updates of `datamodel-code-generator` with a comment pointing to `packages/contracts/python/pyproject.toml:13-16`, so PR #198 can be rebuilt without the generator bump (bumping it is a deliberate contracts change, PRP-37's area).
- [x] No suppressed failure appears in any workflow (`|| true`, `continue-on-error`, `if: always()` that hides a red job): the planning validator passes.

PRP exit: every box ticked, `verify-gates.ps1` full run green, review pass approved, PR open with CI green including the non-required `security`, `helm`, `contracts` and `egress-compose` jobs, and the two Dependabot PRs shown passing the licence step when re-run by the operator (or the evidence from the scratch worktree).

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| 1 | Dependabot #198 | Bump the generator and regenerate; hold the pin | Hold the pin (ignore rule). ASSUMPTION: the generator bump is a deliberate contracts PRP action, not a drive-by; confirm at plan approval. |
| 2 | Licence resolution for bumped platform binaries | Default to permissive; cite a family rule; require a human each time | Cite a family rule anchored on the installed sibling package of the same version (no network, no guess). Anything that cannot be anchored stays UNKNOWN and fails. |
| 3 | `sqlite3` in the stub | Keep the import at module top and keep the CVE ignores; make it lazy and drop `sqlite-libs` | Lazy import inside the connection factory (stub.py `:237`), then drop the package. The edit to `analytics/base/stub.py` waits for PRP-11 (it owns `analytics/**` in W12). |
| 4 | APIM rate limit scope | Per-API policy; service-level policy; skip | ASSUMPTION: service-level, off by default, created-service only. The UI ingress API itself is not defined in Bicep today, so a per-API policy has nothing to attach to. |
| 5 | App Service `NS_CLOUD` | Edit `infra/appservice/main.bicep` here; hand to PRP-58 | Hand to PRP-58 (not granted to this wave); record it in the completion note. |
| 6 | Shared skip helper location | New test package; extend `ci_gate.py`; drift test | Prefer one importable helper; the tests under `tests/unit/` are not packages, so a shared import needs a `pythonpath` entry in `pyproject.toml` (Tier-1, not owned). Fall back to the drift test. |
| 7 | Making new jobs required checks | Now; later | Later, by the operator. This PRP does not change branch protection. |

## Context manifest

### Files to read first
- `.github/workflows/security.yml` (`:40-125`), `.github/workflows/ci.yml` (`:20-60`, `:225-275`), `.github/workflows/dependabot-licences.yml`, `.github/workflows/contracts.yml`, `.github/dependabot.yml`.
- `scripts/licenses_report.py` (`:14-30` docstring, `:78-95` `PLATFORM_GATED`, `:292-345` uv, `:453-470` pnpm, `:583-625` main), `tests/test_licenses_report.py` (`:236`).
- `scripts/render_mermaid.py`, `tests/test_render_mermaid.py`, `docs/security/dfd/`.
- `infra/bicep/modules/network/main.bicep`, `infra/bicep/modules/main.bicep` (`:175-200`), `infra/bicep/modules/apim.bicep`, `infra/bicep/modules/policies/apim-mcp-enforcement.xml`.
- `infra/helm/values.yaml`, `infra/helm/values-government.yaml`, `infra/helm/templates/deployment.yaml` (`:36-110`), `infra/helm/templates/networkpolicy.yaml`, `infra/helm/ci/values-ci.yaml`.
- `services/api/Dockerfile`, `services/workers/Dockerfile`, `services/docs-assistant/Dockerfile`, `.grype.yaml`.
- `tests/security/egress/{ci_gate,conftest,test_compose_egress_blocked}.py`.

### Interfaces consumed
- ADR-0002 pins (`docs/adr/0002-stack-pins.md`) for scanner versions and the licence appendix the script regenerates.
- The `integration` marker rule: `pyproject.toml:90` deselects it; the egress job passes `-m integration` (PRP-20).
- `packages/core/neurosphere_core/analytics/base/stub.py` (PRP-11, W12) for the lazy import.

### Interfaces provided
- `scripts/ci/install-scanners.sh` (new) used by every workflow that needs the scanners (PRP-63 and later image jobs may reuse it).
- `licenses_report.py` platform-family rule and carried-forward check; later PRPs that add dependencies (PRP-62) rely on both.
- Helm chart requirement `env.NS_CLOUD`; `uiApiRateLimitCalls` parameter on the APIM module.
- An aggregator check name `images (all scans)` that the operator can make required.

### Patterns to match
- Pinned, sha256-verified tool install: `security.yml:77-95`.
- Fail-loud CI rule and header comment: `ci.yml:1-8`.
- `skip_or_fail` semantics: `tests/security/egress/ci_gate.py:20-35`.
- `PLATFORM_GATED` entries that cite their source: `scripts/licenses_report.py:78-85`.
- Policy XML with a named value: `infra/bicep/modules/policies/apim-mcp-enforcement.xml:16`.
- Helm `required` and `fail` style: `infra/helm/templates/deployment.yaml:48-52`, `networkpolicy.yaml:95`.

### Gotchas
- Do not weaken the secret and supply-chain gates while refactoring workflows: keep sha256 verification, `permissions` blocks and `persist-credentials: false` on untrusted-code jobs.
- `dependabot-licences.yml` splits an untrusted `regenerate` job (read-only token) from a `commit` job; do not merge them or give `regenerate` a write token.
- `ci.yml`, `security.yml` and `contracts.yml` job names are required-check names (python, frontend, mermaid, planning, bicep, gitleaks, blocked-paths, PII, two CodeQL analyses): never rename a required check.
- The `mermaid` job uses the runner's preinstalled Chrome and `--no-sandbox` (`ci.yml:249-272`); keep that.
- Reproduce the Dependabot failures from the PR branches in a scratch worktree (`gh pr checkout` is a read of GitHub plus a local checkout); do not push or comment on the PRs.
- Removing `sqlite-libs` with `apk del` can pull out the `.python-rundeps` meta package; check the result by building the image and importing the analytics package, not by reading the Dockerfile.
- Same-named test directories with `__init__.py` shadow each other: run `tests/security/network`, `tests/security/egress`, `tests/unit/infra` and `tests/unit/government_profile` in one pytest invocation.
- Docker is needed for item 5's image builds; this PRP does not use compose and does not hold the compose stack.

Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership

```ownership
owns:
  - .github/workflows/ci.yml
  - .github/workflows/security.yml
  - .github/workflows/codeql.yml
  - .github/workflows/contracts.yml
  - .github/workflows/dependabot-licences.yml
  - .github/dependabot.yml
  - scripts/ci/**
  - scripts/render_mermaid.py
  - scripts/licenses_report.py
  - infra/bicep/modules/**
  - infra/helm/**
  - services/api/Dockerfile
  - services/workers/Dockerfile
  - services/docs-assistant/Dockerfile
  - frontend/Dockerfile
  - .grype.yaml
  - tests/security/egress/**
  - tests/security/network/**
  - tests/unit/infra/**
  - tests/unit/government_profile/test_no_commercial_endpoints.py
  - tests/unit/government_profile/test_sovereign_hosts.py
  - tests/test_licenses_report.py
  - tests/test_render_mermaid.py
tier1:
  - .github/workflows/ci.yml
  - .github/workflows/security.yml
  - .github/workflows/contracts.yml
  - infra/bicep/modules/**
  - infra/helm/**
  - services/api/Dockerfile
  - services/workers/Dockerfile
  - services/docs-assistant/Dockerfile
  - .grype.yaml
tier2_appends: []
must_not_touch:
  - packages/contracts/**
  - pyproject.toml
  - uv.lock
  - .github/workflows/real-stack.yml
  - .github/workflows/deploy-hosted.yml
  - infra/demo/**
  - infra/appservice/**
  - packages/core/neurosphere_core/analytics/**
```

## Implementation blueprint

Parallelization map: item 1 owns `security.yml` and `scripts/ci/**`; item 2 owns Bicep and Helm; item 3 owns `ci.yml` (all `ci.yml` edits are in this item) and `render_mermaid.py`; item 4 owns the four test files and `tests/security/egress/**`; item 5 owns Dockerfiles, `.grype.yaml` and (serially) `stub.py`; item 6 owns the licence script, `dependabot*.yml` and `contracts.yml`. Items 1, 2, 4 and 6 share no file and are [P]. Item 3 touches `ci.yml` and `tests/security/egress/**`'s CI dependency: do it after item 4's shared-helper decision only for the egress job step; the Mermaid half is [P]. Item 5 follows nothing but its `stub.py` part is `[serial-after: PRP-11]`.

### Item 1 - security.yml hardening (#66)  [P]
- Deliverable: `env:`-passed, quoted matrix values; `scripts/ci/install-scanners.sh` shared by the `image-scan` and `dependency-audit` jobs (versions and sha256 stay in workflow `env`); `--include-dev-deps` on `trivy fs`; aggregator job `images (all scans)`; a comment recording that the "images exist and run" bullet is satisfied by the current runs.
- Owned files: `.github/workflows/security.yml`, `scripts/ci/install-scanners.sh` (new).
- Must NOT touch: `ci.yml`, `.grype.yaml` (item 5).
- Depends on: none.
- Acceptance criteria: the `security.yml` box; the workflow run on the PR shows the jobs green and the aggregator green.
- Tests: `actionlint .github/workflows/security.yml` if installed, else state it was not run; `uv run pytest -q tests/test_planning_alignment.py` (the no-suppression rule).
- Pattern references: `security.yml:77-95`.

### Item 2 - Network baseline, APIM rate limit, Helm NS_CLOUD (#67, #69, PRP-13 (a))  [P]
- Deliverable: the load-balancer allow rule and `vnetAddressPrefix` root parameter; `uiApiRateLimitCalls` and `policies/apim-ui-ingress.xml` with the created-only rule; Helm egress documentation, `required` `NS_CLOUD`, CI and Government values updated; tests pinning each. Hand the App Service `NS_CLOUD` requirement to PRP-58 in the completion note.
- Owned files: `infra/bicep/modules/**`, `infra/helm/**`, `tests/security/network/**`, `tests/unit/infra/test_helm_render.py`, `tests/unit/infra/test_bicep_build.py`.
- Must NOT touch: `infra/demo/**`, `infra/appservice/**`, `docs/security/threat-model.md`.
- Depends on: none.
- Acceptance criteria: the Network, Helm and APIM boxes; `az bicep build --file infra/bicep/modules/main.bicep` output shown.
- Tests: `uv run pytest -q tests/security/network tests/unit/infra`; `helm lint --strict infra/helm -f infra/helm/ci/values-ci.yaml`; `helm template` with and without `env.NS_CLOUD` (failure expected without).
- Pattern references: `network/main.bicep:70-95`, `policies/apim-mcp-enforcement.xml:16`, `deployment.yaml:48-52`.

### Item 3 - ci.yml: DFD render and egress-job logs (#68, #215 item 4)
- Deliverable: multi-source mode in `render_mermaid.py` and its test; `mermaid` job step for `docs/security/dfd`; `if: failure()` log step on `egress-compose`.
- Owned files: `.github/workflows/ci.yml`, `scripts/render_mermaid.py`, `tests/test_render_mermaid.py`.
- Must NOT touch: required job names, the python job's pytest command.
- Depends on: none (rebase on `main`; `ci.yml` is Tier-1 and PRP-52 is its only editor this wave).
- Acceptance criteria: the DFD box and the log-step half of the Egress box; show the render of the three DFD files and a deliberately broken block failing locally (not committed).
- Tests: `uv run pytest -q tests/test_render_mermaid.py`; `python scripts/render_mermaid.py --no-sandbox` plus the new mode, locally if Chrome is available.
- Pattern references: `ci.yml:249-272`.

### Item 4 - Egress tests: shared helper and corpus robustness (#215 items 1-3)  [P]
- Deliverable: single `skip_or_fail` for the four copies (or the drift test fallback, clarification 6), exact busybox message matching replacing `"no service"` in `tests/security/egress/conftest.py:57`, nslookup output fallback in `test_compose_egress_blocked.py`.
- Owned files: `tests/security/egress/**`, `tests/unit/infra/test_apim_v2_diagnostics_mcp_front.py`, `tests/unit/infra/test_helm_render.py`, `tests/unit/government_profile/test_no_commercial_endpoints.py`, `tests/unit/government_profile/test_sovereign_hosts.py`.
- Must NOT touch: assertions about which hosts are allowed or denied (corpus content), `pyproject.toml`.
- Depends on: none (items 2 and 4 both edit `test_helm_render.py`: do item 2's test additions first, or in one branch commit order).
- Acceptance criteria: the Egress box (helper half); the helper has its own test.
- Tests: `uv run pytest -q tests/security/egress tests/unit/infra tests/unit/government_profile`; `CI=1` run shows a missing tool fails rather than skips.
- Pattern references: `tests/security/egress/test_ci_gate.py`.

### Item 5 - Drop sqlite-libs (#171)
- Deliverable: after PRP-11 has merged (rebase on `main`), make the `sqlite3` import in `analytics/base/stub.py` lazy; add the removal step to the final stage of the three Dockerfiles; delete the four ignore rules and update the header comment in `.grype.yaml`; build all three images and import the analytics package in each.
- Owned files: `services/api/Dockerfile`, `services/workers/Dockerfile`, `services/docs-assistant/Dockerfile`, `.grype.yaml`, and `[serial-after: PRP-11]` `packages/core/neurosphere_core/analytics/base/stub.py` (one import moved; not in this PRP's Ownership block).
- Must NOT touch: base image digests, `pyproject.toml`, `uv.lock`.
- Depends on: PRP-11 merged for the `stub.py` edit.
- Acceptance criteria: the Images box; if PRP-11 has not merged, deliver the Dockerfile and `.grype.yaml` change only if the analytics import still works, otherwise leave #171 open and say so.
- Tests: `docker build -f services/api/Dockerfile -t ns-api:probe .` (and workers, docs-assistant); `docker run --rm --entrypoint python ns-api:probe -c "import neurosphere_core.analytics"`; `uv run pytest -q packages/core/tests/analytics`; Grype run as in `security.yml` if available locally, else the CI job is the evidence.
- Pattern references: `services/api/Dockerfile:30-45`.

### Item 6 - Licence register on bumps and carried-forward check (#197, #198)  [P]
- Deliverable: reproduce both failures from the PR branches in scratch worktrees; the platform-family rule for npm binaries and the sync selection fix for the uv member group in `dependabot-licences.yml`; the carried-forward CI check; the Dependabot ignore rule for `datamodel-code-generator`; tests in `tests/test_licenses_report.py` for each rule (a bumped sibling resolves, an unanchored package stays UNKNOWN, a carried row fails under `CI`).
- Owned files: `scripts/licenses_report.py`, `.github/workflows/dependabot-licences.yml`, `.github/dependabot.yml`, `.github/workflows/contracts.yml` (only if the generator pin comment or step needs it), `tests/test_licenses_report.py`.
- Must NOT touch: `docs/licenses.md` content except through the script's own regeneration, `packages/contracts/**`, `uv.lock`, `pnpm-lock.yaml`.
- Depends on: none.
- Acceptance criteria: the Licences, Carried-forward and Dependabot boxes; logs of the reproduction before and after.
- Tests: `uv run pytest -q tests/test_licenses_report.py`; `python scripts/licenses_report.py --check` on `main` and on each scratch PR checkout.
- Pattern references: `scripts/licenses_report.py:78-95`, `.github/workflows/dependabot-licences.yml`.

### Item 7 - Integration and close-out
- Deliverable: completion note including the handoffs (App Service `NS_CLOUD` to PRP-58; threat-model APIM row and #69 to the PRP-48 owner), the operator list (rebase the Dependabot PRs, consider requiring new checks), `CHANGELOG.md` line, issues #66, #67, #68, #171, #215 closed or commented; #69 left open for its non-Bicep half (PRP-48).
- Owned files: close-out files per reference section 6.
- Depends on: items 1 to 6.
- Acceptance criteria: Validation gates pass.
- Tests: the gates below.

## Validation gates
```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q tests/security/egress tests/security/network tests/unit/infra tests/unit/government_profile tests/test_licenses_report.py tests/test_render_mermaid.py tests/test_planning_alignment.py packages/core/tests/analytics
helm lint --strict infra/helm -f infra/helm/ci/values-ci.yaml
az bicep build --file infra/bicep/modules/main.bicep
python scripts/licenses_report.py --check
python scripts/render_mermaid.py --no-sandbox
python scripts/validate_planning.py
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```
Also paste the three `docker build` results and the import check from item 5, and the workflow runs of the PR. Report any command not run (for example no Docker or no `actionlint`).

## Migration and rollback
No data migration. Bicep changes are additive parameters with defaults (`vnetAddressPrefix` keeps its value, `uiApiRateLimitCalls` defaults to off) and one new NSG rule; a deployed environment picks them up only on its next apply. The Helm `required` `NS_CLOUD` is a breaking render change for any values file without it: it is announced in `CHANGELOG.md` and in the chart comments. Revert by reverting the PR; each item is independently revertible (workflow, Bicep/Helm, images, licence script).

## Live and open gates
No `NS_LIVE_APPROVED=1` item and no paid call. OPEN and operator-only: a live Bicep what-if of the root template (#67 last bullet, PRP-64); making `security`, `contracts`, `helm`, `frontend-e2e`, `egress-compose` or the new aggregator required checks (branch protection); rebasing or closing Dependabot PRs #197 and #198 after this merges.

## NOT building
- A merge queue, new required checks, or Dependabot auto-merge.
- The hosted delivery workflow, real-stack workflow, or App Service and demo Bicep changes.
- A generator upgrade or any change to `packages/contracts/**`.
- Cluster-level egress proof (in-cluster proof stays OPEN, D7).
- The audit-for-allowed-reads half of #69 (PRP-48).

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [ ] All clarification questions are decided, not guessed (rows 1, 4 and 6 are assumptions to confirm at plan approval)

## Execution state

| Item | Status | Branch/worktree | Notes |
|---|---|---|---|
| 1 | merged | prp-52-ci-infra-hardening | security.yml env-passed matrix, install-scanners.sh, --include-dev-deps, aggregator; actionlint clean |
| 2 | merged | prp-52-ci-infra-hardening | LB allow rule, vnetAddressPrefix, APIM uiApiRateLimitCalls + policy, Helm NS_CLOUD required + egress docs; App Service NS_CLOUD handed to PRP-58 |
| 3 | merged | prp-52-ci-infra-hardening | --source-dir mode, ci.yml DFD step + egress log step; real render not run locally (no Chrome) |
| 4 | merged | prp-52-ci-infra-hardening | shared skip_or_fail loaded by path from ci_gate.py (no pyproject change); exact exec-failure markers; nslookup text fallback; compose-only probe run not run |
| 5 | merged | prp-52-ci-infra-hardening | lazy sqlite3 in stub.py (PRP-11 shipped); .python-rundeps re-pin then apk del; 3 images built, no sqlite apk, analytics import ok; .grype.yaml ignore emptied; Grype run is CI-only |
| 6 | merged | prp-52-ci-infra-hardening | family rule + carried-forward CI check + --allow-carried; reproduced PR 197/198 in scratch worktrees (old script UNKNOWN, new resolves); dependabot ignore; sync selection in ci planning job + dependabot-licences |
| 7 | merged | land-prp-52 | close-out: completion note, changelog fragment, index regeneration |

## Completion note
- Date and PR: 2026-11-16, PR #302 (squash merge to main).
- Deviations: the shared `skip_or_fail` is loaded by path from `tests/security/egress/ci_gate.py` (no `pyproject.toml` change, clarification 6). The Helm `NS_CLOUD` check hard-fails on any value other than `commercial` or `government`, which is stricter than the spec and intended. Item 5's serial dependency (PRP-11, lazy `sqlite3` in `analytics/base/stub.py`) was already shipped, so it was done in this PR.
- Descoped items: the App Service `NS_CLOUD` requirement is handed to PRP-58 (`infra/appservice/**` is not owned here; PRP-58 must add it). The `docs/security/threat-model.md` APIM rate-limit row is not edited here: the PRP-48 owner updates it (#69 stays open for the non-Bicep half). The DFD Mermaid render was not run locally (no Chrome); the CI `mermaid` job is the evidence.
- OPEN gates: live Bicep what-if of the root template (PRP-64, operator); Grype run is CI-only; compose-only egress probe not run locally; making `security`, `contracts`, `helm`, `frontend-e2e`, `egress-compose` and the `images (all scans)` aggregator required checks (operator, branch protection; do not require the aggregator until it has run on main, it uses `if: always()` and checks results explicitly); rebasing Dependabot PRs #197 and #198 after merge.
- Env vars for the operator: none new. `NS_CLOUD` is now required in the Helm values for every environment; `uiApiRateLimitCalls` is a Bicep parameter, default 0 (off).
- Follow-up issues: reviewer follow-ups handled at close-out: the `fsevents` carry-forward citation now names its actual dependent (vite optionalDependencies in `pnpm-lock.yaml`); the bare `"is not running"` egress marker is kept on purpose and documented (docker daemon messages carry a variable container id); the compose log dump service names `egress-probe` and `azurite` match `docker-compose.yml`. Remaining: PRP-58 App Service `NS_CLOUD`; PRP-48 owner threat-model row.
- Product check: CI and infrastructure work with no operator-facing UI; operator actions are listed under OPEN gates.
