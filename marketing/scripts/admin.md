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
---

# Admin demo script

Follows [docs/walkthroughs/admin.md](../../docs/walkthroughs/admin.md). Sandbox scenario: `bad_events`.

Show an admin operating the platform against messy input: the generator injects duplicate, out-of-order and malformed events so quarantine can be observed.

## Isolation

Before step 1, confirm the sandbox banner is visible at the top of every screen: "Sandbox mode is on. You are working with a synthetic dataset. No real data is read or changed." Run this script against the synthetic sandbox only. Stop if the banner is missing.


## Setup

```bash
make dev-up
make seed-stack SEED_PROFILE=small
```

Sign in as the synthetic persona `admin` (policy-store role `admin`).

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
5. Compare counts in `temp/sandbox/bad-event-manifest.json` with what the pipeline accepted and quarantined.
   - Expected: Duplicate, out-of-order and malformed counts in the manifest line up with the accepted and quarantined counts you observe.
   - Permission: operator access to the local stack

## Permissions

Role `admin`: `data.read`, `config.manage`, `policy.manage`. Access is scoped to granted domains; there is no unrestricted bypass.

## Planned (excluded from the demo path)

- Governed copilot chat and chat-driven report creation: the UI route is not in the merged route manifest, so no step uses it.
- Session replay beyond `/replay/traces`: not demonstrated here.
