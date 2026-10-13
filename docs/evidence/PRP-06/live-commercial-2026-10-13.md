# PRP-06 live Entra validation: commercial (2026-10-13)

Operator-approved live run (NS_LIVE_APPROVED=1). Tenant `d1fc0498-f208-4b49-8376-beb9293acdf6`, API app `ace128f6-2389-43d1-84ba-40efa53937aa`.
A delegated user token was minted with `az` and validated by the production validator
against live JWKS. No token, identity, oid or UPN is recorded here.

| Check | Outcome | Pass |
|---|---|---|
| valid live token accepted | issuer_kind=entra ver=2.0 cloud=commercial audience_is_guid=True issuer_is_v2=True scopes=['access_as_user'] | yes |
| wrong audience rejected | UnauthorizedError status=401 reason=wrong_audience | yes |
| wrong tenant rejected | DependencyTransientError status=502 reason=jwks_unavailable | yes |
| other cloud's authority rejected | DependencyTransientError status=502 reason=jwks_unavailable | yes |
| tampered payload rejected | UnauthorizedError status=401 reason=invalid_signature | yes |
| empty token rejected | UnauthorizedError status=401 reason=missing_token | yes |

Not covered: expiry (needs a wait), app-only tokens, Government v1 issuer shape.
This is not an authorization, ATO or compliance claim.
