# Admin walkthrough

> **Status: DRAFT.** Not yet validated by an independent new-user test. See [new-user-test](../runbooks/new-user-test.md).

Persona: **Admin** (policy-store role `admin`, synthetic persona slug `admin` in `sandbox/stack/personas.json`).

Sandbox scenario: `bad_events`

Operate the platform against messy input: the generator injects duplicate, out-of-order and malformed events (`sandbox/bad_events.py`, summarised in `bad-event-manifest.json`) so quarantine and replay can be observed.

## Setup

Bring up the stack with [install.md](../runbooks/install.md), then seed and replay (synthetic, idempotent):

```bash
make dev-up
make seed-stack SEED_PROFILE=small
make replay
```

## Steps

1. Open `/workspaces/admin`, then `/admin/execution-control` and `/mcp-admin` for platform controls.
2. Open `/sandbox` to confirm you are looking at isolated synthetic data.
3. Open `/gateways` and `/deploy/capabilities` to see which features the cloud and region allow; unsupported combinations are disabled.
4. Compare the counts in `temp/sandbox/bad-event-manifest.json` with what the pipeline accepted and quarantined.

## Scope

Admin is a scoped role. Privileged grants are time-bound; renew with `make grant-operator OPERATOR_OID=<object-id> OPERATOR_ROLE=admin`. There is no unrestricted bypass for any role. Government availability of any feature is gated, see [RESEARCH-AND-GATES.md](../RESEARCH-AND-GATES.md).
