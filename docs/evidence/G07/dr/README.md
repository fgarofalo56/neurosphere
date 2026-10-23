# G07 restore drill evidence (PRP-21 item 5)

Environment label: **compose, not representative of production**.

`restore-drill-compose-2026-10-22.json` is the record of one drill run on the compose emulators
(Cosmos vNext, Azurite, Event Hubs emulator running; the drill itself uses Cosmos and Azurite).

- Method: seed drill-namespaced stores from the sandbox generator (seed 7, tiny profile,
  synthetic only); export each store; write 12 more documents and advance a checkpoint after the
  backup; delete the `drill-<run>` Cosmos database and blob containers; restore from the export;
  compare count and content-hash digests of the live restored store with the digests taken
  before the backup. Search is rebuilt from the restored catalog into the in-process fixture
  index and compared by a hash of fixed query answers.
- Result: all 8 stores match. Per-store restore time, summed restore time (5.0 s) and recovery
  point gap (2.2 s) are in the JSON and in `docs/ops/dr-runbook.md` beside the provisional
  targets (RTO 4 h, RPO 15 min), which are targets and not results.
- The git SHA in the JSON is the commit containing the scripts that produced it.
- Limits: tens of kilobytes of synthetic data; one machine; emulators. A restore drill proves a
  restore, not a failover. The recovery point gap follows from a test-chosen interval.

Reproduce (from the repository root):

```
docker compose up -d --wait
uv run python infra/dr/ns_dr.py drill --evidence-dir docs/evidence/G07/dr
docker compose down
```

## Still OPEN

Real Event Hubs failover and failback; Event Hubs data geo-replication (Premium/Dedicated,
Government unverified); production-sized restore; Azure AI Search index rebuild time; replay
through a live pipeline from the redacted archive. G07 stays OPEN.
