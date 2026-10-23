# RA: Risk Assessment (SSP narratives)

- Scope: NeuroSphere application controls mapped to NIST SP 800-53 Rev 5 family RA. Baseline selection is a customer input, see [scope.md](../scope.md). Machine-readable source: [control-mapping.yaml](../control-mapping.yaml).
- Status vocabulary: `designed`, `implemented_tested`, `inherited`, `customer`, `planned`, `not_applicable`.
- Statement: not FedRAMP authorized; the authorizing official decides. Inherited entries follow [the responsibility matrix](../../responsibility-matrix.md) and do not automatically authorize this application.

These narratives are source material for the customer's SSP. They are generated from `control-mapping.yaml`; edit the YAML, not this file.

## RA-2 Security Categorization

- Status: `customer`
- Implementing PRPs: PRP-23
- Owner: Customer data owner / authorizing official (data classification, gate G06)
- Evidence:
  - `docs/compliance/ssp/scope.md`

Classification is a customer input. A missing classification is treated as restricted.

## RA-3 Risk Assessment

- Status: `designed`
- Implementing PRPs: PRP-12
- Evidence:
  - `docs/security/threat-model.md`

A STRIDE threat model covers each trust boundary and records open items.

## RA-5 Vulnerability Monitoring and Scanning

- Status: `implemented_tested`
- Implementing PRPs: PRP-12, PRP-13
- Evidence:
  - `.github/workflows/security.yml`
  - `.github/workflows/codeql.yml`
  - `docs/evidence/prp-12-supply-chain/local-scan-evidence.md`

Trivy, Grype, CodeQL and secret scanning run in CI, with images scanned on every pull request. Local
proof against a known-vulnerable image is recorded.
