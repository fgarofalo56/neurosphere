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
  - grant.read
---

# Viewer demo script

Follows [docs/walkthroughs/viewer.md](../../docs/walkthroughs/viewer.md). Sandbox scenario: `cost_spike`.

Show a read-only user finding a seeded cost spike (tokens 12x, volume 3x inside an injected window).

## Isolation

Sandbox mode defaults to off and the banner appears only once it is on. Before step 1, switch it on from the user menu (the sandbox toggle), then confirm the banner is visible at the top of every screen: "Sandbox mode is on. You are working with a synthetic dataset. No real data is read or changed." Run this script against the synthetic sandbox only. Stop if the banner is missing.


## Setup

```bash
make dev-up
make seed-stack SEED_PROFILE=small
```

Sign in as the synthetic persona `viewer` (policy-store role `viewer`). After sign-in, switch sandbox mode on from the user menu (the sandbox toggle) before step 1.

## Steps

1. Open `/workspaces/viewer`.
   - Expected: The Viewer landing workspace loads with the sandbox banner shown.
   - Permission: data.read
2. Open `/dashboards/cost` and find the spike window.
   - Expected: The cost dashboard shows a spike. Compare its window with `temp/sandbox/anomaly-manifest.json`; estimated and invoiced costs are shown separately and unknown values are not shown as 0. `make seed-stack` moves the generated epoch to the run time, so the manifest's absolute window times will not match what you see; compare the ratios and the affected agents, not clock times.
   - Permission: data.read
3. Open `/map` to browse the agents, then open `/recommendations` and find the `cost_spike` recommendation to read the spike agents.
   - Expected: The map renders the agents and their relations; it has no spike overlay or highlight. The `cost_spike` recommendation names the agents involved.
   - Permission: data.read
4. Open `/catalog` and read one agent entry.
   - Expected: The catalog lists agents; the entry is read-only with no edit control.
   - Permission: data.read

## Permissions

Role `viewer`: `data.read`, `grant.read`. Access is scoped to granted domains; there is no unrestricted bypass.

## Planned (excluded from the demo path)

- Governed copilot chat and chat-driven report creation: the UI route is not in the merged route manifest, so no step uses it.
- Session replay beyond `/replay/traces`: not demonstrated here.
