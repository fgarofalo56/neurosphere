# G17 evidence (APIM AI gateway, observe)

This directory holds evidence produced by `scripts/gates/g17_apim_observe_live.py` (PRP-33 item 8).
Nothing here is hand-written: an `observe-<UTC stamp>.{json,md}` pair exists only after an
operator-approved live run. Until one is committed, G17 is **OPEN**.

Scope: Azure Commercial only. Government is OPEN (no subscription; APIM v2 tiers `unverified`),
and the script refuses `usgov*`/`usdod*` regions and any `az` cloud other than `AzureCloud`.
Approved targets: Limitlessdata subscriptions only.

## What the run does

1. Creates a resource group tagged `neurosphere:created-by=g17`, `neurosphere:gate=G17`, a Log
   Analytics workspace and one Standard v2 API Management service (ARM `az rest`, api-version
   2024-05-01), polling until `Succeeded`.
2. Enables `GatewayLogs` and `GatewayLlmLogs` to the workspace (resource-specific tables).
3. Imports the `g17-llm` HTTP API (path `llm`) against `<foundry-endpoint>/openai` with the
   `authentication-managed-identity` and `llm-emit-token-metric` policies.
4. RBAC: grants the APIM identity `Cognitive Services OpenAI User` on the Foundry resource.
5. Sends ONE chat completion (max_completion_tokens 200) with a subscription key read in memory only.
6. Polls every 60 s: `preflight` + `read_inventory`, plus the connector `APIM_GATEWAY` query for
   the last 30 minutes, until the gateway row for the request appears or the budget ends. A
   missing `TotalTokens` is reported `llm_log_row: not_observed`, not a failure.
7. Tears down what it created (RG delete only after every resource carries the created-by tag).

## How to run (operator)

```
NS_LIVE_APPROVED=1 MSYS_NO_PATHCONV=1 uv run python scripts/gates/g17_apim_observe_live.py \
  --subscription <limitlessdata-sub-id> --location centralus \
  --foundry-endpoint https://<resource>.openai.azure.com --foundry-deployment <deployment>
```

Approval points: (a) `NS_LIVE_APPROVED=1` for the whole run; (b) the RBAC write on the shared
Foundry resource: without `--approve-rbac` the exact command is printed, the phase is recorded
`skipped_awaiting_operator`, the request/observe phases are skipped and the run tears down
(`PARTIAL_OPEN`); re-run with `--approve-rbac` to complete. Other flags: `--budget-minutes`
(default 20), `--keep`, `--purge`, `--resource-group`, `--evidence-dir`.

Exit codes: 0 PASS or PARTIAL_OPEN, 1 FAIL, 2 refused (nothing changed), 3 teardown failure with
the orphan list (remove those manually).

## Cost

One Standard v2 APIM instance and one Log Analytics workspace for under an hour, plus one paid
model call (max_completion_tokens 200).

## Running it where a tag policy applies, and live-run lessons (2026-11-06)

- `--tag KEY=VALUE` (repeatable) adds tags to the throwaway resource group and workspace. Limitlessdata
  - Main requires `project` and `owner` tags on resource groups, or the create is refused by policy.
- The Foundry endpoint must be an account the gate may grant `Cognitive Services OpenAI User` on:
  create a dedicated throwaway AIServices account and a model deployment (gpt-5-mini, GlobalStandard)
  and pass its `https://<name>.cognitiveservices.azure.com` endpoint. Never use another workload's.
- Pass `--budget-minutes 45`: resource-specific log tables can take longer than 20 minutes to first
  ingest in a new workspace.
- The operator machine did not resolve `api.loganalytics.io` or `api.loganalytics.azure.com`, so the
  gate queries the workspace through ARM (`<workspace>/api/query`). It proves the connector KQL against
  real data but does not exercise the connector HTTP client.
- Defects found only by running it live, all fixed in the script with tests: `neurosphere:` tag keys
  break `az monitor log-analytics workspace create` unless passed as JSON; APIM answers a policy PUT
  with XML, not JSON (and a BOM crashes `az rest` console output, so responses go through
  `--output-file`); the first gateway call is a 401 until the role assignment propagates (retried);
  gpt-5 models reject `max_tokens` (now `max_completion_tokens`).

## What OPEN means

G17 stays OPEN in `docs/RESEARCH-AND-GATES.md` until an `observe-*.md` with `result: PASS` and
`rbac: applied` is committed. `PARTIAL_OPEN`, a refusal or no run is OPEN. Evidence carries
subscription ids as `<subscription:sha256-8>` and the gateway key only as `<key:redacted>`.

## Manage side (PRP-34 item 9)

`scripts/gates/g17_apim_manage_live.py` writes `manage-<UTC stamp>.{json,md}` here, and only after
an operator-approved run that reached at least one live step. None exists: **G17 manage is OPEN**
(not run). Every gateway change in that run is a drafted action intent executed by the worker, each
step needs `--approve-step <name>` (or `--approve-all-steps`), the reused Loom APIM is never a
target, and Government is OPEN. Evidence carries subscription ids as `<subscription:sha256-8>` and
tokens only as `<token:redacted>`. `--print-echo-server` prints a stdlib header-echo MCP backend
for the throwaway streamable-HTTP backend the credential-stripping check needs.

**This script has never run, so treat it as unvalidated.** The MCP echo backend is supplied by the
operator (`--mcp-backend-url`), not provisioned by the script as PRP-34 item 9 specifies, because the
repo has no runnable MCP sandbox server. The API paths and diff shapes it drives (pool JSON-patch
operations, `/catalog/grants/{id}/publish`, `/api/v1/catalog/mcp-servers/{id}/publish`, the fragment
`test` operations) were read from the routers and connector docs, not exercised. Known follow-ups:
refuse a pre-existing `--resource-group`, persist the resource-group name and clear the state file on
teardown, and require a distinct approver token instead of falling back to the maker token.
