# AU: Audit and Accountability (SSP narratives)

- Scope: NeuroSphere application controls mapped to NIST SP 800-53 Rev 5 family AU. Baseline selection is a customer input, see [scope.md](../scope.md). Machine-readable source: [control-mapping.yaml](../control-mapping.yaml).
- Status vocabulary: `designed`, `implemented_tested`, `inherited`, `customer`, `planned`, `not_applicable`.
- Statement: not FedRAMP authorized; the authorizing official decides. Inherited entries follow [the responsibility matrix](../../responsibility-matrix.md) and do not automatically authorize this application.

These narratives are source material for the customer's SSP. They are generated from `control-mapping.yaml`; edit the YAML, not this file.

## AU-2 Event Logging

- Status: `implemented_tested`
- Implementing PRPs: PRP-06
- Evidence:
  - `packages/core/neurosphere_core/audit/builders.py`
  - `services/api/tests/audit/test_audit_routes.py`
  - `services/workers/tests/action_executor/test_audit_phases.py`

Authorization decisions, actions and approvals emit structured audit records through a single audit
writer interface.

## AU-3 Content of Audit Records

- Status: `implemented_tested`
- Implementing PRPs: PRP-01, PRP-06
- Evidence:
  - `packages/contracts/schemas/audit/v1/audit-record.schema.json`
  - `packages/core/tests/audit/test_redaction_scan.py`

Audit records follow a versioned schema with principal (pseudonymous), action, target, outcome and
chain hash. Invalid shapes are rejected by contract examples.

## AU-6 Audit Record Review, Analysis, and Reporting

- Status: `customer`
- Implementing PRPs: PRP-06
- Owner: Customer security operations (SIEM, review cadence)
- Evidence:
  - `packages/core/neurosphere_core/audit/siem.py`

Review and alerting are customer SIEM processes. NeuroSphere provides an export hook.

## AU-9 Protection of Audit Information

- Status: `implemented_tested`
- Implementing PRPs: PRP-06
- Evidence:
  - `packages/core/tests/audit/test_chain.py`
  - `packages/core/tests/audit/test_immutability.py`

Audit records are append-only and hash-chained. Tests assert immutability and chain verification.
The lifecycle engine (PRP-23 item 1) is specified to refuse any action on audit data.

## AU-10 Non-repudiation

- Status: `designed`
- Implementing PRPs: PRP-06, PRP-17
- Evidence:
  - `packages/core/neurosphere_core/actions/hashing.py`
  - `tests/security/mcp/test_intent_hash_parity.py`

Action intents are hashed and the same hash is carried across button, chat, REST and MCP paths, so
an approved action can be tied to the audited execution.

## AU-11 Audit Record Retention

- Status: `planned`
- Implementing PRPs: PRP-23
- Owner: PRP-23 lifecycle engine (mechanism); customer records policy (retention periods, gate G06)
- Evidence: none yet

Retention periods are a customer input and no built-in values are shipped. The mechanism that keeps
audit records out of deletion scope is planned under PRP-23 item 1.

## AU-12 Audit Record Generation

- Status: `implemented_tested`
- Implementing PRPs: PRP-06, PRP-17
- Evidence:
  - `services/api/tests/authz/test_audit_mount.py`
  - `services/workers/tests/action_executor/test_audit_phases.py`

The API and the action executor write audit records for each phase of an action.
