# Plan of action and milestones (template)

- Scope: a blank POA&M template for weaknesses found against NeuroSphere controls. The customer's security team owns the entries and the dates. Control identifiers refer to [control-mapping.yaml](ssp/control-mapping.yaml).
- Status vocabulary: POA&M item status is `open`, `in_progress`, `closed` or `risk_accepted`. Control status uses `designed`, `implemented_tested`, `inherited`, `customer`, `planned`, `not_applicable`.
- Statement: not FedRAMP authorized; the authorizing official decides. This template carries no pre-filled completion dates, and risk acceptance belongs to the authorizing official.

## How to use

1. Add one row per weakness. Reference the control identifier from the mapping.
2. Name a milestone and a single accountable owner.
3. Enter a scheduled completion date only when the owner commits to it. Leave it blank otherwise.
4. Do not mark an item `closed` without a link to evidence.

## Register

| Weakness | Control | Milestone | Owner | Scheduled completion | Status |
|---|---|---|---|---|---|
| | | | | | |

## Example row (format only, not a finding)

| Weakness | Control | Milestone | Owner | Scheduled completion | Status |
|---|---|---|---|---|---|
| Description of the weakness and where it was found | AC-3 | The verifiable step that resolves it | Named role | (entered by the owner) | open |

## Items the repository already lists as OPEN

These are pointers, not committed milestones. Dates and owners are for the customer to assign.

| Weakness | Control | Source |
|---|---|---|
| In-cluster proof of no Commercial egress is not yet recorded | AC-4, SC-7 | `docs/RESEARCH-AND-GATES.md` gate G02 |
| Retention periods, legal hold process and classification not provided | AU-11, SI-12 | `docs/compliance/ssp/scope.md` and gate G06 |
| Live Azure DR measurements not recorded (emulator drill only) | CP-4 | `docs/evidence/G07/dr/README.md` |
| Contingency, continuous monitoring and evidence inventory documents not yet written | CP-2, CA-7, PM-5 | `docs/compliance/ssp/control-mapping.yaml` |
