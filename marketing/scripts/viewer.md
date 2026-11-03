---
status: draft
persona: viewer
walkthrough: docs/walkthroughs/viewer.md
sandbox_scenario: cost_spike
claims:
  - "Read-only access to a seeded synthetic cost spike"
  - "No action, export or edit path is offered to the Viewer"
permissions:
  - data.read
---

# Viewer demo script

Follows [docs/walkthroughs/viewer.md](../../docs/walkthroughs/viewer.md). Sandbox scenario: `cost_spike`.

Show a read-only user finding a seeded cost spike (tokens 12x, volume 3x inside an injected window).

## Isolation

Before step 1, confirm the sandbox banner is visible at the top of every screen: "Sandbox mode is on. You are working with a synthetic dataset. No real data is read or changed." Run this script against the synthetic sandbox only. Stop if the banner is missing.


## Setup

```bash
make dev-up
make seed-stack SEED_PROFILE=small
```

Sign in as the synthetic persona `viewer` (policy-store role `viewer`).

## Steps

1. Open `/workspaces/viewer`.
   - Expected: The Viewer landing workspace loads with the sandbox banner shown.
   - Permission: data.read
2. Open `/dashboards/cost` and find the spike window.
   - Expected: The cost dashboard shows a spike. Compare its window with `temp/sandbox/anomaly-manifest.json`; estimated and invoiced costs are shown separately and unknown values are not shown as 0.
   - Permission: data.read
3. Open `/map` to see which agents are involved.
   - Expected: The map renders the agents tied to the spike.
   - Permission: data.read
4. Open `/catalog` and read one agent entry.
   - Expected: The catalog lists agents; the entry is read-only with no edit control.
   - Permission: data.read

## Permissions

Role `viewer`: `data.read`. Access is scoped to granted domains; there is no unrestricted bypass.

## Planned (excluded from the demo path)

- Governed copilot chat and chat-driven report creation: the UI route is not in the merged route manifest, so no step uses it.
- Session replay beyond `/replay/traces`: not demonstrated here.
