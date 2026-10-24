# CP: Contingency Planning (SSP narratives)

- Scope: NeuroSphere application controls mapped to NIST SP 800-53 Rev 5 family CP. Baseline selection is a customer input, see [scope.md](../scope.md). Machine-readable source: [control-mapping.yaml](../control-mapping.yaml).
- Status vocabulary: `designed`, `implemented_tested`, `inherited`, `customer`, `planned`, `not_applicable`.
- Statement: not FedRAMP authorized; the authorizing official decides. Inherited entries follow [the responsibility matrix](../../responsibility-matrix.md) and do not automatically authorize this application.

These narratives are source material for the customer's SSP. They are generated from `control-mapping.yaml`; edit the YAML, not this file.

## CP-2 Contingency Plan

- Status: `planned`
- Implementing PRPs: PRP-23
- Owner: PRP-23 item 4 (plan document); customer system owner (approval)
- Evidence: none yet

The contingency plan is produced by PRP-23 item 4 and is not yet in the repository. It will cite
measured DR results and will not restate targets as guarantees.

## CP-4 Contingency Plan Testing

- Status: `designed`
- Implementing PRPs: PRP-21
- Evidence:
  - `docs/evidence/G07/dr/README.md`
  - `docs/evidence/G07/dr/restore-drill-compose-2026-10-22.json`

A restore drill ran against the local emulator only. Live Azure DR measurements remain OPEN (gate
G07).

## CP-9 System Backup

- Status: `designed`
- Implementing PRPs: PRP-21
- Evidence:
  - `docs/ops/dr-runbook.md`
  - `infra/dr/README.md`

The DR runbook documents backup and restore. Event Hubs metadata geo-DR copies neither payloads nor
RBAC.

## CP-10 System Recovery and Reconstitution

- Status: `designed`
- Implementing PRPs: PRP-21
- Evidence:
  - `docs/ops/dr-runbook.md`
  - `docs/ops/slo.md`

Recovery steps are in the DR runbook; recovery targets are measured per drill and are not
guarantees.
