# Security model

> _Fill in during the build (PRP §6 / §7)._

- **Identity / auth:** OAuth2 bearer (RS256 JWT from the local issuer;
  stands in for Microsoft Entra ID). The gateway validates against the
  issuer JWKS; a request with no / invalid token is rejected at the edge
  and never reaches the auto-API.
- **Rate limiting / quota:** gateway `rate-limiting` (429 +
  `Retry-After`).
- **OWASP API Top 10 at the gateway:** document which controls map to
  which risks.
- **Classify before exposure:** `data/classification.yml` labels are
  applied at seed and surfaced in the catalog.
- **Secrets:** via `.env` (gitignored); no secrets in the repo.
