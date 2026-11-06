# Action-plane kill switch (emergency disable)

`PUT /api/v1/actions/emergency-disable` stops (or resumes) action execution for the whole
customer. While it is on, the executor defers every intent (`emergency_disabled`) and makes zero
connector calls. `GET` on the same path reports the state to any reader.

## Who may flip it

The switch is customer-wide, so `config.manage` in an ordinary domain is not enough. The
permission model has no customer-wide role (no wildcard or superuser), so customer-level control is
`config.manage` on one reserved control domain per customer:

```
<cloud>:<customer>:neurosphere:domain:customer-control
e.g. commercial:contoso:neurosphere:domain:customer-control
```

The caller must hold the `admin` role on that domain (and be a member of it). `admin` is a
privileged role, so the assignment is time-bound and expires like any other.

## 403 `customer_scope_required`

The caller passed the normal `config.manage` check (some domain) but not the control-domain check.
The denial is audited. Fix by granting the control domain, not by widening ordinary domains.

## Granting it

Add the control domain to the operator's `admin` role assignment and `domain_memberships` in the
policy store (same document shape as any domain grant).

* Sandbox or hosted operator: `scripts/sandbox/sbx_grant_operator.py --role admin ...` now includes
  the control domain for `admin`; `scripts/sandbox/sbx_seed_stack.py --operator-object-id ...` does
  the same for the operator persona. Re-run the grant to renew (it is time-bound, 30 days).
* `scripts/gates/p29_entra_local.py --assign-self admin` only assigns the Entra app role (navigation
  display); authority still comes from the policy store, so run the grant script as well.

A policy naming another customer's or another cloud's control domain never matches.

## Not claimed

This documents an access-control design, not an authorization or compliance status.
