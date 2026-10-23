# SR: Supply Chain Risk Management (SSP narratives)

- Scope: NeuroSphere application controls mapped to NIST SP 800-53 Rev 5 family SR. Baseline selection is a customer input, see [scope.md](../scope.md). Machine-readable source: [control-mapping.yaml](../control-mapping.yaml).
- Status vocabulary: `designed`, `implemented_tested`, `inherited`, `customer`, `planned`, `not_applicable`.
- Statement: not FedRAMP authorized; the authorizing official decides. Inherited entries follow [the responsibility matrix](../../responsibility-matrix.md) and do not automatically authorize this application.

These narratives are source material for the customer's SSP. They are generated from `control-mapping.yaml`; edit the YAML, not this file.

## SR-3 Supply Chain Controls and Processes

- Status: `implemented_tested`
- Implementing PRPs: PRP-12, PRP-13
- Evidence:
  - `docs/adr/0002-stack-pins.md`
  - `.github/workflows/security.yml`
  - `docs/licenses.md`

Scanner versions are pinned by checksum, base images by digest, and licences are gated.

## SR-4 Provenance

- Status: `implemented_tested`
- Implementing PRPs: PRP-13
- Evidence:
  - `docs/evidence/PRP-13/release-v0.1.0-rc.1.md`
  - `tests/release/test_release_workflow.py`

Released images carry a cosign signature and a syft CycloneDX SBOM attestation, verified in the
release workflow.

## SR-11 Component Authenticity

- Status: `designed`
- Implementing PRPs: PRP-13
- Evidence:
  - `docs/release/verify.md`

Consumers verify image signatures using the documented procedure.
