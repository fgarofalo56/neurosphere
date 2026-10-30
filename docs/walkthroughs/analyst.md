# Analyst walkthrough

> **Status: DRAFT.** Not yet validated by an independent new-user test. See [new-user-test](../runbooks/new-user-test.md).

Persona: **Analyst** (policy-store role `analyst`, synthetic persona slug `analyst` in `sandbox/stack/personas.json`).

Sandbox scenario: `latency_regression`

Investigate a seeded latency regression (durations 3x from the window start to the end) and use a saved report.

## Setup

Bring up the stack with [install.md](../runbooks/install.md), then seed (synthetic, idempotent):

```bash
make dev-up
make seed-stack SEED_PROFILE=small
```

## Steps

1. Open `/workspaces/analyst`.
2. Open `/dashboards/latency` and locate the regression. The affected agents are listed in `temp/sandbox/anomaly-manifest.json`.
3. Open `/replay/traces` to replay a trace through an affected agent.
4. Open `/reports`. The seed saves the synthetic reports `agents-by-version` and `agent-inventory` (see `sandbox/stack/reports.json`) for the analyst persona. Reports run under your own scope on every run.

## Scope

The Analyst queries and builds reports within granted domains using bounded structured queries; changes go through approvals, not direct edits. Access is always scoped by your grants in the policy store; there is no unrestricted bypass for any role. Government availability of any feature is gated, see [RESEARCH-AND-GATES.md](../RESEARCH-AND-GATES.md).
