# PRP-141 evidence: Azure Monitor AI call telemetry

Gate "Azure Monitor AI call telemetry" is **OPEN**. PRP-141 built and unit-tested the reader, the
worker role, the stored configuration and the console text; it ran nothing against Azure. This
directory holds no evidence file yet. The operator steps are in
`docs/runbooks/azure-monitor-ai-telemetry.md`.

Evidence files are added only by operator runs (`NS_LIVE_APPROVED=1`, the owner's approval of the
workspace read assignment, a real-tenant deployment from PRP-139, Commercial only). They hold
counts, states and reason codes only: no id, host, resource id, token or content value.

Passing this gate closes row 4 of PRP-139's gate (`docs/evidence/PRP-139/README.md`). Government is
not part of it and stays unverified. G04 (`docs/connectors/coverage.md`) stays OPEN and is not
replaced by this gate.

## PASS needs, from one environment

| # | Condition | Commands that produce the evidence | Status |
|---|---|---|---|
| 1 | The run status of the source is `ok` or `partial` and the event count is above zero | `hosted_real_tenant.py verify` (row 4 of `<date>-verify.json`: `events_posted`, `visible_series`, `visible_points`) | OPEN |
| 2 | At least one model call from the owner's workload is visible on a dashboard with latency, outcome, model and token counts | dashboard check in the console; count recorded here | OPEN |
| 3 | At least one agent has a per-agent series, by alias or by derived id | console check; count recorded here | OPEN |
| 4 | A scan of the archived records of the run finds no content field | a scan of the run's archived records against `CONTENT_DENYLIST`; count of matches recorded here | OPEN |
| 5 | A scrubbed real response replaces the hand-built fixture, and each UNVERIFIED item is marked confirmed or corrected in the README | `connectors/reference/azure-monitor/README.md` | OPEN |

`verify` can show conditions 1 and part of 2 only. Because no API route filters events by source,
it reads the admin source status (run state and `events_posted`) and the latency dashboard (known
points). Conditions 2 to 5 are recorded by hand, as counts. A row is never PASS on the status alone.

## Result by row

| Row | Status |
|---|---|
| 1 to 5 | OPEN |
