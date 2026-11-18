# Entra role mapping: administrators from Entra (PRP-138)

This page is for the person who deployed NeuroSphere, signed in with Entra and got "Access
denied" on every Admin page. It explains how to let an Entra app role (or, optionally, an Entra
group) make someone a NeuroSphere administrator without a developer script.

Why the denial happens: the console shows Admin pages based on the `roles` claim of your ID
token, but the API decides from your access token and, without a mapping, only from the policy
store. A fresh deployment has an empty policy store, so every Admin API call answers 403.

## 1. What the mapping is, and what it is not

The mapping is one piece of deployment configuration, the setting `NS_AUTH_ROLE_MAPPINGS`. When
a request arrives with an Entra access token for this deployment's tenant and API audience, and
the token's `roles` claim (or `groups` claim) holds a value the mapping names, the API adds the
mapped NeuroSphere role to that request's scope.

- **Nothing is written to the policy store.** The role exists only while the token is valid.
  A mapped administrator who has no stored policy document does not appear in the principals
  list; the audit record `identity.claim_role_applied` is the trail.
- **The role lasts as long as the token.** The mapped assignment expires at the token's `exp`.
  Nothing renews it except a new token from Entra.
- **No extra power.** A mapped `admin` holds exactly the normal `admin` permission set, the same
  as a stored admin, checked by the same route dependencies. There is no unrestricted bypass.
  Administrators do not approve content capture: that needs a second steward holding
  `action.approve`, which `admin` does not include.
- With no mapping configured (the default) token roles and groups change nothing at all.

## 2. The setting

`NS_AUTH_ROLE_MAPPINGS` is a JSON object on the API (not a secret: it holds identifiers only):

```bash
export NS_AUTH_ROLE_MAPPINGS='{"tenant_id": "<tenant guid>", "audience": "<api app id>", "entries": [{"id": "ns-admins", "claim": "roles", "value": "admin", "role": "admin", "domains": "all", "customer_control": true}]}'
```

| Field | Meaning |
|---|---|
| `tenant_id` | Must equal `NS_AUTH_TENANT_ID`. |
| `audience` | Must equal one of `NS_AUTH_AUDIENCES` (normally the API app's client id). |
| `entries[].id` | Your name for the entry, `^[a-z][a-z0-9-]{0,62}$`, unique. Shown in audit. |
| `entries[].claim` | `roles` (app role values, the default path) or `groups` (group object ids). |
| `entries[].value` | The app role value, or the group object id (a GUID) for `groups`. |
| `entries[].role` | One of `viewer`, `analyst`, `domain_steward`, `admin`, `security_auditor`. |
| `entries[].domains` | `"all"` (the control domain if flagged, plus every active registered domain) or a list of domain ids. |
| `entries[].customer_control` | `true` adds the reserved customer control domain, which every deployment-wide Admin page needs. |

Limits and failures:

- At most 32 entries. One claim value maps to exactly one role.
- Only the five roles above can be mapped. A role added later is not mappable until someone adds
  it on purpose.
- `"all"` is expanded by the server from the domain registry (cached for about 30 seconds), so
  domains registered later are covered and retired ones drop out. A domain that exists only in
  catalog data and was never registered is not covered. At 1000 or more active domains an `all`
  entry is refused (503 `role_mapping_domain_overflow`) rather than granting a partial scope.
- An explicit list of domain ids is not checked against the domain registry: a listed domain
  stays in the mapped role after it is retired, until the list is edited. Use `"all"` when the
  role should follow the registry.
- The mapping is bound to the tenant and audience it names. A token of another tenant, another
  audience, an app-only token (no `scp`) or a development issuer outside local mode maps
  nothing. A copy of the setting on another deployment grants nothing there.
- Startup failures (the `authz` component is not ready and protected routes answer 503):
  - `role_mapping_invalid`: malformed JSON, an unknown key, an unknown role, a duplicate entry id,
    one value mapped to two roles, a `groups` value that is not a GUID, or a domain id of another
    cloud or customer.
  - `role_mapping_binding_mismatch`: `tenant_id` or `audience` does not match the deployment's
    `NS_AUTH_TENANT_ID` / `NS_AUTH_AUDIENCES`.

Where to set it: on the hosted demo deployment it is the Bicep parameter `entraRoleMappings`
(the same object; wiring is PRP-138 item 9 and lands after PRP-139). For Helm and
`infra/appservice` deployments the setting is documented here only; no chart value or
template parameter exists yet, so set it as an API environment variable yourself.

## 3. The Entra step

The mapping only says "the `admin` app role means NeuroSphere admin". Entra decides who holds
that app role.

### With the script

`scripts/gates/entra_admin_mapping.py` reads and changes only the API app registration and its
service principal, through Microsoft Graph with your own `az` sign-in. It never runs a deployment
and never prints a token, a secret or a user, group or service principal object id.

First look, with Graph reads only (the default subcommand, nothing changes):

```bash
python scripts/gates/entra_admin_mapping.py plan --cloud commercial --app-id <api-app-id> --tenant-id <tenant-id> --assign-user <your-upn>
```

It prints the app role values before and after, and whether the user (or the group, with
`--group-object-id <guid>`) already holds the `admin` app role. Then apply:

```bash
NS_LIVE_APPROVED=1 python scripts/gates/entra_admin_mapping.py apply --cloud commercial --app-id <api-app-id> --tenant-id <tenant-id> --approve entra-app --assign-user <your-upn>
```

`apply` refuses unless both `NS_LIVE_APPROVED=1` and `--approve entra-app` are given, and refuses
when the active `az cloud show` does not match `--cloud` (`commercial` is `AzureCloud`,
`government` is `AzureUSGovernment`; each talks only to its own Graph host). It adds the `admin`
app role when missing (allowed member type `User` only), assigns exactly one user
(`--assign-user`, object id or UPN) or group (`--group-object-id`), prints what it changed, and
prints the `NS_AUTH_ROLE_MAPPINGS` value and the `entraRoleMappings` parameter to use. Running it
again finds nothing to do and sends no write. If the app has no service principal in the tenant
yet, the script stops and tells you; it does not create one.

### By hand (Entra admin center)

1. App registrations, open the API app, App roles: make sure a role with value `admin` is enabled
   with allowed member types "Users/Groups" (Graph value `User`, the one the script sets; Microsoft
   Graph documents `User` as assignable to users and groups, and only direct members of an
   assigned group get the role). Create it if missing.
2. Enterprise applications, open the same app, Users and groups, Add user/group: pick the person
   (or group) and the `admin` role, then Assign.
3. Put the mapping value from section 2 on the API, with your tenant id and API app id, and
   restart the API.

## 4. Who can now create administrators

Anyone who can assign the app role in Entra can make a NeuroSphere administrator: owners of the
app registration or enterprise application, and holders of the Application Administrator or
Cloud Application Administrator directory roles (and Global Administrator). Review who holds
those before you turn the mapping on. The Entra role mapping panel in the console says the same.

## 5. Groups

- Assigning a group to an app role needs at least Microsoft Entra ID P1. On a tenant without it,
  Graph refuses; the script says so in plain words and suggests `--assign-user`. (UNVERIFIED: the
  exact Graph error text for that refusal; the script recognises it by keywords and, if it
  cannot, still names P1 as the likely cause.)
- Users in a group assigned to the app role receive the app role in the `roles` claim, so a
  `roles` entry is all you need. That is the recommended path.
- A `groups` entry instead reads the token's `groups` claim, which needs the API app to emit
  group claims (for example "Groups assigned to the application"; direct membership only).
- Group overage: when a user is in more than 200 groups, Entra leaves `groups` out of the token
  and sends an overage indicator instead. NeuroSphere then applies no `groups` entry (app role
  entries still apply), makes no Microsoft Graph call, counts it as `groups_overage`, and
  `GET /api/v1/me/access` reports `groups_overage: true`. Use an app role for those users.

## 6. Revocation

- Remove the app role assignment (or the group membership) in Entra. Access ends when the
  person's current access token expires, because the next token carries no mapped value. The
  token lifetime is set by the tenant (UNVERIFIED: the Entra default of about one hour).
- To end it at once, revoke the principal in the console (Admin, Identity) or with
  `POST /api/v1/admin/identity/principals/{principal_id}/revocation`; revocation is checked
  before any mapping. See [identity-admin.md](identity-admin.md#6-revoking-a-principal).

## 7. First admin on a new deployment, with no script

1. In Entra, do section 3 "By hand", assigning yourself the `admin` app role.
2. Set `NS_AUTH_ROLE_MAPPINGS` on the API as in section 2 and restart it. Check readiness: if the
   `authz` component reports `role_mapping_invalid` or `role_mapping_binding_mismatch`, fix the
   value.
3. Sign out of the console and sign in again, so both the ID token and the access token are new.
4. Open Admin, Identity, "Your access": you should see `admin` with source `entra_app_role` and
   `customer_control` true. The Admin pages now load.
5. Register your first domain. It is covered by the `all` entry within about 30 seconds.
6. Optional: give yourself or a colleague a stored, time-bound assignment through the identity
   admin API as a fallback; the old `sbx_grant_operator.py` script is no longer needed for this.

## 8. Display roles and API roles

The console decides which entries to show from the `roles` claim of the **ID token**; the API
decides what you may do from the **access token** and the mapping. When the frontend and the API
use one app registration (the hosted demo sets the audience to the client id) both tokens carry
the same app roles, so what you see matches what you may do.

When they are two app registrations, the app role must exist and be assigned on each: the
frontend app's role only drives the menu, and the API app's role is what the mapping reads. If
only the frontend app has it, you see the Admin pages and get 403; if only the API app has it,
the API allows you but the menu may hide the pages. The forbidden state on Admin pages names the
missing permission and links to "Your access", which shows what the API sees.

## 9. Commercial and Government

Commercial and Government are separate deployments with separate tenants, app registrations and
mappings. A mapping names one tenant and audience, and a token of the other cloud is already
refused before any mapping is read, so a mapping never crosses clouds. Run the script with the
matching `--cloud` and an `az` session in that cloud; it refuses a mismatch.

## 10. Live gate and open items

Live gate G-138 is OPEN until an operator runs `apply` and then `verify` against a deployed API
and the evidence is recorded:

```bash
NS_LIVE_APPROVED=1 uv run python scripts/gates/entra_admin_mapping.py verify --cloud commercial --app-id <api-app-id> --tenant-id <tenant-id> --base-url https://<api-host>
```

`verify` holds a token in memory only, calls `GET /api/v1/me/access` and
`GET /api/v1/admin/system/status`, and writes status codes, role names and sources and timestamps
to `docs/evidence/PRP-138/`. Without `NS_LIVE_APPROVED=1` it reports the gate OPEN (exit 2).
UNVERIFIED: that `az account get-access-token` can obtain a token for the API app in your tenant
(the Azure CLI may not be pre-authorised for it); when it cannot, `verify` prints a manual
browser check and the gate stays OPEN (exit 3).

- A Government run is a separate OPEN gate and is never satisfied by a Commercial one.
- Helm and `infra/appservice` wiring of the setting is not done.
- This mapping is an access control feature. It makes no FedRAMP or other compliance claim.

## 11. Rollback

Unset `NS_AUTH_ROLE_MAPPINGS` and restart the API. Every scope is then derived from the policy
store alone, as before. Nothing was stored, so there is nothing to clean up. Remove the Entra
app role assignments too if they should no longer drive the menu.
