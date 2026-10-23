# CM: Configuration Management (SSP narratives)

- Scope: NeuroSphere application controls mapped to NIST SP 800-53 Rev 5 family CM. Baseline selection is a customer input, see [scope.md](../scope.md). Machine-readable source: [control-mapping.yaml](../control-mapping.yaml).
- Status vocabulary: `designed`, `implemented_tested`, `inherited`, `customer`, `planned`, `not_applicable`.
- Statement: not FedRAMP authorized; the authorizing official decides. Inherited entries follow [the responsibility matrix](../../responsibility-matrix.md) and do not automatically authorize this application.

These narratives are source material for the customer's SSP. They are generated from `control-mapping.yaml`; edit the YAML, not this file.

## CM-2 Baseline Configuration

- Status: `designed`
- Implementing PRPs: PRP-08, PRP-13
- Evidence:
  - `infra/helm/values.yaml`
  - `infra/helm/values-government.yaml`

Helm values and Bicep parameters define the deployed baseline, with a separate Government values
file.

## CM-3 Configuration Change Control

- Status: `implemented_tested`
- Implementing PRPs: PRP-13, PRP-00
- Evidence:
  - `docs/release/release-process.md`
  - `tests/release/test_release_workflow.py`

Changes land through reviewed pull requests with CI gates; releases are tag-driven and the release
workflow is tested.

## CM-6 Configuration Settings

- Status: `designed`
- Implementing PRPs: PRP-20
- Evidence:
  - `infra/helm/values-government.yaml`
  - `packages/core/neurosphere_core/capabilities/validate.py`

Government profiles disable options that the capability matrix cannot verify, with a reason, instead
of substituting Commercial services.

## CM-7 Least Functionality

- Status: `implemented_tested`
- Implementing PRPs: PRP-19, PRP-12
- Evidence:
  - `packages/core/neurosphere_core/charts/validator.py`
  - `tests/security/injection/test_corpus_schema.py`

The copilot has bounded structured tools only; arbitrary generated SQL, Cypher or JavaScript is not
executed, and charts are a sandboxed declarative subset.

## CM-8 System Component Inventory

- Status: `designed`
- Implementing PRPs: PRP-12, PRP-13
- Evidence:
  - `.github/workflows/security.yml`
  - `docs/evidence/PRP-13/release-v0.1.0-rc.1.md`

A CycloneDX SBOM is produced and attached to released images. The indexed evidence inventory is
planned under PRP-23 item 3.
