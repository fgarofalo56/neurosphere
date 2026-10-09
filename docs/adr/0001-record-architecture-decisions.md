# ADR-0001: Record architecture decisions

- Status: accepted
- Date: 2026-10-08
- Deciders: Frank Garofalo

## Context

NeuroSphere's planning corrected an earlier generic demo direction. Decisions
that are hard to reverse (storage model, cloud boundaries, harness, stack pins)
need a durable record with their reasoning, so a future session or reviewer can
tell a deliberate choice from drift.

## Decision

Record such decisions as Markdown Architecture Decision Records in `docs/adr/`,
numbered sequentially, using this MADR-style layout: Status, Date, Deciders,
Context, Decision, Consequences, and References with URLs and observed dates.

An ADR is required when a choice changes a contract, a storage engine, a cloud
boundary, a security control, a dependency with a licence or support-window
concern, or the development harness. Superseded ADRs stay in place with
`Status: superseded by ADR-NNNN`.

Product-level trade-offs already captured in `docs/ARCHITECTURE.md` are not
duplicated here; an ADR cites them.

## Consequences

- Every PRP that makes a qualifying choice adds or updates an ADR as a work item.
- `docs/DECISIONS-LOG.md` holds operator decisions that are not architectural
  (scope, sequencing, budget); ADRs hold the technical ones.
