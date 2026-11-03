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
  - catalog.curate
  - action.approve
  - action.execute
---

# Steward demo script

Follows [docs/walkthroughs/steward.md](../../docs/walkthroughs/steward.md). Sandbox scenario: `duplicate_agent_candidates`.

Show a steward reviewing consolidation candidates and unused agents. The demo profile seeds two duplicate pairs and two unused agents.

## Isolation

Before step 1, confirm the sandbox banner is visible at the top of every screen: "Sandbox mode is on. You are working with a synthetic dataset. No real data is read or changed." Run this script against the synthetic sandbox only. Stop if the banner is missing.


## Setup

```bash
make dev-up
make seed-stack SEED_PROFILE=demo
```

Sign in as the synthetic persona `steward` (policy-store role `domain_steward`).

## Steps

1. Open `/workspaces/steward`.
   - Expected: The Steward landing workspace loads with the sandbox banner shown.
   - Permission: data.read
2. Open `/catalog/stale-agents`.
   - Expected: The unused agents (active, zero telemetry for the window) are listed.
   - Permission: data.read
3. Open `/recommendations`, then `/review`.
   - Expected: Duplicate pairs appear labelled `candidate`. Nothing is merged automatically.
   - Permission: data.read
4. Open an item at `/review/item` and decide on it.
   - Expected: The screen shows the exact target and diff. On decision the system rechecks permission, honors any required approval, writes an audit entry and verifies the real change.
   - Permission: action.approve, action.execute

## Permissions

Role `domain_steward`: `data.read`, `catalog.curate`, `action.approve`, `action.execute`. Access is scoped to granted domains; there is no unrestricted bypass.

## Planned (excluded from the demo path)

- Governed copilot chat and chat-driven report creation: the UI route is not in the merged route manifest, so no step uses it.
- Session replay beyond `/replay/traces`: not demonstrated here.
