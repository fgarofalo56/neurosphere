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

For steps 1 to 4:

```bash
make dev-up
make seed-stack SEED_PROFILE=small
```

`SEED_PROFILE=small` has zero bad-event rates, so the seed alone pushes no bad events. Step 5 needs a separate run: `make replay` refuses to run when the hub already holds events (checked 2026-11-03: "hub holds 9653 events, expected 0 or 1653"), so it cannot follow `make seed-stack` on the same emulators. Run step 5 on an empty hub (`make seed-reset`, then `make replay`), which pushes the generator's bad events and rewrites `temp/sandbox/bad-event-manifest.json`. Step 5 was tried on 2026-11-03 and did not work; see its note.

Sign in as the synthetic persona `admin` (policy-store role `admin`). After sign-in, switch sandbox mode on from the user menu (the sandbox toggle) before step 1.

## Steps

1. Open `/workspaces/admin`.
   - Expected: The Admin workspace loads. On the local stack (checked 2026-11-03) it shows its purpose line, "Service answered" and the text "Placeholder: this workspace is built out in later work", so present it as a placeholder, not a finished workspace.
   - Permission: data.read
2. Open `/admin/execution-control`, then `/mcp-admin`.
   - Expected: Both platform control pages load (checked 2026-11-03): execution control shows "Execution is enabled" with a Disable execution control; MCP servers lists three synthetic servers with 0 approved tools. Do not press Disable execution on stage. Controls the role lacks are denied by the API, not just hidden.
   - Permission: config.manage
3. Open `/sandbox`.
   - Expected: The page confirms synthetic data only and lists document counts by kind (checked 2026-11-03: 247 documents, 24 agents, 128 relations on the small profile).
   - Permission: data.read
4. Open `/gateways`, then `/deploy/capabilities`.
   - Expected: `/gateways` says no gateways are registered in this domain on the local stack. `/deploy/capabilities` shows the capability matrix (checked 2026-11-03); unsupported or unverified combinations are disabled with a reason, and availability, release status and authorization scope are separate columns.
   - Permission: data.read (view), config.manage (changes)
5. Compare counts in `temp/sandbox/bad-event-manifest.json` with what the pipeline accepted and quarantined (after `make replay`).
   - Expected: Duplicate, out-of-order and malformed counts in the manifest line up with the accepted and quarantined counts you observe. Checked 2026-11-03 on an empty hub with the app services running: `make replay` pushed all 1653 events, and the worker quarantined all 1653 with reason `invalid_wire` (counted in the `ns-quarantine` blob container of the local Azurite emulator); `ns-archive` stayed empty. So the manifest's duplicate (15), out-of-order (13) and malformed (5) counts could NOT be compared with accepted and quarantined counts, and this step cannot be demonstrated as written. The worker's text log prints only "batch checkpointed" without the counts, and no UI screen shows quarantine counts. Do not present this step until the replay path is fixed or the step is replaced.
   - Permission: operator access to the local stack

## Permissions

Role `admin`: `data.read`, `config.manage`, `policy.manage`, `revocation.manage`, `grant.read`, `grant.write`. Access is scoped to granted domains; there is no unrestricted bypass.

## Planned (excluded from the demo path)

- Governed copilot chat and chat-driven report creation: the UI route is not in the merged route manifest, so no step uses it.
- Session replay beyond `/replay/traces`: not demonstrated here.
