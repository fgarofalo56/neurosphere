# PRP-13 item 4: migrations runner on the Cosmos vNext emulator

- Date: 2026-10-18
- Environment: local `docker compose` emulator stack, container `neurosphere-cosmos-1`
  (`mcr.microsoft.com/cosmosdb/linux/azure-cosmos-emulator:vnext-latest`). No cloud account,
  no paid calls, synthetic snapshot data only (`neurosphere_core.migrations.synthetic_snapshot`).
- Code: `packages/core/neurosphere_core/migrations/` (merged in 9a0847d on the PRP-13
  integration branch).
- Command: `uv run pytest tests/integration/migrations -m integration -v`

## Raw output (tail)

```text
collecting ... collected 5 items

tests/integration/migrations/test_concurrent_runners.py::test_exactly_one_runner_applies PASSED [ 20%]
tests/integration/migrations/test_forward_rollback.py::test_dry_run_then_forward_then_rollback PASSED [ 40%]
tests/integration/migrations/test_forward_rollback.py::test_ledger_records_applied_versions PASSED [ 60%]
tests/integration/migrations/test_idempotent.py::test_second_forward_is_noop PASSED [ 80%]
tests/integration/migrations/test_idempotent.py::test_new_runner_instance_skips_applied_steps PASSED [100%]

============================== 5 passed in 3.27s ==============================
```

The in-process unit suite (`packages/core/tests/migrations`, 26 tests, unmarked) covers the
same forward/rollback hash round trip, idempotent second forward, dry-run and concurrent
runner behaviour against the in-memory stores and runs in CI.

## What this does and does not show (G12)

Shown: forward then rollback restores the original documents (canonical JSON hash,
Cosmos system fields excluded); a second forward writes nothing; of two concurrent runners
exactly one takes the ledger lease and the other gets `stale_version`; conditional
`replace_item` with ETag + `IfNotModified` works on the vNext emulator.

Not shown: index behaviour, RU cost, throttling (429) and 5xx handling against a real store,
and behaviour on a live Cosmos account. These remain under G12 (emulator parity), which stays
OPEN. This is bounded-feasibility evidence only.
