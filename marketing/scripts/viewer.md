---
status: draft
persona: viewer
walkthrough: docs/walkthroughs/viewer.md
sandbox_scenario: cost_spike
claims:
  - "Read-only access to seeded synthetic cost_spike recommendations"
  - "Change attempts by the Viewer are refused by the API"
permissions:
  - data.read
  - grant.read
---

# Viewer demo script

Follows [docs/walkthroughs/viewer.md](../../docs/walkthroughs/viewer.md). Sandbox scenario: `cost_spike`.

Show a read-only user finding which agents the seeded cost spike (tokens 12x, volume 3x inside an injected window) involves, through the `cost_spike` recommendations. The local stack has no analytics backend, so the dashboard itself does not draw the spike.

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
   - Expected: on the local emulator stack (checked 2026-11-03), the cost dashboard shows "unknown" cost, an "incomplete data" tag and "analytics: disabled, no analytics backend is enabled", with an empty chart. Unknown values are not shown as 0. The seeded spike is not visible here; it needs an enabled analytics backend, so do not present this screen as showing the spike on the local stack. The generator's spike window is recorded in `temp/sandbox/anomaly-manifest.json` (`make seed-stack` moves the epoch, so its absolute times will not match).
   - Permission: data.read
3. Open `/map` to browse the agents, then open `/recommendations` and find the `cost_spike` recommendation to read the spike agents.
   - Expected: (checked 2026-11-03) the map renders the agents and their relations; it has no spike overlay or highlight. The recommendations list has `cost_spike` entries that each name an agent (seven agents on the small profile), shown with "Projected change: unknown", "Insufficient history" and "Advisory action gates not passed". That is the way to read which agents are involved.
   - Permission: data.read
4. Open `/catalog` and read one agent entry.
   - Expected: (checked 2026-11-03) the catalog lists agents and the entry shows its details and lineage. The entity page can still draw a Deprecate button, because the UI shows controls from the Entra app role in the token. If you press it and confirm, the API refuses ("The service declined this change") for a policy-store `viewer`, and the entity stays active. Do not press it on stage unless you want to show the refusal. Use an account whose Entra role is also `viewer` to avoid the button.
   - Permission: data.read

## Permissions

Role `viewer`: `data.read`, `grant.read`. Access is scoped to granted domains; there is no unrestricted bypass.

## Planned (excluded from the demo path)

- Governed copilot chat and chat-driven report creation: the UI route is not in the merged route manifest, so no step uses it.
- Session replay beyond `/replay/traces`: not demonstrated here.
