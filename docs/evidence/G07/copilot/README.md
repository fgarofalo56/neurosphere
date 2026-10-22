# G07 evidence: copilot first-token latency (PRP-19 item 6)

Status: **measured on the sandbox with recorded fixtures only.** The live-provider number is **OPEN**.

## What the number is

`first-token.json` holds the time from sending a copilot message to the arrival of the first
`token` server-sent event, measured over a real loopback HTTP connection:

- the composed FastAPI app is the same one `tests/integration/copilot/support.py` builds
  (real authz, real tool registry, real chart validator, in-memory conversation store);
- it is served by uvicorn on an ephemeral port in a thread and read with an httpx streaming
  client, so the bytes cross a socket and are not buffered by a test client;
- the model is the **recorded-fixture adapter**, so provider latency is excluded by construction;
  the one tool round trip is the in-memory catalog;
- each sample creates a fresh conversation, sends "What agents do we have?" and stops at the
  first `event: token` line. 3 warm-up messages are discarded, then N = 30 are recorded.

Reproduce (writes this file only when asked, so CI never dirties the tree):

```
NS_WRITE_EVIDENCE=1 uv run pytest -q tests/e2e/copilot -s
```

## Result

| Statistic | Value |
|---|---|
| N | 30 (plus 3 discarded warm-ups) |
| p50 | about 119 ms |
| p95 | about 140 ms |
| max | about 296 ms |

Exact values and the environment (OS, CPU, Python, uvicorn, date) are in `first-token.json`.
Numbers vary run to run and by machine; this is a sandbox figure, not a benchmark.

## How to read it

- The PRD figure of **3 s to first token is a planning target on the sandbox** (PRP-19
  clarification 11). It is **not an SLA and not a guarantee**. The test prints the target beside
  the measured value and asserts only a generous sanity bound (30 s) that catches a stalled stream.
- **No live-provider number is claimed.** A run against a real model endpoint needs operator
  approval (`NS_LIVE_APPROVED=1`) and has not happened: **OPEN**.
- The server releases an answer's tokens only after the output guard and evidence checks have run
  and the turn has been persisted (`engine.py`, "persist, then release"). First token therefore
  tracks the end of the model turn(s) plus tool work, not the first model delta. With recorded
  fixtures that is about the whole turn (about 100 to 125 ms, matching the `duration_ms` the
  engine logs). With a real provider, first token will include full generation time, so the 3 s
  target will be sensitive to provider speed and answer length. That is a design consequence to
  weigh before treating 3 s as achievable live.
- Gate rows touched: G07 (planning targets). G01 and G05 are unaffected.
