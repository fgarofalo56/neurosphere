---
name: PRP-66-operations-and-sign-off-gates
status: backlog
priority: P1
order: 54
review: required
created: 2026-11-14
model: sonnet
orchestrator_model: sonnet
implementer_model: sonnet
phase: 6
ns: NS-01, NS-05, NS-06, NS-07, NS-08
depends_on: [PRP-21-scale-federation-finops-and-dr, PRP-49-per-agent-aggregates-and-map-metrics, PRP-55-real-deploy-apply, PRP-58-hosted-data-path-and-environment-hardening, PRP-63-delivery-pipeline-to-hosted, PRP-67-hosted-environment-hardening, PRP-84-ingest-throughput-and-autoscaling, PRP-82-hosted-profile-everything-on, PRP-77-live-map-filters-search-and-incident-view, PRP-109-north-star-scenario-acceptance]
wave: W34
branch: prp-66-operations-gates
allow_parallel: true
issues: [268, 39, 40, 108, 124, 144, 179, 148]
---

# PRP-66: Operations and sign-off gates (operator-attended)

## Goal
Run the operations, deploy, performance, hosted and human sign-off gates after the build waves, and record each as evidence or as an honest OPEN with a reason. This is the second half of the former PRP-64 live gates campaign (split on 2026-11-14 because 17 items were too many for one sitting; the Azure service gates stay in PRP-64). Each item names the exact script and arguments, the approval the operator gives, the evidence file under `docs/evidence/` or `docs/accessibility/`, a spend cap and the register row it updates. Items are independent and any may end OPEN; a failed run is committed as a failure, never as a pass. The agent drives and records; the operator approves every billable step, supplies every target name and installs every credential (nothing secret enters the conversation, a file or the repo, which is public). A human, not the agent, signs the accessibility checklists. Government items stay OPEN: there is no Government subscription. This PRP changes no product code; the only code edit allowed is a fix to a gate script that is needed to finish a run, recorded as a deviation.

Out of scope: the Azure service gates (G17 observe and manage, G16, G04, G12, G03, G01 analytics, the Event Hubs SIEM sink, the Bedrock check; all PRP-64); building anything the gates exercise (scripts and features come from PRP-21, 49, 55, 58, 61, 63 and 67); closing G02 or G06 (customer inputs) and the G09 waiver beyond what the signed evidence supports; editing ADRs, capability-matrix data or product docs that a run suggests changing (each becomes a follow-up issue); the shipped PRP-18 text (the map criterion reword lives in evidence and the register only).

## Why
- G07 sized load, failover, failback and restore have never run against a sized environment; #108 is operator-only and the targets are provisional planning targets (`docs/RESEARCH-AND-GATES.md:26-39`; `temp/audit/lane-f-issues-136-220.md:75`).
- Live uninstall (#40) and live deploy apply (PRP-55 script `scripts/gates/deploy_apply_live.py`) are operator-gated by design; apply stays 503 unless opted in.
- The map performance prior runs gave mean 38.6-41.8 fps and p5 24.0-30.0 fps against a single-mean criterion (`docs/evidence/G07/map/README.md`); headless fps is SwiftShader, so only operator hardware can decide it.
- #124 manual accessibility sign-off needs a human tester (`docs/accessibility/tester-runbook.md`); the waiver G09 stays unless the owner lifts it.
- Hosted operator parts: #144 (LAW logs, viewer 403 user, S6 rerun, copilot row, drift and cost), #179 items 3-4, #148 item 6 (`temp/audit/lane-f-issues-136-220.md:21,29,41,75`); #39 needs a Government tenant that does not exist.
- Each gate script refuses without `NS_LIVE_APPROVED=1` before any import or network call (`scripts/gates/hosted_demo.py`, `infra/dr/ns_dr.py`, `infra/scripts/uninstall.py`; the campaign relies on that guard and never bypasses it). The repo is public, so evidence carries no subscription id, tenant id, key, token or private endpoint name.

## Acceptance criteria
- [ ] Every item below ends in exactly one of `PASS`, `FAIL`, `PARTIAL` or `OPEN (not run)` with a one-line reason; its evidence file (or an OPEN note) is committed and its register row is edited to match, citing the file.
- [ ] No evidence file, log or commit contains a subscription id, tenant id, client id, key, token, SAS, connection string or private IP/FQDN; a grep for GUIDs and `Key=`/`Bearer` over the evidence paths returns only tokenised or synthetic values before each commit.
- [ ] Each billable run is preceded by the operator's written approval in the session naming the item, the target, the spend cap and `NS_LIVE_APPROVED=1`; each evidence header records the cap and the spend row (planned versus actual, with the date).
- [ ] Throwaway resource groups are torn down by the script or an operator-approved teardown; orphans are listed; nothing owned by another team is modified; security tooling (Defender-created resources) is never deleted by hand.
- [ ] A gate that did not run stays OPEN and the register row says why (no sized environment, no GPU hardware, no human tester, no Government subscription, dependency PRP not shipped).
- [ ] The map evidence states mean and p5 fps separately, with renderer and hardware recorded; headless SwiftShader numbers are labelled as such and never recorded as a pass.
- [ ] The accessibility sign-off blocks hold tester, date, browser, OS and AT versions dictated by the human; the agent never signs; each FAIL is in `docs/accessibility/remediation-log.md` with an owner.
- [ ] Hosted north-star run (PRP-109): the sign-off list includes the operator-approved hosted run of `frontend/tests/hosted/north-star.spec.ts` against the `governanceProfile=north-star` deployment; it ends in `PASS` with evidence under `docs/evidence/north-star/` or `OPEN (not run)` with the reason; PRP-136 re-runs it later.
- [ ] The register rows listed under Ownership are edited only for facts the evidence shows, in the final item, after PRP-64's register edits; no production, SLA, Government or authorization claim is added.
- PRP exit: the completion note holds a table of every item with outcome, evidence path, spend and register row, and a list of what stays OPEN and what closes each; #40, #108 and #124 may be closed only on PASS (the operator closes issues).

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| 1 | Spend authority | Ask per item; pre-authorized | Azure spend on NeuroSphere is pre-authorized by the owner; each item still states a cap and logs a spend row. The caps below are proposals (ASSUMPTION) the operator confirms or changes at approval |
| 2 | Approval granularity | One for the campaign; per item and per step | Per item, and per step where a script has approval points; `NS_LIVE_APPROVED=1` is set per command, never exported for the session |
| 3 | Order | Fixed; operator's choice | Preflight; sized load and DR; deploy apply then uninstall; map and hosted checks; the human accessibility pass; Government record; register edits last. Any order is allowed if the dependency noted in the item is met |
| 4 | Where a script is delivered by another PRP | Wait; mark OPEN | If that PRP has not shipped, the item is `OPEN (not run)` and says which PRP (PRP-61 detections check is optional) |
| 5 | Running agent versus operator | Agent runs all; operator runs billable steps | The agent prepares `temp/campaign/*.ps1` or `.sh` command files with placeholders filled from operator-supplied names; the operator or the agent runs them only after approval; interactive logins, credential installs and portal steps are the operator's |
| 6 | Evidence spill | One file; per item | One file per run under the gate's directory, never overwriting an earlier run |
| 7 | Split with PRP-64 | One PRP; two PRPs | Two PRPs, PRP-64 in W33 and this PRP in W34, with disjoint evidence paths (see Ownership). Both edit `docs/RESEARCH-AND-GATES.md`, so this PRP's register edits are its final item with `[serial-after: PRP-64]` |
| 8 | #179 item 4 and #148 item 6 | Rerun here; read PRP-64's evidence | Both are answered by the G17 observe run, which PRP-64 item 2 owns. This PRP reads that evidence file and posts the results; if it did not run, both stay OPEN. ASSUMPTION |
| 9 | Tracking issue | Share #258; none | #258 stays with PRP-64. This PRP has no tracking issue of its own; the issue numbers in frontmatter are the operator-only issues it answers. ASSUMPTION |
| 10 | Changelog entry | Edit `CHANGELOG.md`; fragment file | ASSUMPTION: PRP-68 (W11) ships the `changelog.d/` fragment convention first, so this PRP writes `changelog.d/PRP-66.md` (new) and never edits `CHANGELOG.md` |

## Context manifest

### Files to read first
- `docs/RESEARCH-AND-GATES.md:26-39` - the register rows this PRP edits.
- `docs/evidence/G07/map/README.md`, `docs/evidence/G07/load/README.md` - how each gate records evidence.
- `tests/load/profiles/README.md` and `docs/ops/dr-runbook.md` - sized load and DR commands.
- `docs/accessibility/tester-runbook.md` and `docs/accessibility/keyboard-checklist.md` - the human pass.
- `docs/deploy/hosted-demo.md` and `scripts/gates/hosted_demo.py` subcommands - hosted checks.
- The delivered scripts: `scripts/gates/deploy_apply_live.py` (PRP-55), `scripts/gates/hosted_smoke.py` (PRP-63); run each with `--help` first and paste the usage into the evidence.
- The Execution state and completion notes of PRP-21, 49, 55, 58, 63 and 67 for env var lists.

### Interfaces consumed
- Scripts and tests already in the repo: `scripts/gates/hosted_demo.py`, `infra/scripts/uninstall.py`, `infra/dr/ns_dr.py`, `tests/load/profiles/run_profile.py`, `frontend/tests/e2e/map-perf.spec.ts`, `frontend/playwright.hosted.config.ts`.
- From other PRPs: `deploy_apply_live.py` and the apply opt-in (PRP-55), `hosted_smoke.py` and the deploy workflow (PRP-63), `docs/evidence/G07/pilot/` and the load profiles (PRP-21), subject metrics on the map (PRP-49), the hosted data path (PRP-58), hosted hardening and the viewer 403 case (PRP-67), the `detections` role (PRP-61, optional).
- From PRP-64: the G17 observe evidence file, read for #179 item 4 and #148 item 6.
- Environment variables named in each item; values come from the operator.

### Interfaces provided
- Evidence files under `docs/evidence/G07/{load,map,dr,finops}/`, `docs/evidence/G01/uninstall-live-*` and `deploy-apply-live-*`, `docs/evidence/PRP-32/hosted-checks-*`, the filled checklists under `docs/accessibility/`, the register rows and the OPEN list (including the Government record).

### Patterns to match
- `docs/evidence/G17/observe-20261106T203521Z.md` (whitelisted fields, tokenised ids, outcome and teardown recorded).
- `docs/evidence/PRP-25/docs-assistant-live-smoke-2026-11-14.md` (cap and spend line in the header).
- `docs/evidence/G01/2026-10-17-commercial-deploy-smoke.md` (a live deploy narrative with teardown).

### Gotchas
- `MSYS_NO_PATHCONV=1` for `az` commands and `uv run` with `/subscriptions/...` arguments; not for `pnpm`.
- Memory notes to honour: RG tag policy requires `project` and `owner` tags; Limitlessdata subscriptions only; never touch another team's resources; DMLZ forces Cosmos private (private endpoint plus P2S VPN, `Resolve-DnsName` not `nslookup`).
- Defender for Storage auto-creates an Event Grid topic that blocks teardown of storage accounts (#144): never delete security tooling by hand; report the leftover.
- Do not run `docker compose` or `make stack-up` in two sessions at once; Playwright needs unique `NS_E2E_APP_PORT` and `NS_MOCK_API_PORT`.
- Do not read `.env*`; the operator exports secrets (including `NS_LOAD_CREDENTIALS_JSON`) into their own shell; the agent verifies presence with `printenv NAME | wc -c` style checks only.
- Exit code 2 means refused and nothing ran; do not retry a refusal with a weaker flag. No polling loops: wait once with a bounded timeout.

Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - docs/evidence/G01/uninstall-live-*
  - docs/evidence/G01/deploy-apply-live-*
  - docs/evidence/G07/load/**
  - docs/evidence/G07/map/**
  - docs/evidence/G07/dr/**
  - docs/evidence/G07/finops/**
  - docs/evidence/G07/pilot/**
  - docs/evidence/G07/ingest/real-azure-*
  - docs/evidence/hosted/live-*
  - docs/evidence/PRP-32/hosted-checks-*
  - docs/accessibility/**
  - frontend/tests/e2e/map-perf.spec.ts
  - changelog.d/PRP-66.md
tier1: []
tier2_appends:
  - docs/RESEARCH-AND-GATES.md
must_not_touch:
  - docs/evidence/G01/analytics/**
  - docs/evidence/G03/**
  - docs/evidence/G04/**
  - docs/evidence/G07/siem/**
  - docs/evidence/G12/**
  - docs/evidence/G16/**
  - docs/evidence/G17/**
  - packages/**
  - services/**
  - frontend/src/**
  - infra/**
  - connectors/**
  - .github/**
  - pyproject.toml
  - uv.lock
```
Register rows this PRP edits in `docs/RESEARCH-AND-GATES.md`, only in item 12 and only after PRP-64's edits: G07 (load, failover, restore, map; not the SIEM sentence), G01 (deploy and uninstall sentences; not the analytics sentence), G09, the Government rows and notes on G12 and G17 for the hosted checks. PRP-64 owns G17, G16, G04, G12, G03 and the G01 analytics and G07 SIEM sentences.

## Implementation blueprint

Every item is independent and operator-attended: the dependency noted is a shipped PRP or an earlier item's output, not a shared file. Commands use placeholders in angle brackets; the operator supplies values. Outcome for each is PASS, FAIL, PARTIAL or OPEN.

### Item 1 - Preflight and approval sheet
- Deliverable: confirm the delivered scripts exist and print `--help` (PRP-55 and 63 files above); check `az account show` is the Limitlessdata target and `AzureCloud`; write `temp/campaign/approvals-ops.md` (one block per item: target, cap, approval line) for the operator; record the baseline of `git status` and the open-issue states of #39, #40, #108, #124.
- Owned files: none committed (temp only).
- Acceptance criteria: a table of item to script presence; missing scripts mark their items `OPEN (not run)` up front.
- Tests: none; evidence is the command output pasted in the completion note.

### Item 2 - G07 sized load, failover, restore (#108)
- Commands: `uv run python tests/load/profiles/run_profile.py enterprise --host <https ingest URL> --environment-label "<sized environment>" --evidence-dir docs/evidence/G07/load` with `NS_LOAD_CREDENTIALS_JSON` supplied by the operator in their shell; the stress profile the same way only if the operator names a sized target; restore drill against a named non-local target: `NS_LIVE_APPROVED=1 uv run python infra/dr/ns_dr.py restore --from <dir> --database <db> --cosmos-container <c> --blob-container <b> --target <name> --confirm-target <name>`; Event Hubs failover and failback, geo-replication, an AI Search rebuild and a production-sized restore follow `docs/ops/dr-runbook.md` step by step with the operator at the portal; invoiced-cost evidence regenerates `docs/evidence/G07/finops/` through the entry point `finops/__main__.py` against real invoiced data.
- Approval: a named sized environment, load duration, and a hard stop; compare against `docs/evidence/G07/pilot/` (PRP-21). Spend cap (proposed, operator sets): USD 150 hard stop; no run starts without a named target.
- Evidence: `docs/evidence/G07/{load,dr,finops}/` new dated files. Register row: G07. This item is expected to end PARTIAL or OPEN; targets are provisional planning targets, never guarantees.

### Item 3 - Live deploy apply (PRP-55)
- Depends on: PRP-55 shipped, API and worker with the apply opt-in (`NS_DEPLOY_APPLY_ENABLED` and the register container setting), a throwaway resource group.
- Command: `NS_LIVE_APPROVED=1 uv run python scripts/gates/deploy_apply_live.py <arguments from its --help>`; the operator approves the plan digest as the second approver.
- Evidence: `docs/evidence/G01/deploy-apply-live-<UTC>.md` (plan digest, applied resources, verify result, teardown). Spend cap: USD 10. Register row: G01 (deploy). Ends OPEN when the apply path is not opted in.

### Item 4 - Live uninstall (#40)
- Depends on: a throwaway resource group deployed by item 3 or by the G01 smoke, with a register export and a planted foreign resource.
- Command: `NS_LIVE_APPROVED=1 uv run python infra/scripts/uninstall.py --export <register.json> --confirm <deployment id>`; first `--dry-run --verify-live`.
- Approval: real ARM deletes in the throwaway group only; the planted foreign resource must block the group delete. Spend cap: USD 5. Evidence: `docs/evidence/G01/uninstall-live-<UTC>.md`. Register row: G01 (deploy). Closes #40 only on PASS (operator closes the issue).

### Item 5 - Map performance re-measure and hosted node metrics
- Command: on the documented operator workstation: `NS_MAP_PERF_HEADED=1 NS_MAP_PERF_ENFORCE=1 NS_E2E_APP_PORT=5301 NS_MOCK_API_PORT=5302 pnpm --filter @neurosphere/frontend exec playwright test tests/e2e/map-perf.spec.ts --project=chromium`, three runs; the spec writes `temp/map-perf/fps.json`, copied to `docs/evidence/G07/map/fps-run<N>.json` with renderer and hardware recorded.
- Also: after PRP-49 and PRP-58, open the hosted `/map` and record whether agent and model nodes show live per-node metrics (unknown shown as unknown); screenshot without ids.
- Criterion reword (the PRP-18 target was a single mean figure; the prior runs gave mean 38.6-41.8 and p5 24.0-30.0 fps): state mean and p5 separately in `docs/evidence/G07/map/README.md` and the G07 row; do not edit the shipped PRP. Spend cap: USD 0. Ends OPEN when no GPU hardware is available (headless SwiftShader numbers are recorded as such, never as a pass).

### Item 6 - Hosted operator checks (#144, #179 items 3-4, #148 item 6, PRP-61 optional)
- Depends on: PRP-58, PRP-63 and PRP-67 (hosted environment current).
- Steps: `NS_LIVE_APPROVED=1 uv run python scripts/gates/hosted_demo.py status --subscription <sub>` (drift and delete-after); `... smoke --subscription <sub>`; confirm App Service logs reach the workspace (`AppServiceConsoleLogs`, `AppServiceHTTPLogs`, `AppServicePlatformLogs`) and diagnose if empty; grant a Viewer principal with `seed-access --grant --principal <object id>` and confirm the 403 case in the hosted Playwright run (`frontend/playwright.hosted.config.ts`), then revoke; rerun S6 seed-access; confirm the copilot `approved_endpoint` register row and the `NS_COPILOT_MODEL_FEATURE`/SKU values; if PRP-61 shipped, one operator-approved read-only run of the `detections` role against a named subscription (Reader only) and record findings count only.
- Issue answers: read PRP-64's G17 observe evidence and record #179 item 4 (does the `Subscription ID` customMetrics dimension equal `ApimSubscriptionId`) and #148 item 6 (observe rerun result) in the hosted-checks file; #179 item 3 (Government Application Insights host) is OPEN via item 8. If PRP-64 item 2 did not run, both stay OPEN.
- Evidence: `docs/evidence/PRP-32/hosted-checks-<UTC>.md` (new file; the directory is PRP-58's, this file is additive only). Spend cap: USD 10 incremental. Register rows: none beyond G12/G17 notes (edited in item 9); follow-up issues for anything found.

### Item 7 - Manual accessibility sign-off (#124)
- A human tester, not the agent, follows `docs/accessibility/tester-runbook.md` (about 45-60 minutes): keyboard pass in light and high-contrast, NVDA 2026.2 plus Narrator or VoiceOver; the agent opens the sign-off blocks, records tester, date, browser, OS and AT versions the human dictates, and logs each FAIL in `docs/accessibility/remediation-log.md` with an owner. An agent never signs.
- Evidence: the filled checklists under `docs/accessibility/`. Register row: G09 (waiver stays unless the owner lifts it; signing is evidence, not a conformance claim). Spend: none. Ends OPEN when no human tester is available.

### Item 8 - Government items stay OPEN
- Record in the register and the completion note, with no script run: #39 (needs a GCC High tenant); G02 profile runs `g02_profile_aks.py` and `g02_profile_appservice.py` (need `NS_GOV_SUBSCRIPTION_ID` and registry variables the owner cannot supply); #213 item 3 (Government what-if); #179 item 3 (Government Application Insights host); Fabric, Synapse and Databricks Government rows; Government Event Hubs geo-replication. Reason for each: no Government subscription; availability is not authorization.
- Spend: none. Outcome: `OPEN (not run)` for every row.

### Item 9 - Real-Azure ingest runs at 1k and 10k events/s (PRP-84)
- Depends on: PRP-84 shipped (runner `tests/load/ingest_e2e/run_ingest_e2e.py`, runbook `docs/runbooks/ingest-scaling.md`, Helm or App Service autoscaling values), a named sized environment, the hosted data path (PRP-58).
- Commands (exact flags are in the runbook and `--help`): `NS_LIVE_APPROVED=1 uv run python tests/load/ingest_e2e/run_ingest_e2e.py pilot-1k --host <https ingest URL>` and then `enterprise-10k` with the same shape; producer credentials come from `NS_LOAD_CREDENTIALS_JSON` in the operator's shell, never in chat.
- Approval: a named environment, duration and hard stop for each profile; 10k only after 1k passed. Spend cap (proposal, operator sets): USD 50 for 1k, USD 150 for 10k (hard stop). Evidence: `docs/evidence/G07/ingest/real-azure-<profile>-<UTC>.{md,json}` (schema `ingest-e2e/v1`; new files beside PRP-84's local evidence, which stays untouched). Register row: G07 (ingest sentence).
- Expected PARTIAL or OPEN; a result below target is recorded as measured. Ends OPEN when no sized environment is named.

### Item 10 - Hosted "everything on" deploy and signed-in smoke (PRP-82)
- Depends on: PRP-82 shipped (`hostedProfile = 'everything-on'`, `scripts/gates/hosted_profile_evidence.py`, `docs/deploy/hosted-everything-on.md`), PRP-63 deploy pipeline, PRP-67 teardown, an approved Foundry deployment for `copilotEndpoint`.
- Steps: follow `docs/deploy/hosted-everything-on.md` in order (VPN, plan, approval, deploy through the pipeline, grant, seed, sign-in, nav walk, revoke, teardown or keep); `NS_LIVE_APPROVED=1`; the operator signs in with MFA in a headed browser, the agent never sees a credential.
- Approval: the plan digest, the environment and the spend row. Spend cap (proposal, operator sets): USD 40 incremental. Evidence: `docs/evidence/hosted/live-<yyyy-mm-dd>-<image-tag>/` in the layout PRP-82 documents, accepted by `hosted_profile_evidence.py`. Register row: none beyond the G12 and G17 notes edited in the close-out; follow-up issues for anything found.
- Ends OPEN when no approval or no endpoint is given.

### Item 11 - Live map interaction-latency re-measure (PRP-77)
- Depends on: PRP-77 shipped (`frontend/tests/e2e/map-latency.spec.ts`, schema in `docs/runbooks/live-map.md`), a documented operator workstation; the hosted `/map` if PRP-82 ran.
- Command: the spec command in the live-map runbook with `NS_MAP_PERF_HEADED=1`, unique `NS_E2E_APP_PORT` and `NS_MOCK_API_PORT`, three runs; copy the result to `docs/evidence/G07/map/interaction-latency-operator-run<N>.json` with renderer and hardware recorded (headless SwiftShader numbers are labelled, never a pass).
- Approval: none beyond the workstation session. Spend cap: USD 0. Register row: G07 (map sentence, with the item 5 fps figures). Ends OPEN when no GPU hardware is available.

### Item 11b - Hosted north-star run (PRP-109)
- Depends on: PRP-109 shipped (the hosted governance profile and `frontend/tests/hosted/north-star.spec.ts`), PRP-63's pipeline, the hosted environment of PRP-82.
- Command: the deploy pipeline run with `governance_profile=north-star` and the spec, as the PRP-109 runbook (`docs/demo/north-star.md`) lists; synthetic content only, the capture policy scoped to the demo domain.
- Approval: the operator's written approval in the session naming the environment; `NS_LIVE_APPROVED=1`; spend row and cap as for the other live items. Evidence: `docs/evidence/north-star/`. No new register row (the Ownership row list is unchanged); the result goes in the completion note table. Ends OPEN when not run.

### Item 12 - Integration and close-out  [serial-after: PRP-64]
- Deliverable: after PRP-64's close-out has merged (both edit the one register file; PRP-64 merges a wave earlier, W33), edit only the register rows listed under Ownership, in one close-out commit, plus the Government record from item 8; write `changelog.d/PRP-66.md`; regenerate `PRPs/INDEX.md` and the status table (`python scripts/prp_status.py --write`); fill the completion note table (item, outcome, evidence, spend, row); file follow-up issues; tell the operator which issues may be closed (#40, #108, #124 only on PASS).
- Owned files: `docs/RESEARCH-AND-GATES.md` (rows listed under Ownership only), `changelog.d/PRP-66.md` (new), this PRP file.
- Acceptance criteria: every item has an outcome row; no register row outside this PRP's list is touched; the GUID grep in Validation gates is clean.
- Tests: `uv run pytest -q tests/unit/gates tests/docs`.

## Validation gates
```bash
python scripts/validate_planning.py
uv run pytest -q tests/unit/gates tests/docs
python scripts/prp_status.py --check
git grep -nE "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}" -- docs/evidence docs/accessibility
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```
The `git grep` must show only tokenised, synthetic or pre-existing values; review every hit before committing. Each live item has its own command in its section; none runs in CI.

## Migration and rollback
No data or schema migration. Live runs create and delete throwaway Azure resources in operator-approved groups; rollback of a run is its teardown. Evidence and register edits roll back with `git revert`. A wrong register edit is corrected by a new commit that cites the evidence, not by deleting evidence.

## Live and open gates
Everything here is live, operator-gated or human-gated. Required for any billable run: `NS_LIVE_APPROVED=1` on that command, the operator's approval naming target and cap, and operator-installed credentials. Expected to stay OPEN without further input: Government rows (no subscription), enterprise and stress load (no sized environment), the map criterion on GPU hardware (no hardware named), the accessibility sign-off (no human tester scheduled), the detections check (PRP-61 not shipped or not approved), anything whose delivering PRP has not shipped. The Azure service gates are PRP-64.

## NOT building
Product code, new gate scripts beyond a fix needed to finish a run, new infrastructure, ADR or capability-matrix edits, Government runs, PII or production data in any run, an agent signing an accessibility checklist, automatic scheduling of live gates, and any claim of SLA, production readiness, compliance or authorization.

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references (commands and evidence paths per item; `Owned files` are evidence paths)
- [x] Gates are executable commands, not intentions
- [x] All clarification questions are decided, not guessed (spend caps and rows 8-10 are flagged ASSUMPTIONS for the operator)

## Execution state

| Item | Status | Branch/worktree | Notes |
|---|---|---|---|
| 1 | todo | | |
| 2 | todo | | |
| 3 | todo | | |
| 4 | todo | | |
| 5 | todo | | |
| 6 | todo | | |
| 7 | todo | | |
| 8 | todo | | |
| 9 | todo | | |
| 10 | todo | | |
| 11 | todo | | |
| 11b | todo | | PRP-109 hosted north-star run |
| 12 | todo | | serial-after PRP-64 |

## Completion note (filled at ship)
- Date, PR number, merge commit:
- Deviations (including any gate-script fix):
- Descoped items:
- OPEN gates (with reason and what closes each):
- Outcome table (item, outcome, evidence path, spend cap versus actual, register row):
- Env vars for the operator:
- Follow-up issues filed:
- Operator product check (can an operator run and read every gate without editing files?):
