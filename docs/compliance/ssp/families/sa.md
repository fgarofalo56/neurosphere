# SA: System and Services Acquisition (SSP narratives)

- Scope: NeuroSphere application controls mapped to NIST SP 800-53 Rev 5 family SA. Baseline selection is a customer input, see [scope.md](../scope.md). Machine-readable source: [control-mapping.yaml](../control-mapping.yaml).
- Status vocabulary: `designed`, `implemented_tested`, `inherited`, `customer`, `planned`, `not_applicable`.
- Statement: not FedRAMP authorized; the authorizing official decides. Inherited entries follow [the responsibility matrix](../../responsibility-matrix.md) and do not automatically authorize this application.

These narratives are source material for the customer's SSP. They are generated from `control-mapping.yaml`; edit the YAML, not this file.

## SA-3 System Development Life Cycle

- Status: `designed`
- Implementing PRPs: PRP-00
- Evidence:
  - `docs/adr/0003-harness-orchestrated-prp-kit.md`
  - `docs/DECISIONS-LOG.md`

Work follows PRPs with declared file ownership, gates and architecture decision records.

## SA-11 Developer Testing and Evaluation

- Status: `implemented_tested`
- Implementing PRPs: PRP-00, PRP-12
- Evidence:
  - `.github/workflows/ci.yml`
  - `scripts/validate_planning.py`

CI runs unit, contract, security and release tests; no failure is suppressed with `|| true`, and the
planning validator checks this.

## SA-4 Acquisition Process

- Status: `customer`
- Implementing PRPs: PRP-20
- Owner: Customer acquisition and contracting office
- Evidence:
  - `docs/evidence/G02/register.yaml`

Procurement terms for the platform services in use are customer-owned.
