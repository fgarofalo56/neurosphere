# Incident response plan (customer-hosted deployment)

> **Scope:** How incidents affecting a customer-hosted NeuroSphere deployment are classified, handled and recorded, and where the customer must supply its own contacts and thresholds.
> **Status vocabulary:** `designed`, `implemented_tested`, `inherited`, `customer`, `planned`, `not_applicable`.
> **Statement:** NeuroSphere is not FedRAMP authorized; the authorizing official decides. This document supports the customer security team and the authorizing official. It is not an assessment, makes no authorization, ATO, parity or certification claim, and carries no authorization date or compliance score.
> **Provenance:** PRP-23 item 4. Customer-owned inputs are recorded as `customer` and OPEN; they are never guessed here.

This plan links to the existing runbooks instead of copying them. Operational runbooks (PRP-12): [incident response plan and severity levels](../../security/runbooks/incident-response-plan.md), [credential leak response](../../security/runbooks/credential-leak-response.md), [secret rotation](../../security/runbooks/secret-rotation.md), [Key Vault references](../../security/runbooks/key-vault-references.md), [runbook index](../../security/runbooks/README.md). Threat model and abuse cases: [threat-model.md](../../security/threat-model.md). Recovery: [contingency plan](contingency-plan.md) and the [DR runbook](../../ops/dr-runbook.md). Boundaries: [boundary and data-flow diagrams](boundary-and-data-flow.md). Responsibility split: [responsibility matrix](../responsibility-matrix.md).

## 1. Relationship to the runbooks

The PRP-12 runbook defines severity levels (SEV1 to SEV3), the flow (contain, eradicate, recover, lessons learned), evidence preservation and communication, for the repository and pipeline and, once deployed, a customer-hosted instance. This plan adds the deployment-level view: what is detected where, who in the customer organization owns each phase, and what stays OPEN. Where the two differ, the runbook is the operational authority and this document is updated to match.

## 2. Phases and ownership

| Phase | NeuroSphere provides | Owner | Status |
|---|---|---|---|
| Preparation | Runbooks, hooks, CI secret scan, audit store, scoped permissions, kill switches (disable a connector or feature) | Customer security team | `designed`; customer adoption `customer` |
| Detection and analysis | Audit events (before, after, denied action), CI scans, application telemetry; exportable to a SIEM | Customer SOC | event content `implemented_tested`; SIEM wiring `customer` |
| Containment | Revoke or rotate credentials, disable identity, disable connector or feature, fail closed | Incident lead (customer) | procedure `designed` |
| Eradication and recovery | Rotation runbook, restore procedure, verification by behaviour | Customer with operator | `designed`; failover not exercised, see contingency plan |
| Post-incident | Timeline template in the runbook; follow-up issues with owners | Incident lead | `designed` |

## 3. Incident categories specific to this platform

Handled with the same severity scale; each names where to look first.

- **Cross-cloud or cross-tenant exposure.** Any observed data path between the Government and Commercial deployments, or across `IdentityScope`, is SEV1. Fail closed, disable the path, preserve audit exports. See the [boundary diagram](boundary-and-data-flow.md).
- **Unauthorized or unverified action.** The action executor records intent, approval and the verified outcome. A mismatch between recorded and actual outcome is an incident; use the audit trail and rollback evidence.
- **Credential or secret exposure.** Rotate first, then clean history: [credential-leak-response.md](../../security/runbooks/credential-leak-response.md).
- **Prompt injection, SSRF, confused deputy.** Abuse cases and data-flow diagrams are in the [threat model](../../security/threat-model.md) and `docs/security/dfd/`.
- **Retention or deletion error.** The lifecycle engine blocks deletion under legal hold and never targets the audit store; a failed read-back verification marks the job `failed` and raises an audit record. A suspected wrongful deletion is an incident and triggers the contingency plan restore path.
- **Data-loss or availability event.** Hand over to the [contingency plan](contingency-plan.md).

## 4. Evidence and records

Audit records are append-only: export copies and record hashes, never edit or delete. Preserve CI logs, commit ids, alert ids and provider log extracts in access-controlled storage. Do not put credentials or personal data in the incident record. Audit records carry pseudonymous principals; the pseudonym mapping store is separate and its use during an investigation needs the customer's authorization.

## 5. Customer inputs (OPEN, not guessed)

| Input | Status |
|---|---|
| Incident response contacts, on-call roster, escalation path | `customer`, OPEN |
| Reporting obligations and deadlines (to the agency, US-CERT or other bodies) | `customer`, OPEN; depend on agency baseline and classification |
| Severity thresholds mapped to the customer's own categories | `customer`, OPEN |
| SIEM destination and retention for exported audit | `customer`, OPEN |
| Legal hold and records process when evidence is under hold | `customer`, OPEN (G06) |
| Exercise (tabletop) schedule and owner | `customer`, OPEN |

No live incident exercise has been run against a deployed instance; none is claimed.
