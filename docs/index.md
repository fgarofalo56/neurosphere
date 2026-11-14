# NeuroSphere

NeuroSphere is a customer-hosted AI governance platform for Azure Commercial and Azure
Government: telemetry and cost, a versioned catalog with curated relationships,
recommendations and evaluation, human-in-the-loop approvals, a live map with session
replay, a governed copilot, MCP tools, and an evidence accelerator for authorization
work.

!!! note "Scope of these claims"
    Availability, feature maturity and authorization are separate gates. Nothing on this
    site claims FedRAMP authorization, an ATO, or Commercial and Government parity.
    Unsupported cloud, region or feature combinations are disabled with a reason, not
    silently routed to another cloud.

## Start here

- Install: [install runbook](runbooks/install.md) and [local setup](dev/local-setup.md).
- Operate: [runbooks](runbooks/operations.md), [DR](ops/dr-runbook.md) and [SLOs](ops/slo.md).
- Use: [admin walkthrough](walkthroughs/admin.md), plus analyst, auditor, steward and viewer.
- Integrate: [API and SDK reference](reference/index.md) and [connector coverage](connectors/coverage.md).
- Secure: [security runbooks](security/runbooks/README.md) and [ATO accelerator plans](compliance/plans/README.md).
- Release: [release process](release/release-process.md) and [verification](release/verify.md).
- Design: [architecture](ARCHITECTURE.md) and [research and gates](RESEARCH-AND-GATES.md).

## Architecture decision records

Each record states the context, the decision and its date.

| Record | Topic |
|---|---|
| [ADR-0001](adr/0001-record-architecture-decisions.md) | Record architecture decisions |
| [ADR-0002](adr/0002-stack-pins.md) | Stack selection and version pins |
| [ADR-0003](adr/0003-harness-orchestrated-prp-kit.md) | Harness and orchestrated PRP kit |
| [ADR-0004](adr/0004-contract-versioning.md) | Contract versioning |
| [ADR-0005](adr/0005-catalog-store.md) | Catalog store |
| [ADR-0006](adr/0006-eventhubs-quarantine.md) | Event Hubs quarantine |
| [ADR-0007](adr/0007-analytics-adapter-contract.md) | Analytics adapter contract |
| [ADR-0008](adr/0008-docs-site-tool.md) | Documentation site tool |
