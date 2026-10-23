# CA: Assessment, Authorization, and Monitoring (SSP narratives)

- Scope: NeuroSphere application controls mapped to NIST SP 800-53 Rev 5 family CA. Baseline selection is a customer input, see [scope.md](../scope.md). Machine-readable source: [control-mapping.yaml](../control-mapping.yaml).
- Status vocabulary: `designed`, `implemented_tested`, `inherited`, `customer`, `planned`, `not_applicable`.
- Statement: not FedRAMP authorized; the authorizing official decides. Inherited entries follow [the responsibility matrix](../../responsibility-matrix.md) and do not automatically authorize this application.

These narratives are source material for the customer's SSP. They are generated from `control-mapping.yaml`; edit the YAML, not this file.

## CA-2 Control Assessments

- Status: `customer`
- Implementing PRPs: PRP-12
- Owner: Customer assessor / security team
- Evidence:
  - `docs/security/threat-model.md`

Assessment is performed by the customer or its assessor. NeuroSphere supplies the threat model, scan
output and test evidence as inputs.

## CA-3 Information Exchange

- Status: `designed`
- Implementing PRPs: PRP-12
- Evidence:
  - `docs/security/threat-model.md`
  - `docs/ARCHITECTURE.md`

Trust boundaries and data flows for each external exchange (model endpoint, connectors, MCP,
analytics adapters) are modelled with STRIDE per boundary.

## CA-5 Plan of Action and Milestones

- Status: `designed`
- Implementing PRPs: PRP-23
- Evidence:
  - `docs/compliance/poam.md`

A POA&M template is provided. It carries no pre-filled completion dates; entries are made by the
customer.

## CA-6 Authorization

- Status: `customer`
- Implementing PRPs: PRP-20, PRP-23
- Owner: Customer authorizing official
- Evidence:
  - `docs/compliance/responsibility-matrix.md`

The authorization decision belongs to the customer authorizing official. NeuroSphere makes no claim
of authorization and promises no certification date.

## CA-7 Continuous Monitoring

- Status: `planned`
- Implementing PRPs: PRP-23
- Owner: PRP-23 item 4 (continuous monitoring plan); customer ISSO (execution)
- Evidence: none yet

The continuous monitoring plan is produced by PRP-23 item 4 and is not yet in the repository. Scan
workflows already run in CI (see RA-5).

## CA-8 Penetration Testing

- Status: `customer`
- Implementing PRPs: PRP-12
- Owner: Customer security team or independent assessor
- Evidence:
  - `tests/security/injection/test_harness_negative_control.py`

Penetration testing of a deployed instance is customer-scheduled. Adversarial corpora (injection,
confused deputy, SSRF) run in CI.
