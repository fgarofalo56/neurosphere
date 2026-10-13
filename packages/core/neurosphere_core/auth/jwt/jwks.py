"""JWKS parsing, fetching and caching for token signature keys (PRP-06 item 1).

Rules (PRP-06 gotchas, RFC 8725):

* Only RSA signing keys of at least 2048 bits whose ``alg`` is absent or allowlisted are kept;
  the verification algorithm is pinned from the key, never taken from a token header.
* A JWKS document is bounded (``max_keys``, ``max_bytes``); oversize or malformed documents are
  rejected as an invalid upstream response and never partially trusted.
* An unknown ``kid`` triggers at most one fetch per ``min_refresh_interval_seconds`` across all
  kids, so random ``kid`` values cannot drive refresh traffic (refresh-driven DoS).
* When the cached set has expired and a fetch fails, validation fails closed with
  ``dependency_transient``; expiry is never extended on error and stale keys are not served.

HTTP goes through an injected client (``httpx.AsyncClient`` satisfies ``AsyncHttpClient``), so
this module imports no HTTP library and tests drive it with respx.
"""

from __future__ import annotations

import asyncio
import json
import math
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Final, Protocol

from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from jwt.algorithms import RSAAlgorithm
from jwt.exceptions import PyJWTError

from neurosphere_core.auth.jwt.config import ALLOWED_ALGORITHMS
from neurosphere_core.errors import DependencyTransientError, InvalidSchemaError, UnauthorizedError

Clock = Callable[[], float]
"""Returns POSIX seconds. Injected everywhere time matters; tests pass a fake clock."""

DEFAULT_CACHE_TTL_SECONDS: Final = 3600
DEFAULT_MIN_REFRESH_INTERVAL_SECONDS: Final = 300
#: Start renewing the key set this long before it expires (still serving the cache meanwhile).
DEFAULT_REFRESH_AHEAD_SECONDS: Final = 300
DEFAULT_MAX_KEYS: Final = 32
DEFAULT_MAX_JWKS_BYTES: Final = 64 * 1024
DEFAULT_FETCH_TIMEOUT_SECONDS: Final = 5.0
MIN_RSA_KEY_BITS: Final = 2048
MAX_KID_LENGTH: Final = 128

_PRIVATE_MEMBERS: Final = frozenset({"d", "p", "q", "dp", "dq", "qi", "oth", "k"})


class JwksDocumentError(Exception):
    """A JWKS document is unusable. Internal; callers map it to the taxonomy."""


@dataclass(frozen=True, slots=True)
class SigningKey:
    kid: str
    algorithm: str
    key: RSAPublicKey


def parse_jwks(document: Any, *, max_keys: int = DEFAULT_MAX_KEYS) -> dict[str, SigningKey]:
    """Return usable signing keys by ``kid``. Raises ``JwksDocumentError`` on any document fault."""
    if not isinstance(document, Mapping):
        raise JwksDocumentError("JWKS is not an object")
    entries = document.get("keys")
    if not isinstance(entries, list):
        raise JwksDocumentError("JWKS has no keys array")
    if len(entries) > max_keys:
        raise JwksDocumentError("JWKS exceeds the key bound")
    keys: dict[str, SigningKey] = {}
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise JwksDocumentError("JWKS key is not an object")
        kid = entry.get("kid")
        if not isinstance(kid, str) or not 0 < len(kid) <= MAX_KID_LENGTH:
            raise JwksDocumentError("JWKS key has no usable kid")
        if kid in keys:
            raise JwksDocumentError("JWKS has a duplicate kid")
        parsed = _signing_key(kid, entry)
        if parsed is not None:
            keys[kid] = parsed
    if not keys:
        raise JwksDocumentError("JWKS has no usable signing key")
    return keys


def _signing_key(kid: str, entry: Mapping[str, Any]) -> SigningKey | None:
    """One JWK to a pinned public key, or ``None`` when the key is not for RS256 signatures."""
    if entry.get("kty") != "RSA" or entry.get("use", "sig") != "sig":
        return None
    if _PRIVATE_MEMBERS & set(entry):
        return None  # never load private material from a JWKS
    algorithm = entry.get("alg", "RS256")
    if algorithm not in ALLOWED_ALGORITHMS:
        return None
    try:
        key = RSAAlgorithm.from_jwk(dict(entry))
    except (PyJWTError, ValueError, TypeError, KeyError):
        return None
    if not isinstance(key, RSAPublicKey) or key.key_size < MIN_RSA_KEY_BITS:
        return None
    return SigningKey(kid=kid, algorithm=algorithm, key=key)


class HttpResponse(Protocol):
    @property
    def status_code(self) -> int: ...

    @property
    def content(self) -> bytes: ...


class AsyncHttpClient(Protocol):
    """The subset of ``httpx.AsyncClient`` used here."""

    # The keyword mirrors httpx's own signature; the caller cannot rename it.
    async def get(
        self,
        url: str,
        *,
        timeout: float,  # noqa: ASYNC109
        follow_redirects: bool,
    ) -> HttpResponse: ...


class JwksFetcher(Protocol):
    @property
    def url(self) -> str: ...

    async def fetch(self) -> Any:
        """Return the decoded JWKS document or raise ``DependencyTransientError``."""
        ...


class HttpJwksFetcher:
    """Fetches one fixed HTTPS JWKS URL. No redirects; size-bounded; taxonomy errors only."""

    def __init__(
        self,
        client: AsyncHttpClient,
        url: str,
        *,
        timeout_seconds: float = DEFAULT_FETCH_TIMEOUT_SECONDS,
        max_bytes: int = DEFAULT_MAX_JWKS_BYTES,
    ) -> None:
        if not url.startswith("https://"):
            raise InvalidSchemaError("JWKS URL must use https", reason="config")
        self._client = client
        self._url = url
        self._timeout = timeout_seconds
        self._max_bytes = max_bytes

    @property
    def url(self) -> str:
        return self._url

    async def fetch(self) -> Any:
        try:
            response = await self._client.get(
                self._url, timeout=self._timeout, follow_redirects=False
            )
        except Exception as exc:  # any transport failure is infrastructure, never an allow
            raise DependencyTransientError(
                "signing keys unavailable", reason="jwks_unavailable"
            ) from exc
        status = response.status_code
        if status != 200:
            transient = status in (408, 429) or status >= 500
            raise DependencyTransientError(
                "signing keys unavailable",
                reason="jwks_unavailable",
                upstream_invalid=not transient,
            )
        body = response.content
        if len(body) > self._max_bytes:
            raise DependencyTransientError(
                "signing keys response invalid", reason="jwks_invalid", upstream_invalid=True
            )
        try:
            return json.loads(body)
        except ValueError as exc:
            raise DependencyTransientError(
                "signing keys response invalid", reason="jwks_invalid", upstream_invalid=True
            ) from exc


class JwksCache:
    """Bounded, rate-limited cache of one issuer's signing keys."""

    def __init__(
        self,
        fetcher: JwksFetcher,
        *,
        clock: Clock = time.time,
        ttl_seconds: float = DEFAULT_CACHE_TTL_SECONDS,
        min_refresh_interval_seconds: float = DEFAULT_MIN_REFRESH_INTERVAL_SECONDS,
        max_keys: int = DEFAULT_MAX_KEYS,
        refresh_ahead_seconds: float = DEFAULT_REFRESH_AHEAD_SECONDS,
    ) -> None:
        if min_refresh_interval_seconds <= 0 or ttl_seconds < min_refresh_interval_seconds:
            raise InvalidSchemaError(
                "JWKS ttl must be at least the minimum refresh interval (> 0)", reason="config"
            )
        if not 0 <= refresh_ahead_seconds < ttl_seconds:
            raise InvalidSchemaError(
                "JWKS refresh-ahead window must be in [0, ttl)", reason="config"
            )
        self._refresh_ahead = refresh_ahead_seconds
        self._fetcher = fetcher
        self._clock = clock
        self._ttl = ttl_seconds
        self._min_refresh = min_refresh_interval_seconds
        self._max_keys = max_keys
        self._keys: dict[str, SigningKey] = {}
        self._expires_at = -math.inf
        self._last_attempt = -math.inf
        self._lock = asyncio.Lock()

    @property
    def source_url(self) -> str:
        return self._fetcher.url

    async def get_key(self, kid: str) -> SigningKey:
        """Return the key for ``kid``; ``unauthorized`` if untrusted, ``dependency_transient``
        if the key set cannot be established."""
        key = self._fresh_key(kid)
        if key is not None:
            if self._clock() >= self._expires_at - self._refresh_ahead:
                return await self._refresh_ahead_of_expiry(kid, key)
            return key
        async with self._lock:
            key = self._fresh_key(kid)  # another task may have refreshed while we waited
            if key is not None:
                return key
            now = self._clock()
            fresh = now < self._expires_at
            wait = self._last_attempt + self._min_refresh - now
            if wait > 0:
                if not fresh:
                    raise DependencyTransientError(
                        "signing keys unavailable",
                        reason="jwks_unavailable",
                        retry_after_seconds=max(1, math.ceil(wait)),
                    )
                raise UnauthorizedError("invalid bearer token", reason="unknown_kid")
            await self._refresh(now)
            key = self._keys.get(kid)
            if key is None:
                raise UnauthorizedError("invalid bearer token", reason="unknown_kid")
            return key

    async def _refresh_ahead_of_expiry(self, kid: str, key: SigningKey) -> SigningKey:
        """Near expiry, try to renew the key set while the cached one is still valid.

        A failed attempt keeps serving the unexpired cache (and consumes the refresh interval, so
        a broken endpoint is not hammered); expiry is never extended. A successful refresh that no
        longer lists ``kid`` means the key was withdrawn, so the token is untrusted.
        """
        if self._lock.locked():  # another task is already renewing; do not queue behind it
            return key
        async with self._lock:
            now = self._clock()
            if now >= self._expires_at or now - self._last_attempt < self._min_refresh:
                return self._fresh_key(kid) or key
            try:
                await self._refresh(now)
            except DependencyTransientError:
                return key
            fresh = self._keys.get(kid)
            if fresh is None:
                raise UnauthorizedError("invalid bearer token", reason="unknown_kid")
            return fresh

    def _fresh_key(self, kid: str) -> SigningKey | None:
        if self._clock() < self._expires_at:
            return self._keys.get(kid)
        return None

    async def _refresh(self, now: float) -> None:
        self._last_attempt = now  # failed attempts consume the interval too
        document = await self._fetcher.fetch()
        try:
            keys = parse_jwks(document, max_keys=self._max_keys)
        except JwksDocumentError as exc:
            raise DependencyTransientError(
                "signing keys response invalid", reason="jwks_invalid", upstream_invalid=True
            ) from exc
        self._keys = keys
        self._expires_at = now + self._ttl
