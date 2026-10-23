# MA: Maintenance (SSP narratives)

- Scope: NeuroSphere application controls mapped to NIST SP 800-53 Rev 5 family MA. Baseline selection is a customer input, see [scope.md](../scope.md). Machine-readable source: [control-mapping.yaml](../control-mapping.yaml).
- Status vocabulary: `designed`, `implemented_tested`, `inherited`, `customer`, `planned`, `not_applicable`.
- Statement: not FedRAMP authorized; the authorizing official decides. Inherited entries follow [the responsibility matrix](../../responsibility-matrix.md) and do not automatically authorize this application.

These narratives are source material for the customer's SSP. They are generated from `control-mapping.yaml`; edit the YAML, not this file.

## MA-2 Controlled Maintenance

- Status: `inherited`
- Implementing PRPs: PRP-20
- Evidence:
  - `docs/compliance/responsibility-matrix.md`

Platform maintenance is performed by the cloud provider; see docs/compliance/responsibility-
matrix.md. Inherited controls do not automatically authorize this application. Application
maintenance follows CM-3.
