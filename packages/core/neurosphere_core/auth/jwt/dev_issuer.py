"""Self-signed local token issuer for ``NS_ENV=local`` development and tests (PRP-06 C3).

The private key is generated in memory per instance and never written anywhere. Constructing a
``DevIssuer`` outside ``NS_ENV=local`` raises ``invalid_schema``; ``JwtConfig`` independently
refuses a dev issuer outside local, so a misconfigured deployment fails at startup.
"""

from __future__ import annotations

import secrets
import time
from collections.abc import Mapping, Sequence
from typing import Any, Final

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from neurosphere_core.auth.jwt.config import (
    DevIssuerTrust,
    dev_issuer_for,
    normalize_tenant_id,
)
from neurosphere_core.cloud import Settings
from neurosphere_core.errors import InvalidSchemaError

DEV_TOKEN_LIFETIME_SECONDS: Final = 3600
_KEY_BITS: Final = 2048


class DevIssuer:
    """Mints RS256 tokens shaped like Entra v2 access tokens, signed by a local key."""

    def __init__(self, settings: Settings, *, tenant_id: str, kid: str | None = None) -> None:
        if settings.env != "local":
            raise InvalidSchemaError(
                "the dev issuer is available only when NS_ENV=local", reason="config"
            )
        try:
            self.tenant_id = normalize_tenant_id(tenant_id)
        except ValueError as exc:
            raise InvalidSchemaError("dev issuer tenant must be a GUID", reason="config") from exc
        self.issuer = dev_issuer_for(self.tenant_id)
        self.kid = kid or f"dev-{secrets.token_hex(8)}"
        self._private_key = rsa.generate_private_key(public_exponent=65537, key_size=_KEY_BITS)

    def jwks(self) -> dict[str, Any]:
        """Public JWKS (no private members) for this issuer's signing key."""
        public = RSAAlgorithm.to_jwk(self._private_key.public_key(), as_dict=True)
        if not isinstance(public, dict):  # as_dict=True always yields a dict; narrow for typing
            raise TypeError("unexpected JWK serialization")
        return {"keys": [{**public, "kid": self.kid, "use": "sig", "alg": "RS256"}]}

    def trust(self) -> DevIssuerTrust:
        return DevIssuerTrust(issuer=self.issuer, jwks=self.jwks())

    def sign(self, claims: Mapping[str, Any], *, headers: Mapping[str, Any] | None = None) -> str:
        """Sign arbitrary ``claims`` with RS256 and this issuer's ``kid`` (tests use this to
        build deliberately invalid tokens)."""
        merged = {"kid": self.kid, "typ": "JWT", **(headers or {})}
        return jwt.encode(dict(claims), self._private_key, algorithm="RS256", headers=merged)

    def mint(
        self,
        *,
        audience: str,
        object_id: str,
        now: float | None = None,
        lifetime_seconds: int = DEV_TOKEN_LIFETIME_SECONDS,
        roles: Sequence[str] = (),
        scopes: Sequence[str] = (),
        extra: Mapping[str, Any] | None = None,
    ) -> str:
        """A well-formed v2-shaped token from this issuer. ``extra`` overrides any claim."""
        issued = int(time.time() if now is None else now)
        claims: dict[str, Any] = {
            "iss": self.issuer,
            "aud": audience,
            "tid": self.tenant_id,
            "oid": object_id,
            "sub": f"dev-sub-{object_id}",
            "ver": "2.0",
            "iat": issued,
            "nbf": issued,
            "exp": issued + lifetime_seconds,
        }
        if roles:
            claims["roles"] = list(roles)
        if scopes:
            claims["scp"] = " ".join(scopes)
        claims.update(extra or {})
        return self.sign(claims)
