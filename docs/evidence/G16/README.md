# G16 - live judge run (PRP-16)

Status: **OPEN**. The live judge run has not been performed.

| Item | State |
|---|---|
| Live paid judge call | OPEN: not run, no operator approval (`NS_LIVE_APPROVED=1` was never set for this gate) |
| Judge adapter | BUILT: `EndpointJudge` (`neurosphere_core.evaluation.endpoint_judge`), tested against recorded HTTP fixtures only; never exercised against a live endpoint |
| Hosting the sampling worker in the PRP-05 worker runtime | OPEN: `EvaluationService` is a plain async API |
| Azure blob reader over the PRP-07 archive | OPEN: only in-memory and NDJSON `RecordSource`s exist |

## What CI covers instead

Judge behaviour in CI comes from recorded fixtures (`neurosphere_core.evaluation.judge.RecordedFixtureJudge`)
and counting doubles. The restricted-content guard, budgets and stratified sampling are tested with
the real code paths in `services/workers/tests/evaluation_worker/`. None of that is live evidence, and no
test or CI job makes a paid call.

## The judge adapter

`EndpointJudge` is a non-streaming Azure OpenAI-style chat-completions client (plain `httpx` plus a
managed-identity `AsyncTokenCredential`; no new dependency). It reuses the copilot endpoint rules
(`require_endpoint`, `token_scope`, `bearer_headers`, `error_for_status`, redaction), refuses an
endpoint outside the deployment cloud at construction (Government never calls Commercial), requests
a JSON verdict, and parses it strictly: an unparseable or schema-invalid verdict is an abstention
with a recorded reason, never a score. Token usage comes from the response `usage` block into
`JudgeResponse.input_tokens` / `output_tokens`. HTTP 401/403/429/5xx go through the error taxonomy.

`scripts/gates/g16_judge_live.py` refuses (exit 2) unless `NS_LIVE_APPROVED=1`, checked before any
project, azure or network import. With approval it reads `NS_CLOUD`, `NS_G16_JUDGE_ENDPOINT` and
`NS_G16_JUDGE_DEPLOYMENT` (optional `NS_G16_JUDGE_API_VERSION`), and exits 3 (OPEN) if any is
missing. The live run is still OPEN: it has not been run.

## How it would run

1. Operator approves the spend and names the cloud, the Foundry deployment and a small budget.
2. The operator supplies the endpoint and deployment through the environment variables above (Entra or managed identity only; no key in arguments, files or logs).
3. `NS_LIVE_APPROVED=1 uv run python scripts/gates/g16_judge_live.py` runs `EvaluationService.run_offline`
   over the SYNTHETIC pilot dataset with a small `BudgetLedger`, using the same pre-call guard
   (classification approval, boundary cloud, capability-matrix availability, price known) as CI.
4. Whitelisted fields only are written here: counts, tokens, cost with `price_version`, judge config
   version, date, operator. A Government run uses a Government judge and never a Commercial one.

Availability, feature maturity and authorization are separate gates; nothing here claims FedRAMP
authorization, ATO or compliance parity.
