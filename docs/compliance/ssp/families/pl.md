# PL: Planning (SSP narratives)

- Scope: NeuroSphere application controls mapped to NIST SP 800-53 Rev 5 family PL. Baseline selection is a customer input, see [scope.md](../scope.md). Machine-readable source: [control-mapping.yaml](../control-mapping.yaml).
- Status vocabulary: `designed`, `implemented_tested`, `inherited`, `customer`, `planned`, `not_applicable`.
- Statement: not FedRAMP authorized; the authorizing official decides. Inherited entries follow [the responsibility matrix](../../responsibility-matrix.md) and do not automatically authorize this application.

These narratives are source material for the customer's SSP. They are generated from `control-mapping.yaml`; edit the YAML, not this file.

## PL-2 System Security and Privacy Plans

- Status: `customer`
- Implementing PRPs: PRP-23
- Owner: Customer ISSO / system owner (owns the SSP)
- Evidence:
  - `docs/compliance/ssp/scope.md`

The SSP is owned by the customer. These narratives are source material for it.

## PL-8 Security and Privacy Architectures

- Status: `designed`
- Implementing PRPs: PRP-01, PRP-12
- Evidence:
  - `docs/ARCHITECTURE.md`
  - `docs/diagrams/01-component-trust-boundaries.svg`

The architecture document and diagrams show trust boundaries, and the threat model is keyed to them.

## PL-10 Baseline Selection

- Status: `customer`
- Implementing PRPs: PRP-23
- Owner: Customer authorizing official and agency (Low/Moderate/High baseline)
- Evidence:
  - `docs/compliance/ssp/scope.md`

Baseline selection is not made by NeuroSphere. It is recorded as an OPEN customer input.
