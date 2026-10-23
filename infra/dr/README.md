# infra/dr - per-store backup, restore and the restore drill (PRP-21 item 5)

Scripts, not a package: modules are imported by name from this directory
(`tests/integration/dr/conftest.py` adds it to `sys.path`). Procedure and caveats:
`docs/ops/dr-runbook.md`. Measurements: `docs/evidence/G07/dr/`.

| File | Role |
|---|---|
| `ns_dr.py` | CLI: `backup`, `restore`, `drill` |
| `ns_dr_safety.py` | Target rules: local emulators by default; live targets gated |
| `ns_dr_emulator.py` | Emulator connection settings (no credential literal; env names only) |
| `ns_dr_stores.py` | Per-store export, restore and content digests |
| `ns_dr_drill.py` | Seed, back up, lose, restore, verify, measure |

## Stores

| Store | Backup | Restore |
|---|---|---|
| Cosmos documents (`cost-ledger`, `outbox`, `catalog`, `aggregates`) | export each container to `cosmos/<container>.jsonl`, system `_*` fields stripped | create database/containers if missing, upsert (never deletes) |
| Blob archive (redacted archive, PRP-07) | export every blob with metadata to `blobs/<label>.jsonl` | create container if missing, upload with overwrite, verify each blob hash |
| Quarantine container | same blob export (`records/`, `replayed/` prefixes) | same; verified through `BlobQuarantineReader` |
| Checkpoint store (Event Hubs checkpoints in Azurite) | same blob export | same; verified through `BlobCheckpointStore.list_checkpoints` |
| Search index | none: derived data | rebuild from the restored catalog. There is no search emulator on compose, so the drill rebuilds the in-process fixture index (`FixtureSearchIndex`) and compares a hash of fixed query answers. Azure AI Search rebuild is not exercised here |
| Event Hubs event data | none: the emulator has no persistence | replay from the redacted archive plus source producers (`scripts/replay/`, read-only here); see the runbook |

## Safety

- Default endpoints are `localhost`/`127.0.0.1` emulators (`NS_COSMOS_ENDPOINT`,
  `NS_COSMOS_KEY`, `NS_BLOB_CONNECTION_STRING` override; `.env` is never read).
- A non-local endpoint is refused unless `NS_LIVE_APPROVED=1` **and** `--target NAME` are given;
  a non-local restore also needs `--confirm-target NAME` equal to `--target`. Hosts are compared
  by parsed hostname. Exit code 2 means refused.
- `restore` upserts and never deletes. The drill creates, overwrites and deletes only
  `drill-<run>` databases/containers (enforced by `require_drill_name`) and seeds its own
  synthetic data (sandbox generator, seed 7).

## Run

```
docker compose up -d --wait
uv run python infra/dr/ns_dr.py drill --evidence-dir docs/evidence/G07/dr
uv run pytest -m integration tests/integration/dr -q
docker compose down
```
