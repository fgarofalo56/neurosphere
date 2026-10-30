# Auditor walkthrough

> **Status: DRAFT.** Not yet validated by an independent new-user test. See [new-user-test](../runbooks/new-user-test.md).

Persona: **Auditor** (policy-store role `security_auditor`, synthetic persona slug `auditor` in `sandbox/stack/personas.json`).

Sandbox scenario: `cost_spike`

Verify that what happened is recorded: trace the seeded cost spike and any actions through the audit trail.

## Setup

Bring up the stack with [install.md](../runbooks/install.md), then seed (synthetic, idempotent):

```bash
make dev-up
make seed-stack SEED_PROFILE=small
```

## Steps

1. Open `/workspaces/auditor`.
2. Open `/audit` and inspect entries; each action records who, the target and version, and the outcome.
3. Open `/actions` and `/actions/detail` to compare a proposed change with the verified result.
4. Open `/reconciliation` to compare cost sources for the spike window.

## Scope

The Auditor reads evidence only. Seeded data is synthetic, so nothing here is evidence of compliance, authorization or ATO. Access is always scoped by your grants in the policy store; there is no unrestricted bypass for any role. Government availability of any feature is gated, see [RESEARCH-AND-GATES.md](../RESEARCH-AND-GATES.md).
