# IR: Incident Response (SSP narratives)

- Scope: NeuroSphere application controls mapped to NIST SP 800-53 Rev 5 family IR. Baseline selection is a customer input, see [scope.md](../scope.md). Machine-readable source: [control-mapping.yaml](../control-mapping.yaml).
- Status vocabulary: `designed`, `implemented_tested`, `inherited`, `customer`, `planned`, `not_applicable`.
- Statement: not FedRAMP authorized; the authorizing official decides. Inherited entries follow [the responsibility matrix](../../responsibility-matrix.md) and do not automatically authorize this application.

These narratives are source material for the customer's SSP. They are generated from `control-mapping.yaml`; edit the YAML, not this file.

## IR-4 Incident Handling

- Status: `designed`
- Implementing PRPs: PRP-12
- Evidence:
  - `docs/security/runbooks/credential-leak-response.md`

A credential-leak response runbook and an incident response plan cover the repository, build
pipeline and a customer-hosted instance.

## IR-6 Incident Reporting

- Status: `customer`
- Implementing PRPs: PRP-12
- Owner: Customer incident lead and reporting chain
- Evidence:
  - `docs/security/runbooks/incident-response-plan.md`

External reporting obligations belong to the customer. The engineering plan names the internal
incident lead and severity levels only.

## IR-8 Incident Response Plan

- Status: `designed`
- Implementing PRPs: PRP-12, PRP-23
- Evidence:
  - `docs/security/runbooks/incident-response-plan.md`

The engineering incident response plan exists; the customer-facing ATO plan set under
docs/compliance/plans/ is planned under PRP-23 item 4.
