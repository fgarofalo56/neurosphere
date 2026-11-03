---
status: draft
persona: auditor
walkthrough: docs/walkthroughs/auditor.md
sandbox_scenario: cost_spike
claims:
  - "Actions are recorded with who, target, version and outcome"
  - "Seeded data is synthetic and is not evidence of any authorization"
permissions:
  - audit.read
  - evidence.read
---

# Auditor demo script

Follows [docs/walkthroughs/auditor.md](../../docs/walkthroughs/auditor.md). Sandbox scenario: `cost_spike`.

Show an auditor tracing a seeded cost spike and actions through the audit trail.

## Isolation

Before step 1, confirm the sandbox banner is visible at the top of every screen: "Sandbox mode is on. You are working with a synthetic dataset. No real data is read or changed." Run this script against the synthetic sandbox only. Stop if the banner is missing.


## Setup

```bash
make dev-up
make seed-stack SEED_PROFILE=small
```

Sign in as the synthetic persona `auditor` (policy-store role `security_auditor`).

## Steps

1. Open `/workspaces/auditor`.
   - Expected: The Auditor landing workspace loads with the sandbox banner shown.
   - Permission: audit.read
2. Open `/audit` and inspect entries.
   - Expected: Each entry records who acted, the target and version, and the outcome.
   - Permission: audit.read

## Permissions

Role `security_auditor`: `audit.read`, `evidence.read`. Access is scoped to granted domains; there is no unrestricted bypass.

## Not on the demo path

The walkthrough also lists `/actions`, `/actions/detail` and `/reconciliation`. In the role map the `security_auditor` role holds `audit.read` and `evidence.read` and no `data.read`, while those screens read data. Expect access-denied for the Auditor persona on them until verified against a running stack. Do not present them as Auditor capabilities. Show them with the Steward persona instead.

## Planned (excluded from the demo path)

- Governed copilot chat and chat-driven report creation: the UI route is not in the merged route manifest, so no step uses it.
- Session replay beyond `/replay/traces`: not demonstrated here.
