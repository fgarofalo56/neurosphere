# IA: Identification and Authentication (SSP narratives)

- Scope: NeuroSphere application controls mapped to NIST SP 800-53 Rev 5 family IA. Baseline selection is a customer input, see [scope.md](../scope.md). Machine-readable source: [control-mapping.yaml](../control-mapping.yaml).
- Status vocabulary: `designed`, `implemented_tested`, `inherited`, `customer`, `planned`, `not_applicable`.
- Statement: not FedRAMP authorized; the authorizing official decides. Inherited entries follow [the responsibility matrix](../../responsibility-matrix.md) and do not automatically authorize this application.

These narratives are source material for the customer's SSP. They are generated from `control-mapping.yaml`; edit the YAML, not this file.

## IA-2 Identification and Authentication (Organizational Users)

- Status: `inherited`
- Implementing PRPs: PRP-06, PRP-20
- Evidence:
  - `docs/compliance/responsibility-matrix.md`
  - `packages/core/neurosphere_core/auth/jwt/validator.py`

User authentication and MFA are operated by Microsoft Entra ID in the customer tenant, as recorded
in docs/compliance/responsibility-matrix.md. NeuroSphere validates tokens (issuer, audience,
signature). Inherited controls do not automatically authorize this application.

## IA-5 Authenticator Management

- Status: `designed`
- Implementing PRPs: PRP-12
- Evidence:
  - `docs/security/runbooks/secret-rotation.md`
  - `docs/security/runbooks/key-vault-references.md`

No secrets in files, prompts or logs. Vault references and managed identity are used in production;
a rotation runbook exists. A dev issuer is allowed only when NS_ENV=local.

## IA-9 Service Identification and Authentication

- Status: `designed`
- Implementing PRPs: PRP-07, PRP-22
- Evidence:
  - `tests/security/mcp/test_confused_deputy.py`
  - `docs/security/runbooks/key-vault-references.md`

Service-to-service calls use managed identity; MCP tokens are audience-checked and are not passed
through to other services.
