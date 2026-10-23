# PE: Physical and Environmental Protection (SSP narratives)

- Scope: NeuroSphere application controls mapped to NIST SP 800-53 Rev 5 family PE. Baseline selection is a customer input, see [scope.md](../scope.md). Machine-readable source: [control-mapping.yaml](../control-mapping.yaml).
- Status vocabulary: `designed`, `implemented_tested`, `inherited`, `customer`, `planned`, `not_applicable`.
- Statement: not FedRAMP authorized; the authorizing official decides. Inherited entries follow [the responsibility matrix](../../responsibility-matrix.md) and do not automatically authorize this application.

These narratives are source material for the customer's SSP. They are generated from `control-mapping.yaml`; edit the YAML, not this file.

## PE-2 Physical Access Authorizations

- Status: `inherited`
- Implementing PRPs: PRP-20
- Evidence:
  - `docs/compliance/responsibility-matrix.md`

Datacenter physical controls are the cloud provider's, per docs/compliance/responsibility-matrix.md.
Inherited controls do not automatically authorize this application.
