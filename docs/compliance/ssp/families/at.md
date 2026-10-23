# AT: Awareness and Training (SSP narratives)

- Scope: NeuroSphere application controls mapped to NIST SP 800-53 Rev 5 family AT. Baseline selection is a customer input, see [scope.md](../scope.md). Machine-readable source: [control-mapping.yaml](../control-mapping.yaml).
- Status vocabulary: `designed`, `implemented_tested`, `inherited`, `customer`, `planned`, `not_applicable`.
- Statement: not FedRAMP authorized; the authorizing official decides. Inherited entries follow [the responsibility matrix](../../responsibility-matrix.md) and do not automatically authorize this application.

These narratives are source material for the customer's SSP. They are generated from `control-mapping.yaml`; edit the YAML, not this file.

## AT-2 Literacy Training and Awareness

- Status: `customer`
- Implementing PRPs: PRP-12
- Owner: Customer security awareness program
- Evidence:
  - `docs/security/runbooks/README.md`

Training of operators and administrators is a customer program. Engineering runbooks exist for
secret handling and incident response.
