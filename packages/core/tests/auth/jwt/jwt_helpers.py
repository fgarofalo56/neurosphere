"""Shared fixtures for item 1 tests: fake clock, fake JWKS fetcher, signers and token builders.

"Entra" signers here are local RSA keys whose JWKS is served by a fake fetcher (or respx); no
real tenant, credential or network call is involved (PRP-06 C2).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from functools import cache
from typing import Any

from cryptography.hazmat.primitives import serialization
from neurosphere_core.auth.jwt import (
    DevIssuer,
    JwksCache,
    JwtConfig,
    JwtValidator,
    entra_issuers,
    entra_jwks_uri,
)
from neurosphere_core.cloud import CloudName, Settings

TENANT = "0f1e2d3c-4b5a-4968-8776-a5b4c3d2e1f0"
OTHER_TENANT = "9a8b7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c6d"
AUDIENCE = "api://neurosphere-test-api"
OBJECT_ID = "6c1d2e3f-4a5b-4c6d-8e7f-90a1b2c3d4e5"
T0 = 1_800_000_000.0
ENTRA_KID = "entra-kid-1"


class FakeClock:
    def __init__(self, now: float = T0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeFetcher:
    """Counts fetches; serves ``document`` or raises ``error``."""

    def __init__(self, url: str, document: Any) -> None:
        self._url = url
        self.document = document
        self.error: Exception | None = None
        self.calls = 0

    @property
    def url(self) -> str:
        return self._url

    async def fetch(self) -> Any:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.document


def settings(env: str = "prod", cloud: CloudName | None = CloudName.COMMERCIAL) -> Settings:
    return Settings(env=env, cloud=cloud)  # pyright: ignore[reportArgumentType]


def signer(kid: str = ENTRA_KID) -> DevIssuer:
    """A local RSA signer (one per kid), used as a fake Entra key or as the local dev issuer."""
    return _signer(kid)


@cache
def _signer(kid: str) -> DevIssuer:
    return DevIssuer(settings("local"), tenant_id=TENANT, kid=kid)


def entra_claims(
    cloud: CloudName = CloudName.COMMERCIAL,
    *,
    now: float = T0,
    version: str = "2.0",
    tenant: str = TENANT,
    **overrides: Any,
) -> dict[str, Any]:
    issuer = next(i for i, v in entra_issuers(cloud, tenant).items() if v == version)
    claims: dict[str, Any] = {
        "iss": issuer,
        "aud": AUDIENCE,
        "tid": tenant,
        "oid": OBJECT_ID,
        "sub": "pairwise-subject-1",
        "ver": version,
        "iat": int(now),
        "nbf": int(now),
        "exp": int(now) + 3600,
        "roles": ["Analyst"],
        "scp": "catalog.read reports.read",
        "azp" if version == "2.0" else "appid": "c0ffee00-0000-4000-8000-000000000001",
    }
    claims.update(overrides)
    return {k: v for k, v in claims.items() if v is not None}


def make_validator(
    cloud: CloudName = CloudName.COMMERCIAL,
    *,
    env: str = "prod",
    jwks: dict[str, Any] | None = None,
    clock: FakeClock | None = None,
    dev: DevIssuer | None = None,
    ttl: float = 3600,
    interval: float = 300,
) -> tuple[JwtValidator, FakeFetcher, FakeClock]:
    clock = clock or FakeClock()
    config = JwtConfig(
        env=env,  # pyright: ignore[reportArgumentType]
        cloud=cloud,
        tenant_id=TENANT,
        audiences=(AUDIENCE,),
        dev_issuer=dev.trust() if dev is not None else None,
    )
    fetcher = FakeFetcher(entra_jwks_uri(cloud, TENANT), jwks or signer().jwks())
    cache_ = JwksCache(fetcher, clock=clock, ttl_seconds=ttl, min_refresh_interval_seconds=interval)
    return JwtValidator(config, cache_, clock=clock), fetcher, clock


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def unsigned_token(header: dict[str, Any], claims: dict[str, Any], signature: str = "") -> str:
    head = _b64(json.dumps(header).encode())
    body = _b64(json.dumps(claims).encode())
    return f"{head}.{body}.{signature}"


def hs256_with_public_key(claims: dict[str, Any], kid: str = ENTRA_KID) -> str:
    """Algorithm-confusion token: HMAC-SHA256 keyed with the RSA public key PEM."""
    public_key = signer(kid)._private_key.public_key()  # pyright: ignore[reportPrivateUsage]
    pem = public_key.public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    head = _b64(json.dumps({"alg": "HS256", "kid": kid, "typ": "JWT"}).encode())
    body = _b64(json.dumps(claims).encode())
    mac = hmac.new(pem, f"{head}.{body}".encode(), hashlib.sha256).digest()
    return f"{head}.{body}.{_b64(mac)}"
