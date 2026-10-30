# Steward walkthrough

> **Status: DRAFT.** Not yet validated by an independent new-user test. See [new-user-test](../runbooks/new-user-test.md).

Persona: **Steward** (policy-store role `domain_steward`, synthetic persona slug `steward` in `sandbox/stack/personas.json`).

Sandbox scenario: `duplicate_agent_candidates`

Review consolidation candidates (always `label: candidate`, never auto-merged) and unused agents (`unused_agent`: active, zero telemetry for the window). The `demo` profile seeds two duplicate pairs and two unused agents.

## Setup

Bring up the stack with [install.md](../runbooks/install.md), then seed (synthetic, idempotent):

```bash
make dev-up
make seed-stack SEED_PROFILE=demo
```

## Steps

1. Open `/workspaces/steward`.
2. Open `/catalog/stale-agents` for the unused agents.
3. Open `/recommendations` and `/review` for duplicate candidates; open an item at `/review/item`.
4. Decide on a candidate. The system shows the exact target and diff, rechecks your permission, honors approvals, audits, and verifies the real change.

## Scope

The Steward acts only inside the domains granted to the role, with approvals where policy requires them. Access is always scoped by your grants in the policy store; there is no unrestricted bypass for any role. Government availability of any feature is gated, see [RESEARCH-AND-GATES.md](../RESEARCH-AND-GATES.md).
