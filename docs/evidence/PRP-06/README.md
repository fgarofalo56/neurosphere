# PRP-06 evidence (identity, authorization, audit)

Measured 2026-10-12 and 2026-10-13. Local emulators, public unauthenticated metadata, and two
operator-approved live runs (`NS_LIVE_APPROVED=1`) against throwaway Commercial resources.

## Verified

| Check | Result |
|---|---|
| Audit store against the Cosmos vNext emulator (`docker compose up -d --wait cosmos`, `pytest packages/core/tests/audit/test_cosmos_integration.py -m integration`) | 1 passed |
| Snyk code scan on `neurosphere_core/auth`, `neurosphere_core/audit`, `neurosphere_api/authz`, `neurosphere_api/audit`, `tests/security/authz` | 0 issues in each |
| Public OIDC v2 discovery, Commercial and Government | issuers match `entra_issuers` |
| **Live Entra, Commercial** (`scripts/gates/prp06_entra_live.py`, app `neurosphere-api-dev` in the Limitlessdata tenant) | real v2 delegated token accepted by the production validator; wrong audience and tampered payload are 401; see `live-commercial-2026-10-13.md` |
| **Live Cosmos, Commercial** (`scripts/gates/prp06_cosmos_live.py`, throwaway serverless account) | audit chain with 4 parallel writers verifies; replace, upsert, patch and delete on audit records are refused by the service (HTTP 403); policy and revocation stores work through their repositories; see `live-cosmos-2026-10-13.md` |

Live token facts (Commercial, app registered with `requestedAccessTokenVersion=2`): issuer
`https://login.microsoftonline.com/<tenant>/v2.0`, `ver` 2.0, and **`aud` is the bare app-id GUID,
not `api://<id>`**. Configure the GUID as the audience.

## Audit immutability: what is and is not shown

The service-level result needed a layout change: the tail pointer needs `replace`, and Cosmos
data-plane RBAC is scoped to a container, so `CosmosAuditStore` now accepts a separate
`tail_container`. With it, the records container is only written with `create_item`. A role granting
`items/read`, `items/create` and `executeQuery` there (and `replace` only on the tail container) makes
the records append-only for that identity at the service. This is not WORM: an account owner or a
holder of a broader data-plane or control-plane role can still change data, so the hash chain stays
the tamper-detection control. Real deployments must provision the split containers and these roles.

## Emulator deltas (G12)

The Cosmos emulator enforces no auth, so it cannot show any service-side enforcement; the live run
above is the evidence for that.

## OPEN (not verified, not claimed)

- **Government**: live Entra validation and the Government v1 issuer host. `/common` v1 metadata for
  both clouds advertises `https://sts.windows.net/{tenantid}/`, while the allowlist uses
  `sts.usgovcloudapi.net` for Government. It fails closed (a real Government v1 token would get 401).
  Register the API with `accessTokenAcceptedVersion=2` so v2 is the path in use.
- **Expiry and app-only tokens** were not exercised live.
- **Revocation per-item TTL expiry** on real Cosmos was not exercised (retention floor is 28 hours).
- **No FedRAMP, ATO or compliance parity claim.** Availability, feature maturity and authorization
  remain separate gates.
