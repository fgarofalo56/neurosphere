# Viewer walkthrough

> **Status: DRAFT.** Not yet validated by an independent new-user test. See [new-user-test](../runbooks/new-user-test.md).

Persona: **Viewer** (policy-store role `viewer`, synthetic persona slug `viewer` in `sandbox/stack/personas.json`).

Sandbox scenario: `cost_spike`

Read-only view of a seeded cost spike (tokens 12x and volume 3x inside a window; ground truth in `anomaly-manifest.json`).

## Setup

Bring up the stack with [install.md](../runbooks/install.md), then seed (synthetic, idempotent):

```bash
make dev-up
make seed-stack SEED_PROFILE=small
```

For a quick look without Docker, `pnpm demo` serves fixture data from a mock API. Its signed-in persona is Steward, so other personas' workspaces show access-denied by design.

## Steps

1. Open `/workspaces/viewer` for your landing view.
2. Open `/dashboards/cost` and find the spike window. Compare it with the injected window in `temp/sandbox/anomaly-manifest.json` (written by `make sandbox-generate`).
3. Open `/map` to see which agents are involved, then `/catalog` to read an agent's entry.

## Scope

The Viewer reads only; no action, export or edit path is offered. Access is always scoped by your grants in the policy store; there is no unrestricted bypass for any role. Government availability of any feature is gated, see [RESEARCH-AND-GATES.md](../RESEARCH-AND-GATES.md).
