# G01 evidence (Commercial deploy smoke)

This directory holds evidence produced by `scripts/gates/g01_deploy_smoke.py`. Nothing here is
hand-written: a `*-commercial-deploy-smoke.json` file exists only after an operator-approved live
run. Until one is committed, the Commercial slice of G01 integration evidence is OPEN.

Scope: Azure Commercial only. Government Fabric/Synapse/Databricks/Search profiles stay OPEN
(G01, G02). The script refuses `usgov*`/`usdod*` regions and any cloud other than `AzureCloud`.

## How to produce it

Prerequisites: `az` installed and already signed in to the Commercial cloud with the target
subscription active; a resource group name that does not exist yet (the script creates it, tags it
`neurosphere:created-by=neurosphere`, and deletes it at the end).

Run it through `uv run` so `neurosphere_core` is importable (the script refuses otherwise). In Git
Bash, prefix `MSYS_NO_PATHCONV=1` so `--reuse-apim /subscriptions/...` is not rewritten into a
Windows path.

```
MSYS_NO_PATHCONV=1 NS_LIVE_APPROVED=1 uv run python scripts/gates/g01_deploy_smoke.py \
  --subscription <subscription-guid> \
  --resource-group <new-rg-name> \
  --apim-publisher-email <ops-email> --apim-publisher-name <org-name>
```

Use `--reuse-apim <arm-id>` instead of the publisher flags to reuse an existing APIM (never
modified or purged). Without it, APIM Developer is created (~30-45 minutes) and purged at
teardown. `--keep` skips teardown. `--location` defaults to the Commercial bicepparam value.

This deploys billable Azure resources. Key Vault is created with purge protection, so its purge
at teardown is expected to be blocked and is recorded as `blocked_by_purge_protection`.

## Output

`<UTC date>-commercial-deploy-smoke.json` plus a `.md` summary: what-if summary, resources
created, health result, teardown and purge results, `gate: G01`, `result: PASS|FAIL`. The evidence
is built from whitelisted fields (ids, types, states) and scrubbed; the run fails if any value
looks like a credential. Review the file before committing it.
