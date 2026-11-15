---
name: PRP-64-live-gates-campaign
status: backlog
priority: P1
order: 52
review: required
created: 2026-11-14
model: sonnet
orchestrator_model: sonnet
implementer_model: sonnet
phase: 6
ns: NS-01, NS-05, NS-06, NS-07, NS-08
depends_on: [PRP-11-analytics-adapters, PRP-40-audit-search-export-and-siem-sink, PRP-58-hosted-data-path-and-environment-hardening, PRP-62-aws-bedrock-reference-connector]
wave: W21
branch: prp-64-live-gates
allow_parallel: true
issues: [258, 57]
---

# PRP-64: Live gates campaign, Azure service gates (operator-attended)

## Goal
Turn the open Azure service gates in `docs/RESEARCH-AND-GATES.md` into evidence, or into an honest OPEN with a reason, in one operator-attended session after the build waves. Each item runs one gate: the exact script and arguments, the approval the operator gives, the evidence file it writes under `docs/evidence/`, a spend cap and the register row it updates. Items are independent and any of them may end OPEN; a run that failed is committed as a failure, never as a pass. The agent drives and records; the operator approves every billable step, supplies every target name and installs every credential (nothing secret ever enters the conversation, a file or the repo, which is public). This PRP changes no product code; the only code edit allowed is a fix to a gate script that is needed to finish a run, recorded as a deviation. This PRP was split on 2026-11-14: the operations and sign-off gates moved to PRP-66.

Out of scope: building anything the gates exercise (the scripts and features come from PRP-11, 40, 58 and 62); G07 sized load, failover and restore, live uninstall, live deploy apply, the map performance re-measure, the accessibility sign-off, the hosted operator checks and the Government OPEN record (all PRP-66); closing G02, G06 or G09 beyond what evidence supports (G02 and G06 need customer inputs; G09 is waived); editing ADRs, capability-matrix data or product docs that a run suggests changing (each becomes a follow-up issue); the register's three stale rows (PRP-36 fixes them before this PRP, item 1 re-checks); G05 second target and model pair (no PRP assigns it; optional later).

## Why
- The register still lists G01, G03, G04, G12, G16 and G17 as OPEN or NARROWED with named live items (`docs/RESEARCH-AND-GATES.md:26-39`), and nothing has run live since 2026-11-06 except the docs-assistant smoke (`temp/audit/lane-d-replan-gaps.md` section 2).
- G17 observe passed phases 1-4 live on 2026-11-06 but never observed the joined gateway and LLM log row within 20 minutes; the next run must use `--budget-minutes 45` (`docs/evidence/G17/observe-20261106T203521Z.md`, register row G17); manage has never run.
- #57 (in-region G03) is operator-only (`temp/audit/lane-f-issues-136-220.md:75` lists the operator parts).
- Each script already refuses without `NS_LIVE_APPROVED=1` before any import or network call (`scripts/gates/g17_apim_observe_live.py:1012`, `g16_judge_live.py:83`, `g03_live.py:40`, `g01_analytics_live.py:950`); the campaign relies on that guard and never bypasses it.
- The repo is public, so evidence must carry no subscription id, tenant id, key, token or private endpoint name (`PRPs/backlog/PRP-55-real-deploy-apply.md` gotcha; G01 evidence tokenises ids).

## Acceptance criteria
- [ ] Every item below ends in exactly one of `PASS`, `FAIL`, `PARTIAL` or `OPEN (not run)` with a one-line reason; its evidence file (or an OPEN note) is committed and its register row is edited to match, citing the file.
- [ ] No evidence file, log or commit contains a subscription id, tenant id, client id, key, token, SAS, connection string or private IP/FQDN; a grep for GUIDs and `Key=`/`Bearer` over `docs/evidence/**` returns only tokenised or synthetic values before each commit.
- [ ] Each run is preceded by the operator's written approval in the session naming the item, the target, the spend cap and `NS_LIVE_APPROVED=1`; each run's evidence header records the cap and the spend row (planned versus actual, from the script or the portal, with the date).
- [ ] Throwaway resource groups are torn down by the script or by an agent-run teardown the operator approves; orphans are listed in the evidence; nothing owned by another team is modified (Loom and other Foundry accounts are never touched; targets are Limitlessdata subscriptions only).
- [ ] A gate that did not run stays OPEN and the register row says why (no AWS account, no namespace or warehouse approved, dependency PRP not shipped).
- [ ] The register rows for G01 (analytics sentence), G03, G04, G12, G16, G17 and the G07 row's SIEM sentence are edited only for facts the evidence shows; "PASS" for one script never widens a claim (no production, SLA, Government or authorization claim).
- [ ] Any gate-script fix made to finish a run is minimal, covered by the script's existing unit tests (`tests/unit/gates/`), and listed under Deviations.
- PRP exit: the completion note holds a table of every item with outcome, evidence path, spend and register row, and a list of what stays OPEN and what is needed to close it.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| 1 | Spend authority | Ask per item; pre-authorized | Azure spend on NeuroSphere is pre-authorized by the owner; each item still states a cap and logs a spend row. The caps below are proposals (ASSUMPTION) the operator confirms or changes at approval |
| 2 | Approval granularity | One for the campaign; per item and per step | Per item, and per step where a script has approval points (`--approve-step`, `--approve-rbac`); `NS_LIVE_APPROVED=1` is set per command, never exported for the session |
| 3 | Order | Fixed; operator's choice | Preflight first; then G17 observe before manage; G16, G04, G12; SIEM sink, G03, G01. Any order is allowed if the dependency noted in the item is met |
| 4 | Where a script is delivered by another PRP | Wait; mark OPEN | If that PRP has not shipped, the item is `OPEN (not run)` and says which PRP (PRP-62 is optional: Bedrock only runs if an AWS account is named) |
| 5 | Items needing a script that does not exist | Write one; do it by hand | SIEM sink check has no script: run the documented manual procedure; adding a script under `scripts/gates/` is allowed only as a gate-script addition recorded as a deviation. ASSUMPTION |
| 6 | Running agent versus operator | Agent runs all; operator runs billable steps | The agent prepares `temp/campaign/*.ps1` or `.sh` command files with placeholders filled from operator-supplied names; the operator or the agent runs them only after approval; interactive logins and credential installs are the operator's |
| 7 | Evidence spill | One file; per item | One file per run under the gate's directory, never overwriting an earlier run |
| 8 | Split with PRP-66 | Keep one PRP; two PRPs | Two PRPs in W21 (17 items were too many for one sitting). Evidence directories are disjoint (see Ownership); both edit `docs/RESEARCH-AND-GATES.md`, so PRP-66's register edits are its final item and run after this PRP's. The G17 observe run also answers #179 item 4 and #148 item 6; PRP-66 posts those answers from this PRP's evidence file |
| 9 | Changelog entry | Edit `CHANGELOG.md`; fragment file | ASSUMPTION: PRP-68 (W11) ships the `changelog.d/` fragment convention first, so this PRP writes `changelog.d/PRP-64.md` (new) and never edits `CHANGELOG.md` |

## Context manifest

### Files to read first
- `docs/RESEARCH-AND-GATES.md:26-39` - the register rows this PRP edits.
- `docs/evidence/G17/README.md`, `docs/evidence/G05/README.md`, `docs/evidence/G16/README.md` - how each gate records evidence.
- `scripts/gates/{g17_apim_observe_live.py,g17_apim_manage_live.py,g16_judge_live.py,g03_live.py,g01_analytics_live.py}` docstrings - arguments and exit codes (0 pass, 1 fail, 2 refused, 3 teardown failure for G17).
- The delivered scripts: `scripts/gates/g04_connectors_live.py` (PRP-58), `connectors/reference/aws-bedrock/scripts/live_check.py` (PRP-62); run each with `--help` first and paste the usage into the evidence.
- The Execution state and completion notes of PRP-11, 40, 58 and 62 for env var lists.

### Interfaces consumed
- Scripts and tests already in the repo: `scripts/gates/{g17_apim_observe_live,g17_apim_manage_live,g16_judge_live,g03_live,g01_analytics_live}.py`, `tests/integration/ingestion/test_live_commercial.py`.
- From other PRPs: `g04_connectors_live.py` (PRP-58), the Databricks executor in core and the refactored `g01_analytics_live.py` (PRP-11), the Event Hubs SIEM sink and `GET /api/v1/audit/siem/status` (PRP-40), the Bedrock live check (PRP-62, optional).
- Environment variables named in each item; values come from the operator.

### Interfaces provided
- Evidence files under `docs/evidence/G01/analytics/`, `G03/`, `G04/` (new), `G07/siem/` (new), `G12/ingestion/` (new), `G16/`, `G17/` and the register rows; the OPEN list that any later PRP or the owner can read.

### Patterns to match
- `docs/evidence/G17/observe-20261106T203521Z.md` and `docs/evidence/G05/20261105T173214Z-foundry-swap-live.json` (whitelisted fields, tokenised ids, outcome and teardown recorded).
- `docs/evidence/PRP-25/docs-assistant-live-smoke-2026-11-14.md` (cap and spend line in the header).
- `docs/evidence/G03/live-2026-10-17.md` (an operator-approved live run narrative with limits stated).

### Gotchas
- `MSYS_NO_PATHCONV=1` for `az` commands and `uv run` with `/subscriptions/...` arguments (the G17 scripts set it themselves); not for `pnpm`.
- Memory notes to honour: RG tag policy requires `project` and `owner` tags (pass `--tag`); Limitlessdata subscriptions only; deprecated Foundry models fail deploys; never touch another team's Foundry account; DMLZ forces Cosmos private (private endpoint plus P2S VPN, `Resolve-DnsName` not `nslookup`); the operator machine cannot resolve `api.loganalytics.io`, so G17 queries through ARM.
- Do not run `docker compose` or `make stack-up` in two sessions at once (G17 manage may need a composed API).
- Do not read `.env*`; the operator exports secrets into their own shell; the agent verifies presence with `printenv NAME | wc -c` style checks only, never prints values.
- Run exit codes matter: 2 means refused and nothing ran; do not retry a refusal with a weaker flag.
- No polling loops: wait once with a bounded timeout or use the script's own budget.

Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - docs/evidence/G01/analytics/**
  - docs/evidence/G03/**
  - docs/evidence/G04/**
  - docs/evidence/G07/siem/**
  - docs/evidence/G12/ingestion/**
  - docs/evidence/G16/**
  - docs/evidence/G17/**
  - changelog.d/PRP-64.md
tier1: []
tier2_appends:
  - docs/RESEARCH-AND-GATES.md
must_not_touch:
  - docs/evidence/G01/uninstall-live-*
  - docs/evidence/G01/deploy-apply-live-*
  - docs/evidence/G07/load/**
  - docs/evidence/G07/map/**
  - docs/evidence/G07/dr/**
  - docs/evidence/G07/finops/**
  - docs/evidence/G07/pilot/**
  - docs/evidence/PRP-32/**
  - docs/accessibility/**
  - frontend/tests/e2e/map-perf.spec.ts
  - packages/**
  - services/**
  - frontend/src/**
  - infra/**
  - connectors/**
  - .github/**
  - pyproject.toml
  - uv.lock
```
Register rows this PRP edits in `docs/RESEARCH-AND-GATES.md`: G17 (observe, manage), G16, G04, G12, G03, G01 (analytics sentence only) and one sentence in the G07 row for the SIEM sink. PRP-66 edits G01 (deploy sentence), G07 (load, DR, map), G09 and the Government rows; its register item runs after this PRP's.

## Implementation blueprint

Every item is independent and operator-attended: the dependency noted is a shipped PRP or an earlier item's output, not a shared file. Commands use placeholders in angle brackets; the operator supplies values. Outcome for each is PASS, FAIL, PARTIAL or OPEN.

### Item 1 - Preflight and approval sheet
- Deliverable: confirm the delivered scripts exist and print `--help` (PRP-58 and 62 files above); re-check the register's three stale rows are fixed by PRP-36 (G16 "also OPEN" text, "No live evidence exists" for PRP-32, G06 durable stores) and report if not; check `az account show` is the Limitlessdata target and `AzureCloud`; write `temp/campaign/approvals.md` (one block per item: target, cap, approval line) for the operator; record the baseline of `git status` and the open-issue state of #57.
- Owned files: none committed (temp only).
- Acceptance criteria: a table of item to script presence; missing scripts mark their items `OPEN (not run)` up front.
- Tests: none; evidence is the command output pasted in the completion note.

### Item 2 - G17 observe rerun
- Command: `NS_LIVE_APPROVED=1 uv run python scripts/gates/g17_apim_observe_live.py --subscription <limitlessdata-sub> --location centralus --foundry-endpoint <https URL of a FRESH Foundry account> --foundry-deployment <deployment> --budget-minutes 45 --approve-rbac --purge --tag project=neurosphere --tag owner=<alias>`.
- Approval: create a resource group, Log Analytics workspace and Standard v2 APIM; one paid chat completion; RBAC write on the Foundry account (separate `--approve-rbac`); teardown after. Fresh account, not one owned by others.
- Evidence: `docs/evidence/G17/observe-<UTC>.{md,json}`. Spend cap (proposed): USD 25.
- Register row: G17 (observe). Also records #179 item 4 (does the `Subscription ID` customMetrics dimension equal `ApimSubscriptionId`) and #148 item 6 (PRP-66 posts these two answers on the issues from this evidence file).
- Ends OPEN when phase 5 (joined gateway and LLM row) is not observed in 45 minutes; record table-versus-row state.

### Item 3 - G17 manage
- Depends on: item 2 PASS (or PARTIAL with phases 1-4) and a running NeuroSphere API with `NS_APIM_ENABLED=true` and the worker running (compose or hosted), plus a Grant entity, an McpServer entity, a throwaway streamable-HTTP echo backend (`--print-echo-server` prints one) and two operator tokens in `NS_G17_API_TOKEN` and `NS_G17_APPROVER_TOKEN`.
- Command: `NS_LIVE_APPROVED=1 uv run python scripts/gates/g17_apim_manage_live.py --subscription <sub> --api-url <url> --domain <domain id> --grant-entity-id <id> --mcp-entity-id <id> --mcp-backend-url <url> --mcp-audience <app id uri> --budget-minutes 30 --state-file temp/campaign/g17-manage-state.json --tag project=neurosphere --tag owner=<alias> --approve-step provision --approve-step diagnostics ...` (one `--approve-step` per step the operator approves; steps listed in the script docstring).
- Evidence: `docs/evidence/G17/manage-<UTC>.{md,json}`. Spend cap (proposed): USD 40. Register row: G17 (manage).
- Ends OPEN when any step is unapproved or fails; resumable through the state file. The reused Loom APIM is never a target.

### Item 4 - G16 judge live
- Command: `NS_LIVE_APPROVED=1 NS_CLOUD=commercial NS_G16_JUDGE_ENDPOINT=<https endpoint> NS_G16_JUDGE_DEPLOYMENT=<deployment> uv run python scripts/gates/g16_judge_live.py` (optional `NS_G16_JUDGE_API_VERSION`).
- Approval: one paid judge call on an approved account with a small budget (script scores one synthetic request). Exit 3 means OPEN, not failure.
- Evidence: write `docs/evidence/G16/live-<UTC>.md` from the printed whitelisted fields (verdict kind, token counts). Spend cap: USD 5. Register row: G16.
- Ends OPEN when the endpoint is not approved; the broader live evaluation loop stays out of scope.

### Item 5 - G04 connectors live (Azure Monitor, Foundry discovery, billing; Bedrock optional)
- Depends on: PRP-58 (`scripts/gates/g04_connectors_live.py`), PRP-62 for Bedrock.
- Command: `NS_LIVE_APPROVED=1 uv run python scripts/gates/g04_connectors_live.py <arguments from its --help>` for Limitlessdata targets; Bedrock only if the owner names an AWS account: `NS_LIVE_APPROVED=1 uv run python connectors/reference/aws-bedrock/scripts/live_check.py <arguments from its --help>` with a read-only AWS role the operator installed (never a key in the chat).
- Evidence: `docs/evidence/G04/<connector>-<UTC>.{md,json}` (new directory; one file per connector, result per coverage-table row). Spend cap: USD 10 Azure, plus the Cost Explorer request cost (page cap stated in the evidence) for Bedrock.
- Register row: G04 and the status line in `docs/connectors/coverage.md` is a follow-up issue (not edited here). Ends OPEN per connector that did not run; Government OPEN.

### Item 6 - G12 PRP-07 live Commercial ingestion
- Command: `NS_LIVE_APPROVED=1 NS_LIVE_EVENTHUBS_NAMESPACE=<namespace> NS_LIVE_COSMOS_ACCOUNT=<account> uv run pytest -q tests/integration/ingestion/test_live_commercial.py` (Entra auth; the operator holds the data-plane roles).
- Evidence: `docs/evidence/G12/ingestion/live-<UTC>.md` with the pytest output, the emulator-versus-live deltas observed (auth, RU, partitioning) and teardown. Spend cap: USD 5. Register row: G12.
- Ends OPEN when a namespace or account is not approved; a skipped test is OPEN, never PASS.

### Item 7 - Live SIEM sink (PRP-40)
- Depends on: PRP-40 shipped and a composed or hosted API.
- Procedure (no script exists; ASSUMPTION: manual): operator sets `NS_AUDIT_SIEM_SINK=eventhubs`, `NS_AUDIT_SIEM_EVENTHUBS_NAMESPACE`, `NS_AUDIT_SIEM_EVENTHUBS_NAME` on the API with a managed identity holding Azure Event Hubs Data Sender; performs one audited action (an allowed read plus one denial); the agent reads `GET /api/v1/audit/siem/status` (last success, failures) and the operator confirms the events arrived with an Event Hubs data viewer or `az eventhubs`; teardown of any new hub.
- Evidence: `docs/evidence/G07/siem/live-<UTC>.md` (event count, status body with ids tokenised, time to arrival). Spend cap: USD 5. Register row: none exists for the sink, add one line to the G07 row's text.
- Ends OPEN when no namespace is approved; Government OPEN.

### Item 8 - G03 in-region run (#57)
- Command: from a host inside the VNet (operator workstation on the P2S VPN, or a short-lived job in the internal Container Apps environment): `NS_LIVE_APPROVED=1 NS_G03_COSMOS_ENDPOINT=<https://account.documents.azure.com:443/> NS_G03_RESOURCE_GROUP=<rg> NS_G03_SUBSCRIPTION=<guid equal to az account show> NS_G03_ACCOUNT_SKU=<sku> NS_G03_ACCOUNT_REGION=<region> uv run python scripts/gates/g03_live.py --out-dir docs/evidence/G03 --iterations 30 --operator <name> --region-label <region>`.
- Approval: a throwaway Cosmos account (serverless, Entra only); the ACR path needs the VPN or an agent pool if a job is used. Spend cap: USD 10. Evidence: `docs/evidence/G03/live-<date>.{md,json}`. Register row: G03.
- Findings that would change ADR-0005 or the capability-matrix row (`cosmos.yaml` hierarchical keys) are filed as follow-up issues, not edited here. Ends OPEN when no in-VNet host exists.

### Item 9 - G01 analytics per adapter
- Depends on: PRP-11 (executor in core, refactored script).
- Command per adapter: `NS_LIVE_APPROVED=1 NS_G01A_OPERATOR=<name> NS_G01A_DATABRICKS_HOST=<host> NS_G01A_DATABRICKS_WAREHOUSE_ID=<id> NS_G01A_DATABRICKS_CATALOG=<catalog> NS_G01A_DATABRICKS_REGION=<region> uv run python scripts/gates/g01_analytics_live.py --adapter databricks --evidence-dir docs/evidence/G01/analytics`. Fabric and Synapse stay `OPEN (not run)`: they need an approved TDS driver (ADR-0002 row) that no PRP adds.
- Approval: create and drop one run schema on a serverless 2X-Small warehouse (Entra only; Commercial only). Spend cap: USD 10. Register row: G01 (analytics sentence). Ends OPEN when no warehouse is approved.

### Item 10 - Integration and close-out
- Deliverable: edit only the register rows this PRP's evidence supports (one close-out commit); write `changelog.d/PRP-64.md`; regenerate `PRPs/INDEX.md` and the status table (`python scripts/prp_status.py --write`); fill the completion note table (item, outcome, evidence, spend, row); file follow-up issues (ADR-0005, matrix rows, coverage doc, scripts needed); tell the operator which issues may be closed (#57 only on PASS).
- Owned files: `docs/RESEARCH-AND-GATES.md` (rows listed under Ownership only), `changelog.d/PRP-64.md` (new), this PRP file.
- Acceptance criteria: every item has an outcome row; no register row outside this PRP's list is touched; the GUID grep in Validation gates is clean.
- Tests: `uv run pytest -q tests/unit/gates tests/docs`.

## Validation gates
```bash
python scripts/validate_planning.py
uv run pytest -q tests/unit/gates tests/docs
python scripts/prp_status.py --check
git grep -nE "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}" -- docs/evidence
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```
The `git grep` must show only tokenised, synthetic or pre-existing values; review every hit before committing. Each live item has its own command in its section; none runs in CI.

## Migration and rollback
No data or schema migration. Live runs create and delete throwaway Azure resources in operator-approved groups; rollback of a run is its teardown (scripts do it unless `--keep`). Evidence and register edits roll back with `git revert`. A wrong register edit is corrected by a new commit that cites the evidence, not by deleting evidence.

## Live and open gates
Everything here is live or operator-gated. Required for any run: `NS_LIVE_APPROVED=1` on that command, the operator's approval naming target and cap, and operator-installed credentials. Expected to stay OPEN without further input: Fabric and Synapse analytics (no approved TDS driver), Bedrock (no AWS account), SIEM sink and G12 (no approved namespace or account), anything whose delivering PRP has not shipped. The operations and sign-off gates (G07 load and DR, uninstall, deploy apply, map, accessibility, hosted checks, Government rows) are PRP-66.

## NOT building
Product code, new gate scripts beyond a fix needed to finish a run, new infrastructure, ADR or capability-matrix edits, Government runs, a second G05 swap target, PII or production data in any run, automatic scheduling of live gates, and any claim of SLA, production readiness, compliance or authorization.

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references (commands and evidence paths per item; `Owned files` are evidence paths)
- [x] Gates are executable commands, not intentions
- [x] All clarification questions are decided, not guessed (spend caps, row 5 and row 9 are flagged ASSUMPTIONS for the operator)

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

## Completion note (filled at ship)
- Date, PR number, merge commit:
- Deviations (including any gate-script fix):
- Descoped items:
- OPEN gates (with reason and what closes each):
- Outcome table (item, outcome, evidence path, spend cap versus actual, register row):
- Env vars for the operator:
- Follow-up issues filed:
- Operator product check (can an operator run and read every gate without editing files?):
