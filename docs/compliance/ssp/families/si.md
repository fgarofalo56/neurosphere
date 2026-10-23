# SI: System and Information Integrity (SSP narratives)

- Scope: NeuroSphere application controls mapped to NIST SP 800-53 Rev 5 family SI. Baseline selection is a customer input, see [scope.md](../scope.md). Machine-readable source: [control-mapping.yaml](../control-mapping.yaml).
- Status vocabulary: `designed`, `implemented_tested`, `inherited`, `customer`, `planned`, `not_applicable`.
- Statement: not FedRAMP authorized; the authorizing official decides. Inherited entries follow [the responsibility matrix](../../responsibility-matrix.md) and do not automatically authorize this application.

These narratives are source material for the customer's SSP. They are generated from `control-mapping.yaml`; edit the YAML, not this file.

## SI-2 Flaw Remediation

- Status: `designed`
- Implementing PRPs: PRP-12, PRP-13
- Evidence:
  - `.github/dependabot.yml`
  - `.github/workflows/security.yml`

Dependency updates are automated and image scans gate pull requests.

## SI-4 System Monitoring

- Status: `designed`
- Implementing PRPs: PRP-05, PRP-21
- Evidence:
  - `infra/observability/grafana-slo-dashboard.json`
  - `docs/ops/slo.md`

Self-observability and SLO dashboards are defined. Alert routing is customer-owned.

## SI-7 Software, Firmware, and Information Integrity

- Status: `implemented_tested`
- Implementing PRPs: PRP-06, PRP-13
- Evidence:
  - `packages/core/tests/audit/test_chain.py`
  - `docs/evidence/PRP-13/release-v0.1.0-rc.1.md`

The audit chain detects tampering, and release images are signed with cosign with an SBOM
attestation.

## SI-10 Information Input Validation

- Status: `implemented_tested`
- Implementing PRPs: PRP-01, PRP-12
- Evidence:
  - `packages/contracts/schemas/audit/v1/audit-record.schema.json`
  - `tests/security/injection/test_corpus_schema.py`

Inputs are validated against versioned contracts, and an injection corpus is run against the copilot
tools.

## SI-12 Information Management and Retention

- Status: `planned`
- Implementing PRPs: PRP-23
- Owner: PRP-23 item 1 (lifecycle engine); customer records officer (retention periods, gate G06)
- Evidence: none yet

Policy-driven retention, pseudonymization, deletion, export and legal hold are specified under
PRP-23 item 1 with fail-closed defaults. They are not cited as evidence until merged and tested.
