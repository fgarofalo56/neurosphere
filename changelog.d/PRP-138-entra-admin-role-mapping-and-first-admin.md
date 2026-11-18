### Added
- Entra role mapping (PRP-138, PR #330): the deployment setting `NS_AUTH_ROLE_MAPPINGS` maps Entra app role values (the `roles` claim) and, optionally, group object ids (the `groups` claim) to NeuroSphere roles at request time, so the first administrator needs no script. The mapping is off by default, bound to one tenant and audience, applies to delegated user tokens only, and each mapped role expires with the token. Nothing is written to the policy store.
- `GET /api/v1/me/access`: any signed-in caller sees their own roles and whether each came from an Entra app role, an Entra group or the policy store.
- `GET /api/v1/admin/identity/role-mapping`: read-only view of the effective mapping for holders of deployment-wide `policy.manage`.
- Admin console: read-only "Entra role mapping" and "Your access" panels on the Identity page.
- Audit operation `identity.claim_role_applied`, written once per token when a mapped role is applied; a failed audit write refuses the request.
- Operator script `scripts/gates/entra_admin_mapping.py` (`plan`, `apply`, `verify`) and runbook `docs/runbooks/entra-role-mapping.md`.

### Changed
- A 403 for a missing permission now names it ("this operation needs `<permission>`"), and the Admin console forbidden state shows that text and the caller's own access.
- Group overage tokens (`hasgroups` or `_claim_names.groups`) are flagged on the verified claims and their group list is ignored; no Microsoft Graph call is made.

### Security
- Token role and group claims remain non-authoritative unless a mapping is configured. Startup fails closed on an invalid mapping (`role_mapping_invalid`) or one bound to another tenant or audience (`role_mapping_binding_mismatch`).
