# Contingency plan

> **Scope:** Backup, restore, failover and failback of a customer-hosted NeuroSphere deployment; what has been measured, what has not.
> **Status vocabulary:** `designed`, `implemented_tested`, `inherited`, `customer`, `planned`, `not_applicable`.
> **Statement:** NeuroSphere is not FedRAMP authorized; the authorizing official decides. This document supports the customer security team and the authorizing official. It is not an assessment, makes no authorization, ATO, parity or certification claim, and carries no authorization date or compliance score.
> **Provenance:** PRP-23 item 4. Customer-owned inputs are recorded as `customer` and OPEN; they are never guessed here.

This plan points at the operational procedure and the measurements; it does not duplicate them. Procedure: [DR runbook](../../ops/dr-runbook.md) (PRP-21). Boundaries: [boundary and data-flow diagrams](boundary-and-data-flow.md). Incident handling: [incident response plan](incident-response-plan.md). Responsibility split: [responsibility matrix](../responsibility-matrix.md).

## 1. Recovery objectives

There are no recovery guarantees in this document. The PRD carries provisional planning targets (recovery time and recovery point); they are targets to be measured, owned and accepted by the customer, and are recorded in the DR runbook and `docs/ops/slo.md`, not restated here as commitments. The customer's own business impact analysis, system categorization and the objectives they require are `customer` inputs, OPEN.

## 2. What was actually measured

One restore drill, recorded in `docs/evidence/G07/dr/`:

- `restore-drill-compose-2026-10-22.json` is the raw record: run id, git SHA of the scripts, method, per-store counts, content-hash digests before and after, backup and restore seconds, the notes and the open list.
- `README.md` in the same directory states the method and limits.

What the drill measured, verbatim in scope: a sandbox-generated synthetic data set (seed 7, tiny profile, under 0.5 MB in total) was exported from eight stores on the compose emulators (four Cosmos containers: cost-ledger, outbox, catalog, aggregates; the redacted archive, quarantine and checkpoint blob containers; the search index rebuilt from the restored catalog into the in-process fixture index). After deleting the drill namespace and restoring, all eight stores matched on count and content hash. The summed restore time was about five seconds, and the recovery point gap was about two seconds because the test chose a seconds-long interval between the last backed-up write and the simulated loss. The 12 post-backup writes were absent after restore and the checkpoint rewound to the snapshot, as designed; ingestion dedupe makes the re-read idempotent.

What those numbers do not show: the environment is labelled "compose, not representative of production" in the evidence itself. The data is tens of kilobytes on one machine against emulators. A restore drill proves a restore, not a failover. The two-second gap says nothing about a real backup cadence. The numbers must not be quoted as expected production recovery performance.

Not run, OPEN (G07 stays OPEN; recorded in the evidence `open` list):

- Real Event Hubs failover and failback.
- Event Hubs data geo-replication (Premium or Dedicated tiers; Government availability unverified).
- Production-sized restore time and recovery point.
- Azure AI Search index rebuild time.
- Replay from the redacted archive through a live pipeline (the drill restores the archive blobs but does not replay them).
- The documented failover and failback procedure itself, which has not been exercised against real resources.

## 3. Event Hubs caveat

Event Hubs metadata geo-disaster recovery copies neither event payloads nor Entra RBAC role assignments. Pairing namespaces therefore protects the namespace configuration and an alias, not the data in flight, and RBAC on the secondary namespace must be assigned and verified in advance. Event Hubs data geo-replication is a separate feature that does replicate data; it is limited to certain tiers and its Government availability is unverified. Neither option is claimed here as tested. On compose the Event Hubs emulator has no persistence, so the testable event-data path is replay from the redacted archive plus the source producers, using the replay tooling and ingestion dedupe. Sources are cited in the DR runbook.

## 4. Recovery order and dependencies

| Priority | Component | Recovery basis | Status |
|---|---|---|---|
| 1 | Identity, Key Vault and keys | Customer-owned; keys retained, soft delete and purge protection on; rotation paused during an incident | `customer` |
| 2 | Append-only audit store | Recover and verify chain continuity before resuming privileged actions; never edit or delete | `designed`; production-scale backup not exercised |
| 3 | Cosmos stores (catalog, outbox, cost ledger, aggregates) | Native continuous backup and point-in-time restore at production scale; export and upsert scripts in compose | restore `implemented_tested` on compose only |
| 4 | Redacted archive, quarantine, checkpoints | Blob versioning or soft delete at production scale; export and re-upload in compose | restore `implemented_tested` on compose only |
| 5 | Event Hubs | Section 3 | failover `planned`, not exercised |
| 6 | Search index | Derived data; rebuild from the restored catalog | rebuild time not measured, OPEN |
| 7 | Projections and hot aggregates | Rebuilt from the outbox baseline; UI shows lag and coverage | `designed` |
| 8 | Model endpoint | No automatic application failover; the secondary deployment is deployed and tested by the customer, and the catalog must point at a working endpoint | `customer` |

## 5. Boundary rules during contingency

A Government deployment recovers only into another Government region; a Commercial deployment only into Commercial. Government data is never copied to Commercial to shorten recovery, even temporarily. If no approved region is available, the service stays down or degraded and that is recorded; no cross-cloud workaround is permitted. A feature disabled for lack of availability stays disabled.

## 6. Activation, roles and testing

- Activation criteria, notification list, alternate site and call tree: `customer` inputs, OPEN. The incident lead and roles in the [incident response plan](incident-response-plan.md) apply until the customer names its own.
- Any live failover or restore against real resources needs an approved environment, operator approval for paid resources, and `NS_LIVE_APPROVED=1`. A test that did not run is reported OPEN, never as a skipped pass.
- Test cadence and the after-action review owner are `customer` inputs. Each exercise records its start and end time, observed recovery point gap and environment label in `docs/evidence/G07/dr/`.

## 7. Status summary

| Capability | Status |
|---|---|
| Backup and restore scripts, compose drill | `implemented_tested` (compose only, synthetic data) |
| Failover and failback procedure | `designed`; not exercised |
| Event Hubs data geo-replication | `planned`; availability in Government unverified |
| Customer recovery objectives, alternate site, call tree, test cadence | `customer`, OPEN |
