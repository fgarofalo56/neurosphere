---
status: draft
persona: analyst
walkthrough: docs/walkthroughs/analyst.md
sandbox_scenario: latency_regression
claims:
  - "Investigation of a seeded latency regression in synthetic data"
  - "Saved synthetic reports run under the caller scope"
permissions:
  - data.read
  - grant.read
  - report.create
  - data.export
  - action.propose
---

# Analyst demo script

Follows [docs/walkthroughs/analyst.md](../../docs/walkthroughs/analyst.md). Sandbox scenario: `latency_regression`.

Show an analyst investigating a seeded latency regression (durations 3x from the window start) and opening a saved report.

## Isolation

Sandbox mode defaults to off and the banner appears only once it is on. Before step 1, switch it on from the user menu (the sandbox toggle), then confirm the banner is visible at the top of every screen: "Sandbox mode is on. You are working with a synthetic dataset. No real data is read or changed." Run this script against the synthetic sandbox only. Stop if the banner is missing.


## Setup

```bash
make dev-up
make seed-stack SEED_PROFILE=small
```

Sign in as the synthetic persona `analyst` (policy-store role `analyst`). After sign-in, switch sandbox mode on from the user menu (the sandbox toggle) before step 1.

## Steps

1. Open `/workspaces/analyst`.
   - Expected: The Analyst landing workspace loads with the sandbox banner shown.
   - Permission: data.read
2. Open `/dashboards/latency` and locate the regression.
   - Expected: The latency dashboard shows durations rising from the window start (checked 2026-11-03 on the local stack: p95 rises from about 7.5 s to about 44-49 s on Nov 1-2, then falls back). The summary tiles read "unknown" and the page says "analytics: disabled", so the per-day tables are the evidence. The manifest names one affected agent for the latency regression (`a-000014`, 3x multiplier), but the latency dashboard has no per-agent view, so the affected agent cannot be identified on this screen (checked 2026-11-03). Do not claim it can. The affected agents match `temp/sandbox/anomaly-manifest.json`. `make seed-stack` moves the generated epoch to the run time, so the manifest's absolute window times will not match what you see; compare the ratios and the affected agents, not clock times.
   - Permission: data.read
3. Open `/replay/traces` and replay a trace through an affected agent.
   - Expected: The trace replay view opens for the chosen trace (checked 2026-11-03: the trace list loads and Inspect trace opens a detail panel with the span hierarchy).
   - Permission: data.read
4. Open `/reports`.
   - Expected: The synthetic saved reports `agents-by-version` and `agent-inventory` are listed for the synthetic analyst persona who owns them. Checked 2026-11-03: an account that is not that persona sees "No reports are visible to you in this domain", because report visibility is per owner. Do not demo this step from another account. Opening one runs a bounded structured query under your own scope.
   - Permission: data.read (run), report.create (create)

## Permissions

Role `analyst`: `data.read`, `grant.read`, `report.create`, `data.export`, `action.propose`. Access is scoped to granted domains; there is no unrestricted bypass.

## Planned (excluded from the demo path)

- Governed copilot chat and chat-driven report creation: the UI route is not in the merged route manifest, so no step uses it.
- Session replay beyond `/replay/traces`: not demonstrated here.
