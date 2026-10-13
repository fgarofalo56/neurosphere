"""Entra access-token validation (PRP-06 item 1): per-cloud issuers, JWKS cache, dev issuer."""

from neurosphere_core.auth.jwt.claims import VerifiedClaims
from neurosphere_core.auth.jwt.config import (
    ALLOWED_ALGORITHMS,
    DevIssuerTrust,
    JwtConfig,
    entra_issuers,
    entra_jwks_uri,
)
from neurosphere_core.auth.jwt.dev_issuer import DevIssuer
from neurosphere_core.auth.jwt.jwks import (
    AsyncHttpClient,
    Clock,
    HttpJwksFetcher,
    JwksCache,
    JwksFetcher,
    SigningKey,
    parse_jwks,
)
from neurosphere_core.auth.jwt.validator import (
    JwtValidator,
    create_jwt_validator,
    extract_bearer_token,
)

__all__ = [
    "ALLOWED_ALGORITHMS",
    "AsyncHttpClient",
    "Clock",
    "DevIssuer",
    "DevIssuerTrust",
    "HttpJwksFetcher",
    "JwksCache",
    "JwksFetcher",
    "JwtConfig",
    "JwtValidator",
    "SigningKey",
    "VerifiedClaims",
    "create_jwt_validator",
    "entra_issuers",
    "entra_jwks_uri",
    "extract_bearer_token",
    "parse_jwks",
]
