"""Bearer extraction and access-token validation (PRP-06 item 1).

Every rejection is ``unauthorized`` (401) with a snake_case reason; infrastructure failures while
establishing signing keys are ``dependency_transient`` (503/502). No path returns claims on error.

Order of checks: size and shape, header ``alg`` allowlist, ``kid`` lookup (dev keys only when the
config is local and a dev issuer is trusted, otherwise the cloud's own JWKS), algorithm pinned
from the key, signature plus ``iss``/``aud`` (PyJWT), then ``tid``, ``ver`` and lifetime against
the injected clock. Keys from the Entra JWKS validate only Entra issuers of the configured cloud
and tenant; dev keys validate only the dev issuer.
"""

from __future__ import annotations

import math
import re
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Final, Literal

import jwt
from pydantic import ValidationError

from neurosphere_core.auth.jwt.claims import MAX_LIST_CLAIM_ITEMS, VerifiedClaims
from neurosphere_core.auth.jwt.config import ALLOWED_ALGORITHMS, JwtConfig, TokenVersion
from neurosphere_core.auth.jwt.jwks import (
    DEFAULT_CACHE_TTL_SECONDS,
    DEFAULT_MIN_REFRESH_INTERVAL_SECONDS,
    MAX_KID_LENGTH,
    AsyncHttpClient,
    Clock,
    HttpJwksFetcher,
    JwksCache,
    JwksDocumentError,
    SigningKey,
    parse_jwks,
)
from neurosphere_core.errors import InvalidSchemaError, UnauthorizedError

MAX_TOKEN_LENGTH: Final = 16 * 1024
_TOKEN_SHAPE: Final = re.compile(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]*")
_REQUIRED_CLAIMS: Final = ["iss", "aud", "exp", "nbf", "iat", "tid", "oid", "sub"]
_DETAIL: Final = "invalid bearer token"


def _reject(reason: str, detail: str = _DETAIL) -> UnauthorizedError:
    return UnauthorizedError(detail, reason=reason)


def extract_bearer_token(authorization: str | None) -> str:
    """Return the token from an ``Authorization: Bearer <token>`` header value.

    Only the header is a token source; query strings, cookies and bodies are never consulted.
    """
    if authorization is None or not authorization.strip():
        raise _reject("missing_token", "bearer token required")
    scheme, _, token = authorization.strip().partition(" ")
    if scheme.lower() != "bearer":
        raise _reject("invalid_scheme", "bearer token required")
    token = token.strip()
    if not token:
        raise _reject("missing_token", "bearer token required")
    _check_shape(token)
    return token


def _check_shape(token: str) -> None:
    if len(token) > MAX_TOKEN_LENGTH or not _TOKEN_SHAPE.fullmatch(token):
        raise _reject("malformed_token")


class JwtValidator:
    """Validates access tokens for exactly one cloud and tenant (``JwtConfig``)."""

    def __init__(self, config: JwtConfig, jwks: JwksCache, *, clock: Clock = time.time) -> None:
        if jwks.source_url != config.jwks_uri:
            # Prevents wiring one cloud's config to the other cloud's (or any other) key set.
            raise InvalidSchemaError(
                "JWKS source does not match the configured cloud and tenant", reason="config"
            )
        self._config = config
        self._jwks = jwks
        self._clock = clock
        self._entra_issuers = config.entra_issuers
        self._dev_keys: dict[str, SigningKey] = {}
        self._dev_issuers: dict[str, TokenVersion] = {}
        if config.dev_issuer is not None and config.env == "local":
            try:
                self._dev_keys = parse_jwks(config.dev_issuer.jwks)
            except JwksDocumentError as exc:
                raise InvalidSchemaError("dev issuer JWKS is invalid", reason="config") from exc
            self._dev_issuers = {config.dev_issuer.issuer: "2.0"}

    @property
    def config(self) -> JwtConfig:
        return self._config

    async def authenticate(self, authorization: str | None) -> VerifiedClaims:
        """Extract the bearer token from an ``Authorization`` header value and validate it."""
        return await self.validate(extract_bearer_token(authorization))

    async def validate(self, token: str | None) -> VerifiedClaims:
        if not token:
            raise _reject("missing_token", "bearer token required")
        _check_shape(token)
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError:
            raise _reject("malformed_token") from None
        alg = header.get("alg")
        if not isinstance(alg, str) or alg not in ALLOWED_ALGORITHMS:
            raise _reject("disallowed_algorithm")
        kid = header.get("kid")
        if not isinstance(kid, str) or not 0 < len(kid) <= MAX_KID_LENGTH:
            raise _reject("missing_kid")

        key, issuers, kind = await self._resolve(kid)
        if key.algorithm != alg:
            raise _reject("disallowed_algorithm")
        payload = self._verify_signature_and_audience(token, key, issuers)
        return self._claims(payload, issuers, kind)

    async def _resolve(
        self, kid: str
    ) -> tuple[SigningKey, dict[str, TokenVersion], Literal["entra", "dev"]]:
        dev_key = self._dev_keys.get(kid) if self._config.env == "local" else None
        if dev_key is not None:
            return dev_key, self._dev_issuers, "dev"
        return await self._jwks.get_key(kid), self._entra_issuers, "entra"

    def _verify_signature_and_audience(
        self, token: str, key: SigningKey, issuers: Mapping[str, TokenVersion]
    ) -> dict[str, Any]:
        try:
            # Lifetime is checked below against the injected clock, not PyJWT's wall clock.
            return jwt.decode(
                token,
                key.key,
                algorithms=[key.algorithm],
                audience=list(self._config.audiences),
                issuer=list(issuers),
                options={
                    "verify_signature": True,
                    "verify_aud": True,
                    "verify_iss": True,
                    "verify_exp": False,
                    "verify_nbf": False,
                    "verify_iat": False,
                    "require": _REQUIRED_CLAIMS,
                },
            )
        except jwt.InvalidSignatureError:
            raise _reject("invalid_signature") from None
        except jwt.InvalidAlgorithmError:
            raise _reject("disallowed_algorithm") from None
        except jwt.InvalidAudienceError:
            raise _reject("wrong_audience") from None
        except jwt.InvalidIssuerError:
            raise _reject("wrong_issuer") from None
        except jwt.MissingRequiredClaimError:
            raise _reject("missing_claim") from None
        except jwt.PyJWTError:
            raise _reject("malformed_token") from None

    def _claims(
        self,
        payload: Mapping[str, Any],
        issuers: Mapping[str, TokenVersion],
        kind: Literal["entra", "dev"],
    ) -> VerifiedClaims:
        issuer = payload["iss"]
        version = issuers.get(issuer)
        if version is None:  # PyJWT already enforced this; kept as a closed default
            raise _reject("wrong_issuer")
        tid = payload["tid"]
        if not isinstance(tid, str) or tid.lower() != self._config.tenant_id:
            raise _reject("wrong_tenant")
        if payload.get("ver") != version:
            raise _reject("token_version_mismatch")
        audience = payload["aud"]
        if not isinstance(audience, str):
            raise _reject("malformed_token")  # Entra issues exactly one audience

        exp = _epoch(payload["exp"])
        nbf = _epoch(payload["nbf"])
        iat = _epoch(payload["iat"])
        now = self._clock()
        leeway = self._config.leeway_seconds
        if now >= exp + leeway:
            raise _reject("token_expired")
        if nbf > now + leeway or iat > now + leeway:
            raise _reject("token_not_yet_valid")

        try:
            return VerifiedClaims(
                issuer_kind=kind,
                cloud=self._config.cloud,
                issuer=issuer,
                audience=audience,
                tenant_id=tid.lower(),
                object_id=_str_claim(payload, "oid"),
                subject=_str_claim(payload, "sub"),
                token_version=version,
                issued_at=_utc(iat),
                not_before=_utc(nbf),
                expires_at=_utc(exp),
                client_app_id=_optional_str(payload, "azp" if version == "2.0" else "appid"),
                identity_type=_identity_type(payload),
                roles=_str_list(payload, "roles"),
                scopes=_scopes(payload),
                groups=_str_list(payload, "groups"),
            )
        except ValidationError:
            raise _reject("malformed_token") from None


def _epoch(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise _reject("malformed_token")
    return float(value)


def _utc(epoch: float) -> datetime:
    try:
        return datetime.fromtimestamp(epoch, tz=UTC)
    except (OverflowError, OSError, ValueError):
        raise _reject("malformed_token") from None


def _str_claim(payload: Mapping[str, Any], name: str) -> str:
    value = payload.get(name)
    if not isinstance(value, str):
        raise _reject("malformed_token")
    return value


def _optional_str(payload: Mapping[str, Any], name: str) -> str | None:
    value = payload.get(name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise _reject("malformed_token")
    return value


def _str_list(payload: Mapping[str, Any], name: str) -> tuple[str, ...]:
    value = payload.get(name)
    if value is None:
        return ()
    if (
        not isinstance(value, list)
        or len(value) > MAX_LIST_CLAIM_ITEMS
        or not all(isinstance(item, str) for item in value)
    ):
        raise _reject("malformed_token")
    return tuple(value)


def _scopes(payload: Mapping[str, Any]) -> tuple[str, ...]:
    value = payload.get("scp")
    if value is None:
        return ()
    if not isinstance(value, str):
        raise _reject("malformed_token")
    return tuple(value.split())


def _identity_type(payload: Mapping[str, Any]) -> Literal["user", "app"] | None:
    value = payload.get("idtyp")
    if value in ("user", "app"):
        return value
    return None


def create_jwt_validator(
    config: JwtConfig,
    http_client: AsyncHttpClient,
    *,
    clock: Clock = time.time,
    cache_ttl_seconds: float = DEFAULT_CACHE_TTL_SECONDS,
    min_refresh_interval_seconds: float = DEFAULT_MIN_REFRESH_INTERVAL_SECONDS,
) -> JwtValidator:
    """Startup wiring: the JWKS URL always comes from ``config`` (its cloud and tenant)."""
    cache = JwksCache(
        HttpJwksFetcher(http_client, config.jwks_uri),
        clock=clock,
        ttl_seconds=cache_ttl_seconds,
        min_refresh_interval_seconds=min_refresh_interval_seconds,
    )
    return JwtValidator(config, cache, clock=clock)
