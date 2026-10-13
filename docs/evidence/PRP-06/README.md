# PRP-06 evidence (identity, authorization, audit)

Measured 2026-10-12. Local emulators and public, unauthenticated metadata only: no paid calls, no tenant, no credentials.

## Verified

| Check | Result |
|---|---|
| Audit store against the Cosmos vNext emulator (`docker compose up -d --wait cosmos`, `pytest packages/core/tests/audit/test_cosmos_integration.py -m integration`) | 1 passed: append, chain verify, and no code path rewrites a written record |
| Snyk code scan (`snyk code test`) on `neurosphere_core/auth`, `neurosphere_core/audit`, `neurosphere_api/authz`, `neurosphere_api/audit`, `tests/security/authz` | 0 issues in each |
| Public OIDC v2 discovery, Commercial (`login.microsoftonline.com/common/v2.0`) | issuer `https://login.microsoftonline.com/{tenantid}/v2.0`, matches `entra_issuers` |
| Public OIDC v2 discovery, Government (`login.microsoftonline.us/common/v2.0`) | issuer `https://login.microsoftonline.us/{tenantid}/v2.0`, matches `entra_issuers` |

## Emulator deltas (G12)

The Cosmos emulator enforces no auth, so it cannot prove service-side audit immutability. The test above proves only the repository code paths. The Cosmos policy and revocation stores (`CosmosPolicyRepository`, `CosmosRevocationStore`) are covered by fakes and mocked clients, not by an emulator test.

## OPEN (not verified, not claimed)

- **Live Entra token validation, Commercial and Government.** Needs a registered app and `NS_LIVE_APPROVED=1`. Government also needs a Government tenant.
- **Government v1 issuer host.** `/common` v1 metadata for both clouds advertises `https://sts.windows.net/{tenantid}/`. The allowlist uses `sts.usgovcloudapi.net` for Government, which no measurement confirms. It fails closed (a real Government v1 token would get 401). Do not change it without a real Government token. Register the API with `accessTokenAcceptedVersion=2` so v2 is the path in use.
- **Service-level audit immutability on real Cosmos** (immutable storage or write-once configuration).
- **No FedRAMP, ATO or compliance parity claim.** Availability, feature maturity and authorization remain separate gates.
