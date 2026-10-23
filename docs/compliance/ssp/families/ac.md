# AC: Access Control (SSP narratives)

- Scope: NeuroSphere application controls mapped to NIST SP 800-53 Rev 5 family AC. Baseline selection is a customer input, see [scope.md](../scope.md). Machine-readable source: [control-mapping.yaml](../control-mapping.yaml).
- Status vocabulary: `designed`, `implemented_tested`, `inherited`, `customer`, `planned`, `not_applicable`.
- Statement: not FedRAMP authorized; the authorizing official decides. Inherited entries follow [the responsibility matrix](../../responsibility-matrix.md) and do not automatically authorize this application.

These narratives are source material for the customer's SSP. They are generated from `control-mapping.yaml`; edit the YAML, not this file.

## AC-2 Account Management

- Status: `customer`
- Implementing PRPs: PRP-06
- Owner: Customer identity team (Entra tenant, role assignments, privileged-access process)
- Evidence:
  - `packages/core/neurosphere_core/scope/identity_scope.py`

Accounts and role assignments live in the customer Entra tenant. NeuroSphere consumes validated
tokens and derives IdentityScope server-side; it does not create or manage accounts. Privileged
roles are scoped and time-bound, never an unrestricted bypass.

## AC-3 Access Enforcement

- Status: `implemented_tested`
- Implementing PRPs: PRP-06, PRP-22
- Evidence:
  - `tests/security/authz/test_api_paths.py`
  - `tests/security/authz/test_export_paths.py`
  - `tests/security/authz/test_search_paths.py`
  - `tests/security/mcp/test_confused_deputy.py`

Authorization is enforced at every query, tool, export, push and action path using a server-derived
IdentityScope. Caller- or model-supplied domain or customer identifiers are ignored. Hidden
navigation is not authorization; the API denies.

## AC-4 Information Flow Enforcement

- Status: `implemented_tested`
- Implementing PRPs: PRP-12, PRP-20
- Evidence:
  - `tests/security/egress/test_allowlist_no_commercial.py`
  - `tests/security/egress/test_compose_egress_blocked.py`

Government profiles carry an egress allowlist with no Commercial endpoint, and Government data is
never bridged to Commercial. Compose-level egress is tested; the in-cluster proof of no Commercial
egress is OPEN (see docs/RESEARCH-AND-GATES.md, G02).

## AC-5 Separation of Duties

- Status: `designed`
- Implementing PRPs: PRP-17
- Evidence:
  - `packages/core/neurosphere_core/hitl/authz.py`

Governed actions pass a human-in-the-loop approval policy; the requester and approver roles are
distinct in the HITL authorization module.

## AC-6 Least Privilege

- Status: `implemented_tested`
- Implementing PRPs: PRP-06
- Evidence:
  - `tests/security/authz/test_privileged_roles.py`

Privileged users receive scoped permissions with an expiry. Tests assert that privileged roles do
not bypass domain scoping.

## AC-17 Remote Access

- Status: `customer`
- Implementing PRPs: PRP-20
- Owner: Customer network and security team (connectivity to agency networks, VPN, firewall)
- Evidence:
  - `infra/helm/templates/networkpolicy.yaml`

Remote access paths into the customer-hosted deployment are customer network design. NeuroSphere
ships private-endpoint network configuration and network policy only.
