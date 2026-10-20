# G12 evidence: PRP-16 agent evaluation and quality (in process, synthetic, in-memory)

Date measured: 2026-10-19. Gate G12 (emulator parity) stays OPEN. This document records what the
PRP-16 evaluation pipeline did over the SYNTHETIC sandbox benchmark data and, just as important,
what this run could not exercise. Nothing here is a live judge result and nothing here claims
FedRAMP authorization, ATO or compliance parity.

## What was run

`neurosphere_workers.evaluation.pipeline.run_pipeline` over a registry loaded from
`sandbox/evaluation/data` (50-item groundedness pilot set, rubric, three judge configs, recorded judge
fixtures, a versioned human-label set), with the SHIPPED capability matrix (`load_matrix()`, no
row added or edited):

1. the OFFLINE pilot run through the real guard, budget ledger and `EvaluationService`;
2. calibration of the LLM judge per dimension against the human-label set, stored under the item 4
   key (judge config id = `judge_model_id`, version = `<model_version>+<prompt_version>`);
3. contract results re-emitted with the calibration attached, each checked with
   `check_result_references`, then written with per-stratum sampling coverage and drift alerts to an
   `InMemoryEvaluationStore`;
4. an ONLINE sampled run over a small SYNTHETIC archive-shaped record set;
5. the real FastAPI app (router mounted by `REGISTERED`, not by the test) serving
   `/api/v1/evaluation/domains/{domain}/quality` and `/results` to scoped callers over HTTP.

Reproduce (about 15 s, no network, no wall clock, no credential):

```
uv run python tests/integration/evaluation/measure.py
uv run pytest tests/integration/evaluation -q
```

## Measured results

### Pilot set (offline, Government judge)

The only Commercial Foundry row in the shipped matrix is `unverified` (G01), so the Commercial judge is
disabled and the pilot set runs on the Government judge, whose row
`foundry.model_gpt_4_1.government.usgovvirginia.data-zone-standard` is `available`.

| Measure | Value |
|---|---|
| Items (`sbx-groundedness-pilot` 1.0.0) | 50 (16 public, 16 internal, 10 cui, 8 restricted) |
| Judge calls | 42 (every non-restricted item); fixture judge, no network |
| Skipped by reason | `judge_not_approved`: 8 (all restricted); no judge call was made for them |
| Scored / abstained | 40 / 2 |
| Pilot grounded-answer rate | 0.875 (35 of 40), Wilson 95% interval 0.7389 to 0.9454, n = 40 |
| Label shown by the API | "pilot-set target: at least 90%" (the estimate is below it; it is a target, not a result or a guarantee) |
| Judge usage (fixture token counts) | 7687 input + 1072 output tokens, estimated 0.02395 USD at synthetic price version `sandbox-prices-1` |
| Run status | `partial` (restricted items skipped, two abstentions) |

Sampling coverage per stratum (`evaluated / population`): cui 10/10, internal 16/16, public 16/16,
restricted 0/8. The restricted stratum is stored and served as 0 evaluated of 8, not as unknown and
not hidden. (`SamplingCoverage.sampled` is stored as the number actually judged, so the number and
the fraction always agree.)

### Calibration against the human-label set

Synthetic label set `sbx-groundedness-pilot-human-labels` 1.0.0 (one label per pilot item, truth
known by construction). 40 judged items matched to 40 labels, 0 missing.

| Metric | Value |
|---|---|
| Cohen kappa | 0.314, bootstrap 95% interval -0.103 to 0.722 (1000 resamples, seed 0) |
| Raw accuracy (reported alongside, not stored) | 0.85, Wilson 95% interval 0.709 to 0.929 |
| Mean judge-minus-human bias | 0.0 |

Read plainly: accuracy is 85% but only 7 of 50 items are ungrounded, so chance agreement is high and
kappa is low with an interval that includes 0. The judge is marked `calibrated` because the sample
cleared the minimum label count (20), not because agreement is strong. That is a statement about
this synthetic fixture judge, which was built to flip about 10% of verdicts.

### Drift

Both checks compare against the pipeline's real current scores (40 scored items).

| Check | Baseline | PSI | Threshold | Result |
|---|---|---|---|---|
| Stable window | SYNTHETIC baseline, 36/40 grounded | 0.0063 | 0.25 | stable, no alert |
| Seeded shift | SYNTHETIC baseline, 20/40 grounded | 0.7297 | 0.25 | drift, 1 alert stored, served in `/quality` |

### Budget-limited run

Same pilot run with a 6000-token run budget: status `budget_exhausted` (`run_tokens:finance`), 23
items judged, 20 never evaluated (reported as `budget_exhausted`, not dropped), 7 restricted skipped
before the stop, 4786 tokens used (under the limit), judge calls equal judged items. 23 labelled
pairs still cleared the minimum, so one `partial` result was emitted with its coverage.

### Capability-matrix honesty (Commercial)

Running the same pilot on the Commercial judge config: 50 of 50 items skipped with
`judge_unavailable`, 0 judge calls, 0 results. Reason recorded on every outcome: capability row
`foundry.base.commercial.global.any` availability is `unverified`, not `available`. Nothing was
rerouted to the Government judge and no test-only matrix row was added. The result is a finding,
not a failure: it follows the matrix, and changes only when G01 evidence verifies that row.

### Online path

- **Sandbox telemetry carries no `classification`.** The PRP-03 generator (Government customer, 922
  records) wrote the field on 0 records. With the fail-closed rule (null is restricted) and an LLM judge,
  all 451 sampled spans (462 records excluded first: 461 `not_scorable_span`, 1 `cloud_mismatch`; the
  sampler also de-duplicates by item id) were skipped `judge_not_approved`: 0 judge calls, 0 evaluated,
  0 results. Reported, not changed.
- **Synthetic archive-shaped fixture with classifications** (SYNTHETIC, 180 records, two domains, every
  classification and null): 20 unscorable spans excluded, 160 sampled, 160 evaluated by a TEST-ONLY
  programmatic outcome scorer, 8 results stored. Groundedness is `null` / `not_estimable` and the run
  carries `limited_dimensions = {groundedness: bodies_not_archived}` (PRP-07 drops bodies).
- **Restricted guard online** (LLM judge double, same fixture): restricted and null-classified items
  (64) reached no judge; 96 public, internal and cui items did. Their results are not emitted: no human
  labels exist for the metadata dimensions, so the judge is `uncalibrated` and listed.

### API (scoped callers, Government-bound dev-issuer harness)

Pilot rate present with the exact label and a Wilson interval; the LLM point is `calibrated` (it would
render `uncalibrated` if the report were stored under the registry key instead of the item 4 key, which
the negative control in the test proves); `missing_labels` judged 40, labelled 40, missing 0; one drift
alert. A caller scoped to finance gets 403 on operations and the reverse on `/quality` and `/results`;
results returned for each domain carry only that domain. Every stored result validates against the
PRP-01 schema and `check_result_references`. The OpenAPI document gained the two read routes.

## What is synthetic

Everything: the pilot dataset, rubric, judge configs and prices (`sandbox-prices-1`), the recorded judge
fixtures (a fixture judge built to flip about 10% of verdicts and abstain on about 4%), the human
labels, the drift baselines and the archive-shaped records. Test-only objects, labelled in
`tests/integration/evaluation/support.py`: `OutcomeJudge` and the Government programmatic config
`slice-programmatic-gov` (registered by the suite only), `CountingLlm`, `synthetic_archive`.

## Emulator and in-memory limits (G12)

- **No Cosmos evaluation store exists** (OPEN). `InMemoryEvaluationStore` stands in, so RU cost,
  indexes, partitioning, 429 behaviour, Entra and concurrency are not exercised. The `/quality` route
  loads a domain's results per request; that needs a bound or a pre-aggregate before a Cosmos store.
- No archive emulator or Azure blob reader: records come from memory or NDJSON (OPEN).
- The authz harness is the PRP-06 dev issuer with an in-memory policy store (no Entra).
- Outbound connects are blocked in the suite, so the run proves no network was attempted.

## OPEN

- **G16 live judge run: OPEN.** Not run. No model-inference SDK is a repository dependency, no operator
  approval, `NS_LIVE_APPROVED` was not set. `docs/evidence/G16/README.md` describes how it would run.
- **G01 judge availability per cloud: OPEN.** Read from the matrix only. The Commercial Foundry row is
  `unverified`, so the Commercial judge is disabled; Government rows are documentation-derived
  `available`, not authorized and not tested against a Government subscription.
- **G05 model-swap compatibility: OPEN.** This work supplies quality-regression inputs (judge scores,
  calibration, drift) only. The model swap and its gates are PRP-17.
- **G06 privacy, retention, legal hold: OPEN until PRP-23.** Evaluation reads only redacted archive
  shaped data and treats a missing classification as restricted; that informs G06, it does not close it.
- Cosmos evaluation store, worker runtime hosting of `EvaluationService`, Azure blob archive reader,
  and production bootstrap of `app.state.evaluation_store`: OPEN.
