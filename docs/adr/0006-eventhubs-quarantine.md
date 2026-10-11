# ADR-0006: Event Hubs ingest and explicit quarantine

- Status: accepted for design; live behaviour unverified (no live Event Hubs run exists)
- Date: 2026-10-11
- Deciders: Frank Garofalo
- Relates to: PRP.md section 2, `docs/ARCHITECTURE.md`

## Context

Telemetry enters through Event Hubs in production and through the Event Hubs emulator in local dev and tests. Malformed, unauthorized or unprocessable events must never be dropped silently or block a partition forever. Event Hubs has **no built-in dead-letter queue** (unlike Service Bus), so a poison event has nowhere to go unless we build one.

## Decision

1. **Explicit quarantine.** A normalization worker that cannot accept an event writes the original payload (redacted per policy), the failure reason, and the source hub, partition and offset to a **quarantine container** in durable storage. The local emulator mirrors this with the `quarantine` entity (1 partition, consumer group `replay`) defined in `infra/compose/eventhubs.config.json`, next to the `telemetry` hub (4 partitions, consumer groups `normalizer` and `aggregates`).
2. **Replay CLI.** Operators replay quarantined events through a CLI that re-submits them to the normal ingest path after the cause is fixed. Replay re-runs authorization and schema validation; it is not a bypass. Each replay is audited.
3. **Checkpoints advance only after durable accept or durable quarantine.** A consumer never checkpoints an event that is neither stored (idempotent projection via the outbox) nor quarantined. A crash between receipt and either outcome re-delivers the event; idempotency keys make that safe.
4. **Producer identity is enforced at the ingest edge.** The emulator has no Entra support and no persistence, so tests cannot prove Entra-based sender authorization or durability across restarts. Those controls are implemented in the ingest edge service and covered by its own tests; the live check of Entra on a real namespace is OPEN.
5. **Disaster recovery is two separate things.**
   - Geo-DR (metadata) copies namespace metadata only. It copies **neither event payloads nor RBAC assignments**; role assignments must be re-created or deployed by IaC in the secondary. It does not protect in-flight events.
   - Data geo-replication is GA on **Premium and Dedicated only**; Basic and Standard are unavailable for it. Government support is **unverified**, so no Government DR design assumes it.
6. The quarantine container is the system of record for rejected events and is covered by the backup and retention policy of the storage tier chosen at deployment.

## Evidence relied on

No `docs/evidence/G03/` file is relied on by this ADR (G03 concerns the catalog store). No live Event Hubs evidence exists.

Matrix rows (`packages/core/neurosphere_core/capabilities/data/eventhubs.yaml`):

| Row id | Availability / GA |
|---|---|
| `event_hubs.data_geo_replication.commercial.global.premium` | available / ga |
| `event_hubs.data_geo_replication.commercial.global.dedicated` | available / ga |
| `event_hubs.data_geo_replication.commercial.global.standard` | unavailable / not_applicable |
| `event_hubs.data_geo_replication.commercial.global.basic` | unavailable / not_applicable |
| `event_hubs.data_geo_replication.government.global.premium` | unverified / unverified (disabled) |
| `event_hubs.data_geo_replication.government.global.dedicated` | unverified / unverified (disabled) |
| `event_hubs.metadata_geo_dr.commercial.global.any` | available / unverified (metadata only) |
| `event_hubs.metadata_geo_dr.government.global.any` | unverified / unverified (disabled) |

## Consequences

- Government profiles get neither data geo-replication nor metadata Geo-DR from this design until the rows are verified; Government DR is an open gate, not an assumed capability.
- The quarantine container and replay CLI are real work items for the telemetry PRP; the emulator `quarantine` hub only exercises the plumbing.
- Local tests prove checkpoint-ordering logic, not Entra enforcement or durability across emulator restarts.
- No statement here claims FedRAMP authorization, ATO or parity.

## References

- `infra/compose/eventhubs.config.json`
- `PRP.md` section 2, `docs/ARCHITECTURE.md`
- https://learn.microsoft.com/azure/event-hubs/overview-emulator
- G03 evidence: not relied on (Cosmos-specific); see docs/evidence/G03/emulator-2026-10-11.md for the Cosmos benchmark relied on by ADR-0005.
