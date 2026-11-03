---
status: draft
persona: steward
walkthrough: docs/walkthroughs/steward.md
sandbox_scenario: duplicate_agent_candidates
claims:
  - "Duplicate pairs are shown as candidates and are never auto-merged"
  - "Decisions show the exact target and diff and are audited"
permissions:
  - data.read
  - grant.read
  - data.export
  - report.create
  - action.propose
  - catalog.curate
  - action.approve
  - action.execute
  - grant.write
---

# Steward demo script

Follows [docs/walkthroughs/steward.md](../../docs/walkthroughs/steward.md). Sandbox scenario: `duplicate_agent_candidates`.

Show a steward reviewing consolidation candidates and unused agents. The demo profile seeds two duplicate pairs and two unused agents.

## Isolation

Sandbox mode defaults to off and the banner appears only once it is on. Before step 1, switch it on from the user menu (the sandbox toggle), then confirm the banner is visible at the top of every screen: "Sandbox mode is on. You are working with a synthetic dataset. No real data is read or changed." Run this script against the synthetic sandbox only. Stop if the banner is missing.


## Setup

```bash
make dev-up
make seed-stack SEED_PROFILE=demo
```

Sign in as the synthetic persona `steward` (policy-store role `domain_steward`). After sign-in, switch sandbox mode on from the user menu (the sandbox toggle) before step 1.

## Steps

1. Open `/workspaces/steward`.
   - Expected: The Steward landing workspace loads with the sandbox banner shown.
   - Permission: data.read
2. Open `/recommendations` and find the `unused_agent` and duplicate-agent items.
   - Expected: The unused agents (active, zero telemetry for the window) appear as `unused_agent` recommendations. Duplicate pairs are labelled `candidate`. Nothing is merged automatically. Checked 2026-11-03: on the `small` seed profile neither kind appears at all, so this step needs `SEED_PROFILE=demo`. On `demo`, the Customer Support domain showed one `unused_agent` recommendation and no `candidate_duplicate` ones (other domains were not checked). Pick the domain in the domain selector and show only what appears. The `demo` seed can also be throttled by the Event Hubs emulator on the first run ("server-busy"); re-running `make seed-stack SEED_PROFILE=demo` completed it.
   - Permission: data.read
3. Open `/review`.
   - Expected: The review queue lists the seeded items for this domain (checked 2026-11-03 on the small profile: four pending, unassigned `recommendation` items for cost spikes, each with an SLA due about 24 hours out).
   - Permission: data.read
4. Open an item at `/review/item` and inspect it. Do not expect a change to be applied.
   - Expected: (checked 2026-11-03) the review item screen shows kind, state, subject, assignee, SLA, escalation level, created time and decisions ("No decisions yet"), with Claim, Approve and Reject controls. It does not show a diff or an "Advisory only" line; the exact target and diff are on the actions screens, not here. Do not press Approve or Reject in the demo. For a confirmed change outside the seeded demo, the executor rechecks permission, honors any required approval, writes an audit entry and verifies the real change.
   - Permission: data.read (inspect), action.approve and action.execute (confirm, not exercised by the seeded demo)

## Permissions

Role `domain_steward`: `data.read`, `grant.read`, `data.export`, `report.create`, `action.propose`, `catalog.curate`, `action.approve`, `action.execute`, `grant.write`. Access is scoped to granted domains; there is no unrestricted bypass.

## Not on the demo path

- `/catalog/stale-agents` is a dry-run plus confirm "mark stale" tool that needs `catalog.curate`; confirming writes state, and it does not list unused agents. Use the `unused_agent` recommendations instead.

## Planned (excluded from the demo path)

- Governed copilot chat and chat-driven report creation: the UI route is not in the merged route manifest, so no step uses it.
- Session replay beyond `/replay/traces`: not demonstrated here.
