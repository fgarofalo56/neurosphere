# Identity admin: who has access, and changing it

The identity admin API (PRP-39) lets an administrator see who has access and change it without
Cosmos access: role assignments, domain memberships and resource-scoped grants, plus revoking a
principal. Every change is authorized, audited and versioned. There is no unrestricted bypass:
no role, header or flag skips a check.

The console page for this API arrives with PRP-53. Until then, call the API with a bearer token.

## 1. Bootstrap the first admin (script)

The API needs an existing admin, so the first one is granted with the operator script, exactly as
before. It writes a time-bound `admin` assignment over the sandbox domains, including the
customer-control domain, so that admin holds customer-wide `policy.manage`.

```bash
make grant-operator OPERATOR_OID=<object-id> OPERATOR_ROLE=admin
```

The script needs `NS_AUTH_TENANT_ID` (see [operations.md](operations.md)). Run it once per new
deployment, or to recover when no admin is left. Everything after this uses the API.

## 2. Routes

All routes are under `/api/v1/admin/identity`. Principals are named only by their pseudonymous
canonical id (`<cloud>:<customer>:entra:person:p-<64 hex>`); names, e-mail addresses, UPNs and
raw object ids are never accepted or returned.

| Method | Path | Permission |
|---|---|---|
| GET | `/principals?limit=&cursor=` | `policy.manage` |
| GET | `/principals/{principal_id}` | `policy.manage` |
| PUT, DELETE | `/principals/{principal_id}/role-assignments/{assignment_id}` | `policy.manage` |
| PUT, DELETE | `/principals/{principal_id}/domain-memberships/{domain_id}` | `policy.manage` |
| PUT, DELETE | `/principals/{principal_id}/grants/{grant_id}` | `policy.manage` |
| POST, GET, DELETE | `/principals/{principal_id}/revocation` | `revocation.manage` |

Request bodies are the `admin/v1` contracts: `RoleAssignmentChange` (`op: assign`),
`DomainMembershipChange` (`op: add`), `ResourceGrantChange` and `RevocationRequest`. Removes
take an optional `?reason=<reason_code>`; every reason is a snake_case code, never free text.

## 3. What an admin may change

For every write, in this order (each refusal is a 403 with a reason code and an audit record,
and nothing is written):

1. The target is in your own cloud and customer (`cross_scope_target`).
2. It is not your own policy document (`self_modification_forbidden`). Ask another admin.
3. You hold `policy.manage` on every domain the change names, including the domains of an
   assignment you replace or remove and the domain that owns a granted resource
   (`target_out_of_scope`). `grant.write` is not enough for a resource grant.
4. Assigning or removing `admin` or `security_auditor`, and any change on the customer-control
   domain, needs customer-wide `policy.manage` (`customer_scope_required`).
5. Privileged roles must carry `expires_at`, and every grant must carry `expires_at` and a
   reason; an expiry in the past is refused (422).

The list and detail views show only principals with a membership or assignment in a domain you
manage, and only those domains' entries.

## 4. Concurrent edits

`GET /principals/{principal_id}` returns an `ETag`. Send it as `If-Match` on every change to an
existing principal. A missing `If-Match` is 422 with reason `precondition_required`; a stale one
is 409 `stale_version` (re-read and retry). Creating the first entry for a new principal sends no
`If-Match`. Each accepted change advances the policy version; the replica that served it applies
the new scope at once, and every other replica within the policy cache TTL (30 seconds).

## 5. Audit

Each change writes a `before` record, the change, then an `after` record on the audit chain of
every domain it names (`policy.role_assign`, `policy.role_remove`, `policy.membership_add`,
`policy.membership_remove`, `policy.grant_put`, `policy.grant_remove`). Revocation records
(`principal.revoke`, `principal.revoke_lift`) go to the customer chain
`<customer>.identity-admin`. Refusals are recorded as denied attempts.

## 6. Revoking a principal

`POST /principals/{principal_id}/revocation` with `mode`:

* `issued_before`: every token issued at or before the revocation (plus 60 seconds of clock
  skew) is refused. The principal may sign in again; disabling the account is an Entra action.
* `until_lifted`: every token is refused, including ones issued later, until an admin lifts it
  with `DELETE /principals/{principal_id}/revocation`. Tokens from before the block stay
  refused after the lift. A block never expires on its own.

Revocation is bounded by `NS_REVOCATION_TTL_SECONDS` (default 60), not instant: the replica that
revoked refuses at once and closes the principal's push sessions; other replicas refuse within
the bound reported as `propagation_bound_seconds`. A revocation store outage is 503, never an
allow. Revoking needs `revocation.manage` in any domain (an admin of one domain may revoke any
principal of the same customer, because revocation only removes access).

## 7. Turning it off or rolling back

Do not grant `policy.manage` and every write route denies. To roll back the code, lift every
`until_lifted` block first. Plain `issued_before` entries keep the PRP-06 document shape, but a
block, and an entry that was lifted, carry fields code from before PRP-39 does not know: it reads
them as invalid and refuses that principal (502) until retention removes a lifted entry. A block
has no retention, so an unlifted block keeps that principal locked out after a rollback.

## 8. Settings

No new environment variables. The API uses `NS_AUTH_POLICY_CONTAINER` (the policy container
derivation reads) and the existing `NS_REVOCATION_TTL_SECONDS`,
`NS_REVOCATION_RETENTION_SECONDS` and `NS_REVOCATION_CLOCK_SKEW_SECONDS`.
