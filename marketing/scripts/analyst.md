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
  - report.create
  - data.export
  - action.propose
---

# Analyst demo script

Follows [docs/walkthroughs/analyst.md](../../docs/walkthroughs/analyst.md). Sandbox scenario: `latency_regression`.

Show an analyst investigating a seeded latency regression (durations 3x from the window start) and opening a saved report.

## Isolation

Before step 1, confirm the sandbox banner is visible at the top of every screen: "Sandbox mode is on. You are working with a synthetic dataset. No real data is read or changed." Run this script against the synthetic sandbox only. Stop if the banner is missing.


## Setup

```bash
make dev-up
make seed-stack SEED_PROFILE=small
```

Sign in as the synthetic persona `analyst` (policy-store role `analyst`).

## Steps

1. Open `/workspaces/analyst`.
   - Expected: The Analyst landing workspace loads with the sandbox banner shown.
   - Permission: data.read
2. Open `/dashboards/latency` and locate the regression.
   - Expected: The latency dashboard shows durations rising from the window start. The affected agents match `temp/sandbox/anomaly-manifest.json`.
   - Permission: data.read
3. Open `/replay/traces` and replay a trace through an affected agent.
   - Expected: The trace replay view opens for the chosen trace.
   - Permission: data.read
4. Open `/reports`.
   - Expected: The synthetic saved reports `agents-by-version` and `agent-inventory` are listed. Opening one runs a bounded structured query under your own scope.
   - Permission: data.read (run), report.create (create)

## Permissions

Role `analyst`: `data.read`, `report.create`, `data.export`, `action.propose`. Access is scoped to granted domains; there is no unrestricted bypass.

## Planned (excluded from the demo path)

- Governed copilot chat and chat-driven report creation: the UI route is not in the merged route manifest, so no step uses it.
- Session replay beyond `/replay/traces`: not demonstrated here.
