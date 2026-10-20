# G16 - live judge run (PRP-16)

Status: **OPEN**. The live judge run has not been performed.

| Item | State |
|---|---|
| Live paid judge call | OPEN: not run, no operator approval (`NS_LIVE_APPROVED=1` was never set for this gate) |
| Judge adapter | OPEN: no model-inference SDK is a repository dependency (see below) |
| Hosting the sampling worker in the PRP-05 worker runtime | OPEN: `EvaluationService` is a plain async API |
| Azure blob reader over the PRP-07 archive | OPEN: only in-memory and NDJSON `RecordSource`s exist |

## What CI covers instead

Judge behaviour in CI comes from recorded fixtures (`neurosphere_core.evaluation.judge.RecordedFixtureJudge`)
and counting doubles. The restricted-content guard, budgets and stratified sampling are tested with
the real code paths in `services/workers/tests/evaluation/`. None of that is live evidence, and no
test or CI job makes a paid call.

## Why the live run is not built

`scripts/gates/g16_judge_live.py` refuses (exit 2) unless `NS_LIVE_APPROVED=1`, checked before any
project, azure or network import. With approval it reports OPEN (exit 3) because no model-inference
SDK is a dependency. Adding one needs an ADR-0002 stack-pin row and operator approval; this item
adds no dependencies.

## How it would run

1. Operator approves the spend and names the cloud, the Foundry deployment and a small budget.
2. A `Judge` adapter is added (Entra or managed identity only; no key in arguments, files or logs).
3. `NS_LIVE_APPROVED=1 uv run python scripts/gates/g16_judge_live.py` runs `EvaluationService.run_offline`
   over the SYNTHETIC pilot dataset with a small `BudgetLedger`, using the same pre-call guard
   (classification approval, boundary cloud, capability-matrix availability, price known) as CI.
4. Whitelisted fields only are written here: counts, tokens, cost with `price_version`, judge config
   version, date, operator. A Government run uses a Government judge and never a Commercial one.

Availability, feature maturity and authorization are separate gates; nothing here claims FedRAMP
authorization, ATO or compliance parity.
