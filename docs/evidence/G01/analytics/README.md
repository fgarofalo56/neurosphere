# G01 evidence: analytics adapters (Commercial)

This directory holds evidence produced by `scripts/gates/g01_analytics_live.py` (PRP-11 item 6).
Nothing here is hand-written: a `<date>-<adapter>-commercial.{json,md}` file exists only after the
script ran.

## Current state

| Adapter | Status | Why |
|---|---|---|
| Fabric | **OPEN** | Not run (operator decision 2026-10-18). No approved TDS driver. |
| Synapse | **OPEN** | Not run (operator decision 2026-10-18). No approved TDS driver. |
| Databricks | **OPEN** | Not run (operator decision 2026-10-18). The script and its executor ship; no live run was approved. |

Fabric and Synapse need a TDS driver (mssql-python or ODBC Driver 18). That needs an ADR-0002
stack-pin row and operator approval, so even an approved run records them OPEN without attempting
a connection. Government Fabric, Synapse and Databricks stay OPEN for G01 and G02: no Government
subscription exists, and availability is not authorization.

The stub and fixture tests (`tests/integration/analytics`, `packages/core/tests/analytics`) are
contract conformance only. They run vendor-shaped SQL on SQLite through declared shims and are
never evidence that a vendor works in a cloud, region or SKU.

## How to run

Operator approval is required (`NS_LIVE_APPROVED=1`, checked before anything else). Run through
`uv run` so the project packages are importable (the script refuses otherwise). In Git Bash prefix
`MSYS_NO_PATHCONV=1` so paths and ids are not rewritten.

```
MSYS_NO_PATHCONV=1 NS_LIVE_APPROVED=1 uv run python scripts/gates/g01_analytics_live.py \
  --adapter databricks --operator "<name>"
```

`--adapter` is required and repeatable; only the named adapters run, each independently. `--keep`
leaves the run-scoped schema in place; `--timeout-ms` sets the per-request time budget (default and
ceiling 30000). Auth is Entra only (`DefaultAzureCredential` or managed identity, so `az login`
first); no key, token, PAT or password is accepted from arguments or environment.

Configuration is environment variables (names only):

- `NS_G01A_OPERATOR`
- Databricks: `NS_G01A_DATABRICKS_HOST` (`adb-<id>.<n>.azuredatabricks.net`),
  `NS_G01A_DATABRICKS_WAREHOUSE_ID`, `NS_G01A_DATABRICKS_CATALOG` (an existing catalog; a schema
  named `ns_g01a_<run id>` is created in it and dropped afterwards), `NS_G01A_DATABRICKS_REGION`,
  `NS_G01A_DATABRICKS_SKU_CLASS` (label, e.g. `serverless-2X-Small`)
- Synapse (optional, validated when supplied): `NS_G01A_SYNAPSE_WORKSPACE`, `_DATABASE`, `_MODE`
  (`serverless` or `dedicated`), `_HOST`, `_REGION`, `_SKU_CLASS`
- Fabric (optional, validated when supplied): `NS_G01A_FABRIC_HOST`, `_DATABASE`, `_REGION`,
  `_SKU_CLASS`

A Government cloud, region or host is refused with exit 2. Each adapter's own config model also
rejects a cross-cloud host at construction.

## What the run does

Per Databricks run: creates a run-scoped schema, applies the adapter migrations, loads the
synthetic fixture dataset (`build_dataset("commercial")`; no production data), runs the same 14
requests as `tests/integration/analytics/test_equivalence.py` with a budget on each, compares
live against the fixture adapter with `compare_results`, runs the same requests through the SQLite
stub and records the live-versus-stub delta and the stub's applied shims (G12), then drops the
schema unless `--keep`. Tolerance: counts, sums, min and max exact; approximate quantiles within
`QUANTILE_REL_TOL` 0.02 relative with `QUANTILE_ABS_TOL` 1 for integer metrics.

## Statuses and exit codes

- **PASS**: every case within tolerance and the run schema dropped (or `--keep`).
- **FAIL**: a case outside tolerance, a setup or teardown error, or evidence that failed the
  secret scrubber (not written).
- **OPEN**: not run, so not evidence. Distinct from PASS and FAIL.

Exit code: `1` if any adapter FAILed; else `3` if any is OPEN; else `0`. `2` means REFUSED
(no approval, wrong interpreter, bad arguments, Government cloud, invalid config); nothing ran.

## Known limits

- The Statement Execution API reports no rows scanned or cost, so on the live path the rows and
  cost budgets are weak (`rows_scanned` is the returned row count, `cost_units` is 0). The time
  budget and returned-row limit apply in full; a timeout cancels the server-side statement.
- The Databricks API shape and the Entra resource id (`2ff814a6-3304-4ab8-85cb-cd0e6f879c1d`) were
  not verified against Microsoft Learn when the script was written. The first live run verifies
  them.
- Evidence records the SKU class and region the operator supplied. They are not read from a
  management API.

## Evidence content

Built from whitelisted fields only (adapter, cloud, status and reason, SKU class, region, date,
operator, per-case tolerance result, live-versus-stub delta, stub shims, teardown) and passed
through a scrubber that fails the run on anything credential-shaped. Hosts and warehouse ids are
never written. Review a file before committing it. Nothing here is an authorization, ATO or
FedRAMP claim.
