---
name: PRP-63-delivery-pipeline-to-hosted
status: shipped
shipped: 2026-11-16
pr: 316
priority: P1
order: 51
review: required
created: 2026-11-14
model: sonnet
orchestrator_model: sonnet
implementer_model: sonnet
phase: 6
ns: NS-07, NS-08
depends_on: [PRP-38-real-stack-ci-and-dev-stack, PRP-58-hosted-data-path-and-environment-hardening]
wave: W19
branch: prp-63-delivery-pipeline
allow_parallel: true
issues: [257]
---

# PRP-63: Delivery pipeline to the hosted environment

## Goal
Replace the by-hand hosted deploy with a workflow the operator approves once per release: when a release is published from `main`, GitHub Actions logs in to Azure with OpenID Connect (a federated credential, no stored secret), shows the plan, waits for approval in a protected GitHub environment, deploys the pinned image tag with the existing `hosted_demo.py`, runs a smoke on every deploy, fails the run on a red smoke, and only then turns the draft GitHub Release into a published one. Today no workflow logs in to Azure (`grep` for `azure/login|az login|AZURE_CLIENT_ID` in `.github/workflows` is empty), `release.yml` only drafts a release and both `v0.1.0-rc.1` and `v0.1.0-rc.2` are drafts, and the smoke exists (`scripts/gates/_hosted_demo_smoke.py`, `frontend/tests/hosted/`) but nothing runs it. This is for the operator who owns the hosted environment and for every later PRP that must be seen working there. The operator creates the federated credential and the environment (a ready-to-run script is part of this PRP) and approves the first run; the live run itself is PRP-64.

Out of scope: running anything against Azure (PRP-64, `NS_LIVE_APPROVED=1`); the hosted Bicep and its hosted-data-path settings (PRP-58); the signed-in browser smoke `frontend/playwright.hosted.config.ts` (needs a human sign-in, stays manual, PRP-64); building images on every push to `main` (see clarification 1); changes to `ci.yml`, `security.yml` or `real-stack.yml`; Government cloud delivery; automatic teardown or cost control beyond what `hosted_demo.py` already does.

## Why
- `.github/workflows/` has `ci.yml`, `codeql.yml`, `contracts.yml`, `dependabot-licences.yml`, `docs.yml`, `release.yml`, `secret-scan.yml`, `security.yml`; none logs in to Azure. The only CD is the docs site to Pages (PRP-25).
- `.github/workflows/release.yml:8,348-355` builds and signs images and the chart on a `v*.*.*` tag and creates a draft release (`flags=(--draft ...)`); `gh release list` shows both release candidates as drafts. `release.yml:7-10,37` documents `permissions: {}` and that only `sign` holds `id-token: write` and only `release-notes` holds `contents: write`.
- The hosted deploy is manual: `scripts/gates/hosted_demo.py:270-301` has the subcommands preflight, plan, deploy, grant-model-access, entra-redirect, seed-access, smoke, teardown, status; it refuses unless `NS_LIVE_APPROVED=1` (`:1997`), `deploy` needs `--approve-plan <sha256 printed by plan>`, and the images come from `ghcr.io/fgarofalo56/neurosphere/{api,workers,frontend}` at a pinned tag (`docs/deploy/hosted-demo.md:147,358`, update path `:405-421`).
- The smoke is pure and injectable: `scripts/gates/_hosted_demo_smoke.py:275` `run_smoke(frontend_url, api_host, sites, az_runner, transport)` checks the frontend root, `/config.json` keys, 401 on the API, `/readyz` not proxied, API direct access refused and App Service health; `cmd_smoke` (`hosted_demo.py:1688`) resolves hosts from deployment outputs (`get_outputs`, `:594`, deployment name `cm.DEPLOYMENT_NAME`).
- The ownership register behind teardown is a local JSON export plus an optional Cosmos copy (`scripts/gates/_hosted_demo_common.py:294-330`); a CI runner's local state is gone after the job.
- Hosted environment history and evidence (2026-10-27/28) live in `docs/evidence/PRP-32/`; the doc to extend is `docs/deploy/hosted-demo.md`.

## Acceptance criteria
- [x] `.github/workflows/deploy-hosted.yml` (new) triggers on completion of the `release` workflow for a pushed `v*.*.*` tag and on `workflow_dispatch` (inputs: `image_tag`, `apply` default false). A pull request run or a dry-run release never deploys (guarded by event and ref; a static test proves it).
- [x] Azure login uses OIDC only: `permissions: id-token: write` on the jobs that log in, `azure/login` with client, tenant and subscription ids read from environment secrets, no `client-secret`, no stored credential, no `AZURE_CREDENTIALS`. No secret value appears in any file or log; ids that contain a subscription id are environment secrets, not variables.
- [x] Given a release tag, when the workflow runs, then a `plan` job produces the what-if summary and the plan sha256 in the job summary and an uploaded evidence artifact (never committed); an `apply` job bound to the protected environment `hosted-demo` waits for a human reviewer, and then runs `hosted_demo.py deploy --approve-plan <that hash>` for that tag only.
- [x] Given a finished deploy, when the smoke runs (`scripts/gates/hosted_smoke.py`, new), then it runs every check of `run_smoke`, retries App Service warm-up a bounded number of times, writes a machine-readable result and a human summary, fails the job on any failed check, and never prints a response body, token or header value other than `Cache-Control`.
- [x] Release policy: a `publish-release` job (needs `apply`, `contents: write`, nothing else, no Azure login) turns the draft release of the tag into a published release (keeping the prerelease flag) only after a green smoke; on red smoke the release stays a draft and the run is red. `release.yml` itself is changed only in its header comment and, if needed, a stable `name:` for the `workflow_run` trigger.
- [x] Concurrency: one deploy at a time (`concurrency` group without `cancel-in-progress`); a manual re-run with the same tag is idempotent (plan reports no change).
- [ ] `docs/deploy/delivery.md` (new) documents: trigger and flow (Mermaid diagram rendered locally before it is claimed), the OIDC setup, the environment and its reviewers, the secrets list by name (no values), the role assignments the identity needs and why, rollback (re-run with the previous tag, or `teardown` by the operator), and what the pipeline does not do.
- [ ] A ready-to-run operator script `temp/setup-delivery-oidc.ps1` (not committed; `temp/` is gitignored) creates or updates the Entra app registration and the two federated credentials, assigns the roles at the resource group scope, creates the GitHub environments, and sets environment secrets by prompting the operator (values are typed, never echoed or passed on a command line). The PRP completion note tells the operator how to run it and what to report back.
- [x] `tests/unit/delivery_pipeline/` (new directory, unique name) statically asserts the workflow rules above (OIDC only, environment on `apply`, no `|| true` or `continue-on-error`, no secret literals, `id-token: write` only where needed, no trigger on `pull_request`) and unit-tests `hosted_smoke.py` with a fake transport and fake `az`.
- [ ] `actionlint` (if installed) and the planning validator pass; the workflow has never run live and the completion note says so (hand-off to PRP-64).

PRP exit: all boxes ticked, `verify-gates.ps1` full run green, review pass approved, PR open, CI green. Live deploy and first approval are OPEN until PRP-64.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| 1 | What does "deploy `main`" mean | Deploy the image tag of each release cut from `main`; build and publish `main-<sha>` images on every push | ASSUMPTION: the first. Images are published only by `release.yml` on a tag (public GHCR packages, `release.yml:15-16`), so deploying each merge would publish a public package per commit. The push-to-main variant is a follow-up if the owner wants it. |
| 2 | Approval gate | Protected environment with required reviewers; manual `workflow_dispatch` only | Protected environment `hosted-demo` on the `apply` job; the `plan` job uses a second, unprotected environment `hosted-demo-plan`. Both have their own federated credential on one app registration. ASSUMPTION: the operator is the sole reviewer. |
| 3 | Operator approval vs `NS_LIVE_APPROVED=1` | Set the variable in the workflow; require a human each time | ASSUMPTION: approval in the protected environment is the operator approval, so the `apply` job (and only it, and the plan job after its own environment gate) sets `NS_LIVE_APPROVED=1` in its step environment. A reviewer sees the plan hash before approving. |
| 4 | Smoke scope | Unauthenticated and control-plane checks only; add the signed-in Playwright run | Unauthenticated and control-plane checks (`run_smoke`). The signed-in `playwright.hosted.config.ts` run needs a human sign-in and stays manual. |
| 5 | Where parameters come from | Workflow file; repository variables; environment secrets | Environment secrets (subscription ids appear inside subnet and zone ids; the repository is public). Names only in `docs/deploy/delivery.md`. |
| 6 | Register state on an ephemeral runner | Persist as artifact; rely on the Cosmos copy | UNVERIFIED. The implementer reads `docs/deploy/hosted-demo.md` section 4 and `RegisterBook.load` (local file first, then Cosmos backend) and records whether an update deploy works without a local register; if not, the workflow restores the export from the previous run's artifact or fails with a clear message. |
| 7 | First run | Pipeline performs the first-ever deploy; update path only | Update path only: the environment from PRP-32 already exists; a first-ever deploy stays a manual operator action (S3 in the runbook). |

## Context manifest

### Files to read first
- `.github/workflows/release.yml` (header `:1-40`, `meta` outputs `:51-125`, `release-notes` `:311-360`) and `.github/workflows/ci.yml:1-30` (permissions, concurrency, fail-loud rule).
- `scripts/gates/hosted_demo.py` (`build_parser` `:243-302`, `cmd_smoke` `:1688`, `main` `:1989-2025`, `get_outputs` `:594`), `scripts/gates/_hosted_demo_smoke.py` (`run_smoke` `:275`, `SiteTarget` `:44`), `scripts/gates/_hosted_demo_common.py` (`RegisterBook` `:294`, `STATE_DIR`, `EVIDENCE_DIR`, `DEPLOYMENT_NAME`).
- `docs/deploy/hosted-demo.md` (S3 deploy, S8 release tag, section 4 update path, Troubleshooting).
- `infra/demo/main.bicep` (parameters `:22-30`, `imageTag`) for what the deploy takes; PRP-58 may have changed it, re-read after rebasing.
- `frontend/playwright.hosted.config.ts` and `frontend/tests/hosted/` (what stays manual).
- `docs/release/release-process.md` and `docs/release/verify.md` (existing release docs to link).
- `PRPs/shipped/PRP-32-*.md` completion note (what the hosted run proved and its gotchas).

### Interfaces consumed
- `release.yml`: tag trigger, workflow `name: release`, draft release creation, image names and tags (`0.1.0-rc.2` for tag `v0.1.0-rc.2`) from PRP-13.
- `hosted_demo.py` subcommands and the evidence files they write (`--evidence-dir`), `run_smoke` (PRP-32); hosted data-path and probe settings from PRP-58 (must have merged).
- `tests/integration/real_stack` job from PRP-38 as a precondition signal only (the deploy workflow does not run it).

### Interfaces provided
- `.github/workflows/deploy-hosted.yml`: jobs `plan`, `apply`, `publish-release`; environments `hosted-demo-plan` and `hosted-demo`; secret names documented in `docs/deploy/delivery.md`.
- `scripts/gates/hosted_smoke.py` (new): CLI `python scripts/gates/hosted_smoke.py --resource-group ... --subscription ... --result-json PATH` (exact flags are the implementer's), exit non-zero on a failed check.
- The release convention: a tag release stays a draft until the hosted smoke is green.

### Patterns to match
- Least-privilege permissions per job: `release.yml:37,55,133,218,318`.
- Version-pinned actions, no third-party deploy action: `ci.yml` uses pinned `actions/*` and `azure/setup-helm`; pin `azure/login` to a version (verify the current major with the Microsoft Learn doc `https://learn.microsoft.com/azure/developer/github/connect-from-azure-openid-connect` before use; subagents lack Learn, so the orchestrator pastes the facts).
- Injectable-transport unit tests of the smoke: `scripts/gates/_hosted_demo_smoke.py` tests under `tests/unit/` for hosted demo (find with `grep -rn run_smoke tests`).
- Operator hand-off script style: prompts for values with `Read-Host -AsSecureString`, never echoes or passes them on a command line, verifies presence and behaviour afterwards (the owner's rule; no such script exists in this repo yet).

### Gotchas
- The repository is public: no subscription, tenant or resource ids in tracked files, logs or docs (placeholders only); evidence artifacts hold ids, so they are uploaded as private workflow artifacts with a short retention, never committed.
- `workflow_run` triggers run the workflow definition from the default branch and also fire for pull-request runs of `release` (`release.yml` runs on PRs as a dry run): the trigger condition must check `github.event.workflow_run.event == 'push'`, a tag-shaped `head_branch` and `conclusion == 'success'`.
- Never interpolate `${{ github.event.* }}` or inputs into `run:` (script injection); pass through `env:` and validate the tag with a regex before it reaches `--image-tag`.
- `hosted_demo.py` is run with `uv run python scripts/gates/hosted_demo.py ...` (it refuses when `neurosphere_core` is not importable); `MSYS_NO_PATHCONV` is a local Git Bash concern, not a runner concern.
- `deploy --approve-plan` expects the hash printed by `plan` for the same arguments: the `plan` and `apply` jobs must pass identical infra arguments (single source: one env block or a small shared script).
- Key Vault purge protection and Defender topics block redeploy and teardown in this environment (`docs/deploy/hosted-demo.md` Troubleshooting, memory notes): the pipeline only does the update path, never teardown.
- Azure policy requires `project` and `owner` tags on resource groups (G05 notes); `hosted_demo.py` already sets them from `--tag-owner`.
- A deploy changes shared enterprise resources: nothing in this PRP may run it; the static tests and the fake-transport tests are the only execution.

Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership

```ownership
owns:
  - .github/workflows/deploy-hosted.yml
  - .github/workflows/release.yml
  - docs/deploy/delivery.md
  - scripts/gates/hosted_smoke.py
  - tests/unit/delivery_pipeline/**
tier1:
  - .github/workflows/deploy-hosted.yml
  - .github/workflows/release.yml
tier2_appends: []
must_not_touch:
  - .github/workflows/ci.yml
  - .github/workflows/security.yml
  - .github/workflows/real-stack.yml
  - scripts/gates/hosted_demo.py
  - scripts/gates/_hosted_demo_common.py
  - scripts/gates/_hosted_demo_smoke.py
  - infra/demo/**
  - infra/appservice/**
  - docs/deploy/hosted-demo.md
```

## Implementation blueprint

Parallelization map: item 1 (`hosted_smoke.py` and its tests) and item 3 (the operator script and `docs/deploy/delivery.md`) share no file and are [P]; item 2 (the workflow) needs item 1's CLI; item 4 (`release.yml` comment and the static workflow tests) needs item 2; item 5 closes out.

### Item 1 - hosted_smoke.py  [P]
- Deliverable: a CI-oriented wrapper that imports `run_smoke` and `SiteTarget` from `_hosted_demo_smoke`, resolves frontend and API hosts and site names from the deployment outputs (`az deployment group show`, deployment name from `_hosted_demo_common.DEPLOYMENT_NAME`), retries with bounded backoff while sites warm up, writes `--result-json` and a Markdown summary to `$GITHUB_STEP_SUMMARY` when set, exits 1 on any failed check, 2 on a refusal (missing input, no `az`).
- Owned files: `scripts/gates/hosted_smoke.py`, `tests/unit/delivery_pipeline/test_hosted_smoke.py`.
- Must NOT touch: `hosted_demo.py`, `_hosted_demo_*.py` (PRP-58 owns them; import only).
- Depends on: none.
- Acceptance criteria: the smoke box; tests cover all-green, one red check, warm-up retry then green, retry exhaustion, and that no body or token text reaches the output.
- Tests: `uv run pytest -q tests/unit/delivery_pipeline/test_hosted_smoke.py`.
- Pattern references: `hosted_demo.py:1688-1715`, `_hosted_demo_smoke.py:275-320`.

### Item 2 - deploy-hosted.yml
- Deliverable: the workflow with jobs `plan`, `apply`, `publish-release` as specified; tag validation step; shared argument block; artifacts for evidence (retention days set, short); step summary with the plan hash and change list; `concurrency: hosted-demo-deploy` without cancel; `timeout-minutes` on every job; `NS_LIVE_APPROVED=1` set only in the plan and apply steps that call `hosted_demo.py`.
- Owned files: `.github/workflows/deploy-hosted.yml`.
- Must NOT touch: `ci.yml`, `release.yml` (item 4).
- Depends on: item 1.
- Acceptance criteria: the OIDC, plan/approve/deploy, release-policy and concurrency boxes. Read `hosted_demo.py` `_emit` to find where the plan hash is exposed and use that, not a log scrape.
- Tests: `actionlint .github/workflows/deploy-hosted.yml` if installed (else state it was not run); static tests in item 4.
- Pattern references: `release.yml:51-125,311-360`.

### Item 3 - Operator script and delivery documentation  [P]
- Deliverable: `docs/deploy/delivery.md` (Mermaid flow rendered with the repo's mermaid-cli before claiming it renders; link from nothing else, `mkdocs.yml` nav is a Tier-2 append: add one line only if the docs build requires it); `temp/setup-delivery-oidc.ps1` (and a `.sh` twin only if cheap) performing the operator steps listed in the OIDC box, idempotent, with a `-WhatIf`-style dry run; role guidance: Contributor on the hosted resource group plus the narrowest role that lets the Bicep create its role assignments (check what `infra/demo/main.bicep` assigns; do not default to Owner), with the reason for each.
- Owned files: `docs/deploy/delivery.md`, `temp/setup-delivery-oidc.ps1` (untracked).
- Must NOT touch: `docs/deploy/hosted-demo.md`, any file under `infra/`.
- Depends on: none (item 2's secret names are listed from the plan; reconcile at the end).
- Acceptance criteria: the docs and operator-script boxes. The script is syntax-checked (`powershell -NoProfile -Command "[scriptblock]::Create((Get-Content temp/setup-delivery-oidc.ps1 -Raw)) | Out-Null"`) but not run.
- Tests: `uv run pytest -q tests/docs` (docs build rules) and the syntax check above.
- Pattern references: `docs/deploy/hosted-demo.md` section structure; the prompt-for-values style above.

### Item 4 - Release policy and static workflow tests
- Deliverable: `release.yml` header comment (draft until `deploy-hosted` publishes) and, only if required for the `workflow_run` trigger, no functional change; `tests/unit/delivery_pipeline/test_deploy_hosted_workflow.py` asserting the static rules from the Acceptance criteria by parsing the YAML.
- Owned files: `.github/workflows/release.yml`, `tests/unit/delivery_pipeline/test_deploy_hosted_workflow.py`.
- Must NOT touch: release signing, chart, SBOM jobs.
- Depends on: item 2.
- Acceptance criteria: the static-test box; `tests/release` (existing release tests) still pass.
- Tests: `uv run pytest -q tests/unit/delivery_pipeline tests/release`.
- Pattern references: `tests/release` for workflow-parsing tests.

### Item 5 - Integration and close-out
- Deliverable: completion note with the operator hand-off (how to run `temp/setup-delivery-oidc.ps1`, what to report back, which secrets to set by name, the environment reviewer), `CHANGELOG.md` `[Unreleased]` line, mention in the note that the two draft rc releases need a decision (publish by hand or let the first run handle them) and that the live first run belongs to PRP-64; regenerate `PRPs/INDEX.md`/master table as per reference section 6.
- Owned files: close-out files per reference section 6.
- Depends on: items 1 to 4.
- Acceptance criteria: Validation gates pass; completion note states "deployed: no, unverified live".
- Tests: the gates below.

## Validation gates
```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q tests/unit/delivery_pipeline tests/release tests/docs tests/test_planning_alignment.py
python scripts/validate_planning.py
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```
No `NS_LIVE_APPROVED=1` command is run. If `actionlint` is installed, also run it over `.github/workflows/`.

## Migration and rollback
No data migration. The workflow is inert until the operator creates the federated credential, the two GitHub environments and the secrets, so merging it deploys nothing. Rollback: delete the two environments and the federated credentials (documented in `delivery.md`), or revert the PR; a bad deploy is rolled back by re-running the workflow with the previous tag (update path) or by the operator's `teardown`. The release policy change affects only future tags.

## Live and open gates
OPEN until PRP-64: the first OIDC login, the first approved plan and apply, and the first smoke against the real hosted environment (`NS_LIVE_APPROVED=1` plus the operator approving the protected environment). Operator-only before that: run the setup script (elevated Entra and Azure rights), choose reviewers, set the environment secrets by typing them. Spend is pre-authorized for NeuroSphere, but each live run still logs a cap and a spend row (PRP-64). The decision to publish or delete the two draft rc releases is the operator's.

## NOT building
- A deploy on every push to `main`, or image builds outside `release.yml`.
- A first-ever environment creation, teardown, or seed-access automation.
- The signed-in Playwright smoke, scheduled smoke runs, alerting, or rollback automation.
- Government cloud delivery.
- Any change to the hosted Bicep, `hosted_demo.py` or the existing release signing path.

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [ ] All clarification questions are decided, not guessed (rows 1, 2, 3 and 6 are assumptions to confirm at plan approval)

## Execution state

| Item | Status | Branch/worktree | Notes |
|---|---|---|---|
| 1 | merged | prp-63-delivery-pipeline | hosted_smoke.py + 9 tests |
| 2 | merged | prp-63-delivery-pipeline | deploy-hosted.yml; actionlint clean |
| 3 | merged | prp-63-delivery-pipeline | delivery.md + mkdocs nav line; operator script temp/setup-delivery-oidc.ps1 parse-checked, not run |
| 4 | merged | prp-63-delivery-pipeline | static tests + release.yml header comment |
| 5 | merged | prp-63-delivery-pipeline | close-out done at landing |

## Completion note
- Date and PR: 2026-11-16, PR #316 (landed by the unattended landing run; CI green, admin squash merge).
- Deviations: (1) the register is NOT persisted as an artifact (clarification 6): it holds full resource ids and artifacts of this public repo are readable by any signed-in GitHub user; an update deploy relies on the Cosmos copy, which needs the Cosmos data-plane role for the delivery identity. UNVERIFIED until PRP-64 compares register rows before and after the first run. (2) the plan hash is read from the plan evidence JSON (`details.plan_sha256`), not a log scrape. (3) the plan-job summary lists change types and resource types only, not resource ids. (4) `mkdocs.yml` got one nav line for `docs/deploy/delivery.md`. (5) Snyk reported 2 low Path Traversal findings on `hosted_smoke.py` (operator-supplied `--result-json` and `GITHUB_STEP_SUMMARY`); accepted, same pattern as the other gate scripts.
- Descoped items: none.
- OPEN gates: first OIDC login, first approved plan and apply, first smoke on the real environment, the exact role list, register correctness without a local export (all PRP-64, need `NS_LIVE_APPROVED=1` and the operator approving `hosted-demo`). Deployed: no, unverified live. Not ticked: the Mermaid render claim, the operator-script box and the actionlint rerun (not re-run at landing), plus the live items above. The workflow triggers only on a pushed v*.*.* tag release (never on push to main), so merging deployed nothing; the two draft rc releases still need an operator decision.
- Env vars for the operator: secrets `NS_AZURE_CLIENT_ID`, `NS_AZURE_TENANT_ID`, `NS_AZURE_SUBSCRIPTION_ID`, `NS_INTEGRATION_SUBNET_ID`, `NS_PE_SUBNET_ID`, `NS_COSMOS_ZONE_ID`, `NS_EVENTHUBS_ZONE_ID`, `NS_BLOB_ZONE_ID`, `NS_WEBAPPS_ZONE_ID`, `NS_KEYVAULT_ZONE_ID`, `NS_ENTRA_TENANT_ID`, `NS_ENTRA_CLIENT_ID`, `NS_COPILOT_ENDPOINT`, `NS_BUDGET_EMAILS`, `NS_TAG_OWNER`, `NS_FOUNDRY_ACCOUNT_IDS`, `NS_BILLING_EXPORT_STORAGE_ID` on both environments `hosted-demo-plan` and `hosted-demo`; optional variables `NS_HOSTED_RESOURCE_GROUP`, `NS_HOSTED_LOCATION`, `NS_HOSTED_PREFIX`, `NS_HOSTED_SKU`, `NS_HOSTED_COPILOT_MODE`, `NS_HOSTED_COPILOT_DEPLOYMENT`, `NS_HOSTED_CONNECTOR_ROLES`, `NS_HOSTED_RECOMMENDATIONS`, `NS_HOSTED_EVAL_DOMAIN_ID`, `NS_HOSTED_EVAL_SUBJECT_ID`, `NS_HOSTED_EVAL_DATASET_IDS`. Operator script: `temp/setup-delivery-oidc.ps1` in the worktree (untracked), run `powershell -NoProfile -File temp/setup-delivery-oidc.ps1 -SubscriptionId <id> -WhatIf` first, then without `-WhatIf`; report back the app display name, roles assigned and secret counts, never values. The two draft rc releases need a decision (publish by hand or let the first run handle rc.2).
- Follow-up issues: none filed.
- Product check: operator can run the pipeline from GitHub without editing files; first-time setup needs the operator script; live run is PRP-64.
