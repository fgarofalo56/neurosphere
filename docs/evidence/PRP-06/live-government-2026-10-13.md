# PRP-06 live Entra validation: government (2026-10-13)

Operator-approved live run (NS_LIVE_APPROVED=1). Tenant `03f141f3-496d-4319-bbea-a3e9286cab10`, API app `e5bfaf24-14fa-4a18-b8da-ba7f37b516cb`.
A delegated user token was minted with `az` and validated by the production validator
against live JWKS. No token, identity, oid or UPN is recorded here.

| Check | Outcome | Pass |
|---|---|---|
| valid live token accepted | issuer_kind=entra ver=2.0 cloud=government audience_is_guid=True issuer_is_v2=True scopes=['access_as_user'] | yes |
| wrong audience rejected | UnauthorizedError status=401 reason=wrong_audience | yes |
| wrong tenant rejected | DependencyTransientError status=502 reason=jwks_unavailable | yes |
| other cloud's authority rejected | DependencyTransientError status=502 reason=jwks_unavailable | yes |
| tampered payload rejected | UnauthorizedError status=401 reason=invalid_signature | yes |
| empty token rejected | UnauthorizedError status=401 reason=missing_token | yes |

Reading the rejections: wrong audience and tampered payload are 401s from the
validator's own checks. 'Wrong tenant' and 'other cloud' are rejected as 502
jwks_unavailable (fail closed) because no JWKS exists for that tenant or authority;
they do NOT exercise the issuer comparison,
which the unit tests cover with local keys (packages/core/tests/auth/jwt).

Not covered: expiry (needs a wait), app-only tokens, Government v1 issuer shape.
This is not an authorization, ATO or compliance claim.
