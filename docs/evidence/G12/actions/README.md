# G12 evidence: PRP-17 action plane (in-process slice and Cosmos emulator)

Date: 2026-10-20. Gate G12 (emulator parity) stays OPEN. G05 (model swap compatibility) also
stays OPEN: no live run happened (operator decision), so nothing here shows that a real Foundry
deployment was changed. This document records what the action plane tests exercise and, just as
important, what they cannot.

## What was run

Two suites back the PRP-17 claims. Neither makes a network call to Azure.

### 1. In-process vertical slice (CI, unmarked)

```
uv run pytest tests/integration/actions/test_action_vertical_slice.py -q
```

The real FastAPI app from `create_app` with the dev-issuer JWT validator, policy-derived
`IdentityScope` and the routers from the default registry (`/api/v1/actions`, `/api/v1/review`).
`configure_action_plane` is wired over in-memory intent, HITL and audit stores, a
`PolicyPermissionRechecker` reading the same in-memory policy repository the API derives scope
from (plus a revocation list), and `RecheckerReviewerAuthorizer`. The write target is the real
`FoundryModelSwapConnector` over its `httpx.MockTransport` fake ARM
(`connectors/reference/foundry-actions/tests/foundry_swap_fakes.py`), driven by the real
`ActionExecutor` with the review-item completion hook.

| Scenario | What is asserted |
|---|---|
| happy path | maker drafts, validates, presents, confirms over REST; a second steward approves; the executor swaps the model; the status endpoint reports `succeeded` with `verify_matched`; the fake ARM read-back shows the new model version after exactly one PUT; the maker-checker review item is `executed`; the audit chain verifies and brackets the apply with `before`/`after` records |
| repeat pass | a second executor pass over a finished intent makes no further ARM call |
| self-approval | the maker approving gets 403 `self_approval_forbidden`; no PUT |
| Viewer approve | 403 problem+json; intent and review item unchanged |
| revoked after approval | (a) steward role removed from the live policy, (b) principal revoked: the executor blocks, intent `failed` `permission_revoked`, zero ARM requests, a `denied` audit record, review item `failed` |
| verify mismatch | the fake ARM reports another version after the PUT: verify fails, a restore PUT runs, intent `rolled_back`, model back to the original, review item `failed` |
| emergency disable | `PUT /emergency-disable` on: the executor makes zero ARM calls and the intent stays `executing`; off: the same intent completes |
| read-only credential | the connector factory returns the advisory connector, the registry refuses it; draft and validate work; `confirm` and `approve` return 409 `capability_unavailable` `advisory_connector`; zero PUTs; the intent stays `awaiting_confirmation`; no review item |
| Government | a Government target on a Commercial deployment is refused at draft (403 `target_out_of_scope`, nothing stored, no ARM call); a Government account yields an advisory connector with no ARM request; nothing is rerouted to Commercial |
| policy store outage | scope derivation outage is 503 problem+json; the executor defers (zero ARM calls) and completes after recovery |
| hash equality | a `button` and a `rest` draft of the same change yield the same `confirmation_hash` (PRP-17 D1) |

No catalog repository is wired into the action plane, so "no catalog document changed" is shown
by construction (the plane has no catalog dependency; `tests/security/actions` also asserts the
single executor path) and by the assertions above that the only state that moved was the intent,
the HITL item, the audit chain and the fake ARM.

### 2. Cosmos emulator test (needs compose)

```
docker compose up -d --wait
uv run pytest -m integration tests/integration/actions/test_intent_store_cosmos.py
```

`CosmosIntentStore` and `CosmosExecutionControl` against the vNext emulator, one container per
test (8 tests): hierarchical key `/customer_id`,`/domain_id`, create-only idempotency lookup
documents (409), ETag-conditional replace (412), repair of a crash between lookup and intent
write, one-winner concurrent creates, a service lifecycle that executes once, paging and the
cross-partition due scan, and the kill-switch round trip.

## Emulator versus live deltas (all OPEN)

- **No RU accounting.** The emulator reports no request charge, so RU cost of the intent
  create (two documents), the idempotency lookup, the cross-partition `expire_due` scan and the
  executor lease renewals (an ETag'd replace every minute during an apply) is unmeasured.
- **No Entra, no data-plane RBAC.** The emulator is key-authenticated and enforces no role. The
  real boundary (managed identity with Cosmos data-plane roles, database and container creation
  through the control plane) is not exercised; the slice uses the dev issuer and in-memory
  policy.
- **No throttling.** 429 handling (`rate_limited`) is covered with injected errors only.
- **Hierarchical partition key behaviour is proven on the emulator only.** Cross-partition fan-out
  cost, partition splits and the prefix-query behaviour on a real account are not observed.
- **No stored procedures or triggers** (emulator limit and design choice): idempotency relies on
  create-only semantics and ETag preconditions, which the emulator honours. Whether a real
  multi-region account behaves identically under write conflicts is untested.
- **HITL store is in-memory only.** There is no Cosmos HITL store (PRP-17 D7). Review items,
  decisions and timers survive a restart only in the in-memory restart test, not in a real
  store. A Cosmos HITL store is a follow-up and OPEN.
- **Executor state is exercised on the in-memory store in the slice**; crash recovery on the
  Cosmos store is covered only by the item 1 lifecycle test, not by an executor fault injection.
- **The target is a fake ARM.** The real ARM PUT shape, provisioning polling, etag semantics,
  permission-list answers and Government behaviour are unverified until the G05 live script runs
  with `NS_LIVE_APPROVED=1`. There is no traffic-split canary for in-place Foundry swaps (the
  canary phase is verify-only), and the etag check before the PUT is not atomic.
