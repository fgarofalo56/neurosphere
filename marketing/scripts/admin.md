---
status: draft
persona: admin
walkthrough: docs/walkthroughs/admin.md
sandbox_scenario: bad_events
claims:
  - "Platform controls exist for execution control and MCP administration"
  - "Unsupported cloud or region features are shown as disabled"
permissions:
  - data.read
  - config.manage
  - policy.manage
  - revocation.manage
  - grant.read
  - grant.write
---

# Admin demo script

Follows [docs/walkthroughs/admin.md](../../docs/walkthroughs/admin.md). Sandbox scenario: `bad_events`.

Show an admin operating the platform against messy input: the generator injects duplicate, out-of-order and malformed events so quarantine can be observed.

## Isolation

Sandbox mode defaults to off and the banner appears only once it is on. Before step 1, switch it on from the user menu (the sandbox toggle), then confirm the banner is visible at the top of every screen: "Sandbox mode is on. You are working with a synthetic dataset. No real data is read or changed." Run this script against the synthetic sandbox only. Stop if the banner is missing.


## Setup

```bash
make dev-up
make seed-stack SEED_PROFILE=small
make replay
```

`SEED_PROFILE=small` has zero bad-event rates, so the seed alone pushes no bad events; `make replay` pushes the generator's bad events and rewrites `temp/sandbox/bad-event-manifest.json`.

Sign in as the synthetic persona `admin` (policy-store role `admin`). After sign-in, switch sandbox mode on from the user menu (the sandbox toggle) before step 1.

## Steps

1. Open `/workspaces/admin`.
   - Expected: The Admin landing workspace loads with the sandbox banner shown.
   - Permission: data.read
2. Open `/admin/execution-control`, then `/mcp-admin`.
   - Expected: Both platform control pages load. Controls the role lacks are denied by the API, not just hidden.
   - Permission: config.manage
3. Open `/sandbox`.
   - Expected: The page confirms synthetic data only and lists document counts by kind.
   - Permission: data.read
4. Open `/gateways`, then `/deploy/capabilities`.
   - Expected: The pages show which features the cloud and region allow. Unsupported combinations are disabled with a reason.
   - Permission: data.read (view), config.manage (changes)
5. Compare counts in `temp/sandbox/bad-event-manifest.json` with what the pipeline accepted and quarantined (after `make replay`).
   - Expected: Duplicate, out-of-order and malformed counts in the manifest line up with the accepted and quarantined counts you observe. Compare counts only: `make seed-stack` moves the epoch, so the manifest's absolute window times will not match.
   - Permission: operator access to the local stack

## Permissions

Role `admin`: `data.read`, `config.manage`, `policy.manage`, `revocation.manage`, `grant.read`, `grant.write`. Access is scoped to granted domains; there is no unrestricted bypass.

## Planned (excluded from the demo path)

- Governed copilot chat and chat-driven report creation: the UI route is not in the merged route manifest, so no step uses it.
- Session replay beyond `/replay/traces`: not demonstrated here.
