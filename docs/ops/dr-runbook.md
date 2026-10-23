# DR runbook: backup, restore, failover and failback

Status: PRP-21 item 5. Gate G07 (workload/SLO/DR) stays OPEN. This runbook states what was
measured, where, and what has not been run. Nothing here is a service commitment.

## 1. Targets and measurements

The recovery targets are provisional planning targets from the PRD (section 3), to be measured:

- Recovery time: 4 h is the provisional target.
- Recovery point: 15 min is the provisional target.

Measured values, stated beside those targets and never instead of them:

| Measurement | Value | Provisional target | Environment |
|---|---|---|---|
| Sum of per-store restore times (8 stores, sequential) | 5.0 s | 4 h (provisional target) | compose, not representative of production |
| Recovery point gap in the drill | 2.2 s | 15 min (provisional target) | compose, not representative of production |

Environment label for every number in this section: **compose, not representative of
production**. Data set: sandbox generator seed 7, tiny profile, synthetic only (a few hundred
documents per store, under 0.5 MB in total). Run date 2026-10-22, git SHA
`66a5c41709f597cbb5f15063df17d951eeb3f855`. Raw record, method and digests:
`docs/evidence/G07/dr/restore-drill-compose-2026-10-22.json`.

Measured restore time per store (compose, not representative of production):

| Store | Documents/blobs | Restore time | Verification |
|---|---|---|---|
| Cosmos `cost-ledger` | 400 | 1.81 s | count and content hash match |
| Cosmos `outbox` | 400 | 1.67 s | count and content hash match |
| Cosmos `catalog` | 57 | 0.28 s | count and content hash match |
| Cosmos `aggregates` | 68 | 0.32 s | count and content hash match |
| Blob redacted archive | 40 | 0.49 s | count, metadata and content hash match |
| Quarantine container | 25 | 0.35 s | hash match; `BlobQuarantineReader` lists all 25 |
| Checkpoint store | 8 | 0.07 s | hash match; `BlobCheckpointStore` rows equal the snapshot |
| Search index | 57 documents | 0.01 s | rebuilt from restored catalog; query-answer hash matches |

Recovery point gap: the interval from the newest write contained in the backup to the simulated
loss. The drill wrote 12 more documents and advanced a checkpoint after the backup; after the
restore those 12 documents were absent and the checkpoint was back at the snapshot value. The
2.2 s figure reflects a test-chosen interval of seconds, not a backup cadence, so it says nothing
about whether a 15 min cadence would meet the provisional target. Restore times on tens of
kilobytes say nothing about a production-sized restore.

What the drill is not: a restore drill proves a restore, not a failover. It exercises no
Event Hubs namespace pairing, no DNS change, no private-endpoint path and no cross-region step.

## 2. Backup and restore scripts

`infra/dr/ns_dr.py` (details in `infra/dr/README.md`):

```
uv run python infra/dr/ns_dr.py backup  --out DIR --database DB --cosmos-container C --blob-container B
uv run python infra/dr/ns_dr.py restore --from DIR --database DB --cosmos-container C --blob-container B
uv run python infra/dr/ns_dr.py drill --evidence-dir docs/evidence/G07/dr
```

Defaults address the compose emulators only. A non-local endpoint is refused unless
`NS_LIVE_APPROVED=1` and `--target NAME` are both given; a restore to a non-local target also
requires `--confirm-target NAME` equal to `--target`. Restore upserts and never deletes. The
drill touches only `drill-` namespaced resources.

Per-store approach: Cosmos documents are exported and upserted; the blob archive, quarantine
container and checkpoint store are exported with metadata and re-uploaded with hash checks; the
search index is derived data and is rebuilt from the restored catalog (the drill uses the
in-process fixture index because compose has no search emulator; an Azure AI Search rebuild
time is not measured). In Azure, native Cosmos continuous backup and point-in-time restore and
blob versioning or soft delete are the production-scale mechanisms; these scripts do not replace
them and were not exercised against them.

## 3. Event data: what restores it

Event data is not recovered by a store restore.

- The Event Hubs emulator has no persistence, so on compose event data is recovered by replay
  from the redacted archive plus the source producers, using `scripts/replay/` (quarantine
  replay) and the ingestion pipeline's dedupe. This is the compose-testable path. The drill
  restores the archive blobs but does not replay them through a live pipeline.
- Event Hubs metadata geo-DR copies neither event payloads nor Entra RBAC assignments. It is
  insufficient for an event-data recovery point, whatever the stated recovery point target.
- Event Hubs data geo-replication replicates data, but it is available on Premium and Dedicated
  tiers only, and Government support is unverified. Treat it as an option that requires a live
  test in an approved environment (gate G01 tracks Government availability). No such test has
  run.

## 4. Failover and failback procedure (not yet exercised)

This procedure is written from the references in section 8 and has not been run against real
resources. Run it first in a non-production namespace pair with `NS_LIVE_APPROVED=1` and operator
approval for any paid resource.

Preconditions (check on both sides, primary and secondary):

1. Checkpoint store. Event Hub consumers checkpoint to blob storage. Confirm the checkpoint
   container is reachable from the secondary region and holds current checkpoints (either
   geo-redundant storage or a restored copy from section 2). If checkpoints are older than the
   data, consumers re-read from the older offset: ingestion dedupe must make that idempotent.
   Checkpoints advance only after durable accept or quarantine; never advance them by hand.
2. Encryption keys. Confirm the customer-managed key (if used) is retained, enabled, and
   accessible to the secondary resources' identities; key vault soft delete and purge protection
   stay on; key rotation during the incident is paused until failback finishes. A restore that
   cannot decrypt is not a restore.
3. DNS. Confirm the alias or DNS record clients use, its TTL, and who may change it. Lower the TTL
   ahead of planned failover. Check resolution from inside the network, not only the internet.
4. Private endpoints. Where private endpoints are used, they must be configured on both sides
   (primary and secondary namespaces) with matching private DNS zones before the incident. A
   failover to a namespace that has no reachable endpoint is an outage.
5. Identity and RBAC. Metadata geo-DR does not copy Entra RBAC: assign the producer and consumer
   roles on the secondary namespace in advance and verify them.
6. Model endpoint. Foundry provides no automatic application disaster recovery or failover. The
   model deployment endpoint does not fail over with the platform. Deploy and test the secondary
   model deployment and its configuration yourself; the catalog must point at an endpoint that
   works in the surviving region. Do not describe the model endpoint as failing over.
7. Cloud boundary. A Government deployment fails over only to another Government region.
   Government data is never bridged to Commercial to fill a gap.

Failover:

1. Declare the incident and record the time (start of the measured recovery time).
2. Stop or pause producers and consumers that would write to the primary.
3. Initiate failover of the namespace pairing (metadata geo-DR) or promote the replica (data
   geo-replication, where available). Wait for completion; do not assume it is instant.
4. Repoint consumers using the alias or the DNS change prepared in precondition 3.
5. Start consumers from the checkpoints verified in precondition 1.
6. Restore any lost stores from backup (section 2) and rebuild the search index from the
   restored catalog.
7. Replay from the redacted archive and re-send from source producers to cover the gap between
   the last replicated or checkpointed point and the incident (section 3).
8. Verify: record counts and content hashes against the last known digests, ingestion lag
   draining, projections caught up, dashboards reading from the new side.

Failback:

1. Re-establish the pairing or replica toward the original primary and let it catch up.
2. Re-check all seven preconditions on the original side, including DNS and private endpoints.
3. Schedule a window, pause producers, confirm checkpoints, switch back, restart consumers from
   verified checkpoints, and verify as in step 8.
4. Record the end time (the measured recovery time for the exercise) and the observed recovery
   point gap, with the environment label, in `docs/evidence/G07/dr/`.

## 5. Open items

Not run, therefore OPEN under G07:

- Real Event Hubs failover and failback (needs an approved environment).
- Event Hubs data geo-replication on Premium or Dedicated, and its Government availability.
- Production-sized restore time and recovery point.
- Azure AI Search index rebuild time.
- Replay through a live pipeline from the redacted archive.

## 6. Claims boundary

This document makes no authorization, certification or availability commitment. The numbers in
section 1 are measurements from emulators on one machine.

## 7. Test coverage

`tests/integration/dr/test_restore_compose.py` runs the drill (integration marker; fails when
the emulators are unreachable). `tests/integration/dr/test_runbook_caveats.py` guards the
caveats in this document. `tests/integration/dr/test_target_refusal.py` covers the target rules.

## 8. External references

- Event Hubs data geo-replication (GA on Premium and Dedicated):
  https://learn.microsoft.com/azure/event-hubs/geo-replication (retrieved 2026-07-11).
- Event Hubs metadata geo-DR (no payloads, no Entra RBAC; private endpoints on both sides):
  https://learn.microsoft.com/azure/event-hubs/event-hubs-geo-dr (retrieved 2026-10-06).
- Foundry high availability (no automatic application DR):
  https://learn.microsoft.com/azure/foundry/how-to/high-availability-resiliency (retrieved 2026-10-06).
- Event Hubs emulator limits:
  https://learn.microsoft.com/azure/event-hubs/overview-emulator (retrieved 2026-08-26).
- Cosmos DB vNext Linux emulator limits:
  https://learn.microsoft.com/azure/cosmos-db/emulator-linux (GA June 2026).
