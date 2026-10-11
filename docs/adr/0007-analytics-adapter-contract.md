# ADR-0007: Analytics adapter contract

- Status: accepted for design; adapter implementations pending
- Date: 2026-10-11
- Deciders: Frank Garofalo
- Relates to: PRP.md section 2, `docs/adr/0004-contract-versioning.md`

## Context

Customers run Fabric, Synapse or Azure Databricks. These are deployment choices behind adapters, not global requirements or bans. Which adapter may be enabled in a given cloud and region must come from the capability matrix, never from assumption.

## Decision

1. **Two capability contracts.**
   - `TelemetryAnalytics`: scoped aggregate and time-series reads over normalized telemetry and cost, used by dashboards, the live map and reports.
   - `RecommendationCompute`: analytical graph and similarity jobs run away from the interactive path; it produces candidate recommendations that still pass the evaluation and HITL flow.
2. **Structured, bounded requests only.** Both contracts accept typed, declarative requests (metric, dimensions, filter, time range, limit) and return typed results. **No arbitrary LLM-generated SQL, Cypher or JavaScript** is executed; adapters translate the typed request into their engine's native query. Every request carries a query budget (time range, row limit, timeout, cost ceiling) that the adapter enforces; exceeding it returns a truncation marker, not a silent partial result.
3. **Authorization at every path.** The caller's scope is passed into the adapter and applied to every query and export. Privileged users get scoped permissions, never a bypass.
4. **Matrix-driven enablement.** `validate_profile` resolves a requested adapter in a cloud and region to `supported` only when the matrix row says `available`. Rows that are `unverified` or `unavailable` mean the adapter is **disabled with a reason**. `ga_status: unverified` on an available row surfaces as a warning. An unlisted combination is `unverified`, so disabled.
5. **No cross-cloud bridging.** If an adapter is disabled for Government, Government data is not routed to a Commercial adapter to fill the gap.
6. **Availability, GA and authorization are separate gates.** GA is not authorization. This ADR makes no claim of FedRAMP authorization, ATO or Commercial/Government parity.

## Adapter enablement, derived strictly from matrix rows (rows observed 2026-10-08)

Source: `packages/core/neurosphere_core/capabilities/data/fabric.yaml`, `synapse.yaml` and `databricks.yaml`.

| Adapter | Cloud / region | Row id | Row status | Adapter |
|---|---|---|---|---|
| Fabric | Government, US Gov Virginia (GCC High) | `fabric.base.government.usgovvirginia.any` | available / ga | enabled |
| Fabric | Government, US Gov Texas (GCC High) | `fabric.base.government.usgovtexas.any` | available / ga | enabled |
| Fabric | Government GCC | `fabric.base_gcc.government.any.any` | unverified | **disabled** |
| Fabric | Government DoD | `fabric.base_dod.government.any.any` | unverified | **disabled** |
| Fabric | Commercial | `fabric.base.commercial.global.any` | unverified | **disabled** until the row is verified |
| Synapse | Government | `synapse.base.government.global.any` | available / GA unverified | enabled with `ga_unverified` warning |
| Synapse | Commercial | `synapse.base.commercial.global.any` | unverified | **disabled** until verified |
| Azure Databricks | US Gov Virginia | `databricks.base.government.usgovvirginia.any` | available / GA unverified | enabled with `ga_unverified` warning |
| Azure Databricks | US Gov Arizona | `databricks.base.government.usgovarizona.any` | available / GA unverified | enabled with `ga_unverified` warning |
| Azure Databricks | Commercial | `databricks.base.commercial.global.any` | unverified | **disabled** until verified |

Fabric GCC High sub-features are disabled (never routed to Commercial) in both regions: customer-managed keys (`fabric.customer_managed_keys.government.usgovvirginia.any`, `fabric.customer_managed_keys.government.usgovtexas.any`), workspace identity (`fabric.workspace_identity.government.usgovvirginia.any`, `fabric.workspace_identity.government.usgovtexas.any`) and Fabric IQ items (`fabric.fabric_iq_items.government.usgovvirginia.any`, `fabric.fabric_iq_items.government.usgovtexas.any`).

Commercial rows are `unverified` only because the cited sources describe Government; that is a gap to close with a Commercial-sourced row, not evidence of unavailability. Rows older than 90 days add a `stale` warning.

## Evidence relied on

No `docs/evidence/G03/` file is relied on by this ADR. Gates G01 and G02 stay OPEN for Government; all Government rows are documentation-derived and no Government subscription exists.

## Consequences

- Adapter packages implement the two contracts plus a capability declaration the matrix check can compare against.
- Profiles that request a disabled adapter fail validation with the row-based reason rather than degrading silently.
- Contract changes follow ADR-0004 versioning.
- Customers choose among validated available profiles only.

## References

- `PRP.md` section 2, `docs/ARCHITECTURE.md`, `docs/adr/0004-contract-versioning.md`
- `packages/core/neurosphere_core/capabilities/validate.py`
