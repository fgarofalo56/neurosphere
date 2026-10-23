# SC: System and Communications Protection (SSP narratives)

- Scope: NeuroSphere application controls mapped to NIST SP 800-53 Rev 5 family SC. Baseline selection is a customer input, see [scope.md](../scope.md). Machine-readable source: [control-mapping.yaml](../control-mapping.yaml).
- Status vocabulary: `designed`, `implemented_tested`, `inherited`, `customer`, `planned`, `not_applicable`.
- Statement: not FedRAMP authorized; the authorizing official decides. Inherited entries follow [the responsibility matrix](../../responsibility-matrix.md) and do not automatically authorize this application.

These narratives are source material for the customer's SSP. They are generated from `control-mapping.yaml`; edit the YAML, not this file.

## SC-5 Denial-of-service Protection

- Status: `planned`
- Implementing PRPs: PRP-21
- Owner: Customer platform team (edge protection); PRP-21 follow-up (load limits)
- Evidence: none yet

Load tests exist, but edge denial-of-service protection is customer platform design and is not
asserted here.

## SC-7 Boundary Protection

- Status: `implemented_tested`
- Implementing PRPs: PRP-12, PRP-20
- Evidence:
  - `tests/security/network/test_bicep_network.py`
  - `tests/security/network/test_networkpolicy_render.py`

Bicep modules use private endpoints, and network policy is rendered and tested. Gaps (in-cluster
egress proof) are listed as OPEN.

## SC-8 Transmission Confidentiality and Integrity

- Status: `designed`
- Implementing PRPs: PRP-12
- Evidence:
  - `infra/helm/templates/ingress.yaml`
  - `docs/security/threat-model.md`

Transport protection is defined per boundary in the threat model; TLS termination is configured
through the ingress template.

## SC-12 Cryptographic Key Establishment and Management

- Status: `inherited`
- Implementing PRPs: PRP-20
- Evidence:
  - `docs/compliance/responsibility-matrix.md`
  - `docs/security/runbooks/key-vault-references.md`

Key custody is the platform vault and the customer, per docs/compliance/responsibility-matrix.md.
Options that need customer-managed keys are disabled where a service lacks them. Inherited controls
do not automatically authorize this application.

## SC-18 Mobile Code

- Status: `implemented_tested`
- Implementing PRPs: PRP-19
- Evidence:
  - `packages/core/neurosphere_core/charts/validator.py`
  - `packages/core/tests/charts`

Generated charts are a declarative subset (no expressions, signals or external data) and render in a
sandboxed iframe.

## SC-28 Protection of Information at Rest

- Status: `inherited`
- Implementing PRPs: PRP-20
- Evidence:
  - `docs/compliance/responsibility-matrix.md`
  - `docs/evidence/G02/register.yaml`

Encryption at rest is a platform service capability, per docs/compliance/responsibility-matrix.md.
Inherited controls do not automatically authorize this application.
