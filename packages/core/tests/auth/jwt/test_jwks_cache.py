"""JWKS cache: bounded, rate-limited refresh, fail closed on fetch failure with expired cache."""

from __future__ import annotations

import asyncio
import secrets
from typing import Any

import httpx
import pytest
import respx
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm
from neurosphere_core.auth.jwt import (
    HttpJwksFetcher,
    JwksCache,
    JwtConfig,
    create_jwt_validator,
    entra_jwks_uri,
    parse_jwks,
)
from neurosphere_core.auth.jwt.jwks import JwksDocumentError
from neurosphere_core.cloud import CloudName
from neurosphere_core.errors import DependencyTransientError, InvalidSchemaError, UnauthorizedError

from .jwt_helpers import (
    AUDIENCE,
    ENTRA_KID,
    TENANT,
    FakeClock,
    FakeFetcher,
    entra_claims,
    make_validator,
    signer,
)

URL = entra_jwks_uri(CloudName.COMMERCIAL, TENANT)
INTERVAL = 300
TTL = 3600


def _jwks(*kids: str) -> dict[str, Any]:
    return {"keys": [k for kid in kids for k in signer(kid).jwks()["keys"]]}


def _token(kid: str = ENTRA_KID) -> str:
    return signer(kid).sign(entra_claims())


async def test_keys_are_cached_within_ttl() -> None:
    validator, fetcher, clock = make_validator()
    for _ in range(5):
        await validator.validate(_token())
        clock.advance(60)
    assert fetcher.calls == 1


async def test_unknown_kid_refresh_is_rate_limited() -> None:
    validator, fetcher, clock = make_validator(interval=INTERVAL)
    await validator.validate(_token())
    assert fetcher.calls == 1
    clock.advance(INTERVAL)  # interval since the last fetch has elapsed: one refresh allowed
    for _ in range(50):
        with pytest.raises(UnauthorizedError) as info:
            await validator.validate(signer(f"rnd-{secrets.token_hex(4)}").sign(entra_claims()))
        assert info.value.reason == "unknown_kid"
    assert fetcher.calls == 2  # 50 random kids cost exactly one refresh
    clock.advance(INTERVAL - 1)
    with pytest.raises(UnauthorizedError):
        await validator.validate(_token("still-unknown"))
    assert fetcher.calls == 2
    clock.advance(1)
    with pytest.raises(UnauthorizedError):
        await validator.validate(_token("still-unknown"))
    assert fetcher.calls == 3


async def test_concurrent_unknown_kids_share_one_refresh() -> None:
    validator, fetcher, clock = make_validator()
    await validator.validate(_token())
    clock.advance(INTERVAL)
    results = await asyncio.gather(
        *(validator.validate(_token(f"burst-{i}")) for i in range(20)), return_exceptions=True
    )
    assert all(isinstance(r, UnauthorizedError) for r in results)
    assert fetcher.calls == 2


async def test_rotated_key_is_picked_up_after_interval() -> None:
    validator, fetcher, clock = make_validator()
    await validator.validate(_token())
    fetcher.document = _jwks(ENTRA_KID, "rotated-in")
    clock.advance(INTERVAL)
    claims = await validator.validate(_token("rotated-in"))
    assert claims.tenant_id == TENANT
    assert fetcher.calls == 2


async def test_expired_cache_refetches() -> None:
    validator, fetcher, clock = make_validator(ttl=TTL)
    await validator.validate(_token())
    clock.advance(TTL)
    await validator.validate(signer().sign(entra_claims(now=clock.now)))
    assert fetcher.calls == 2


async def test_fetch_failure_with_expired_cache_fails_closed() -> None:
    validator, fetcher, clock = make_validator(ttl=TTL)
    await validator.validate(_token())
    clock.advance(TTL)
    fetcher.error = DependencyTransientError("down", reason="jwks_unavailable")
    token = signer().sign(entra_claims(now=clock.now))  # valid token, previously known kid
    with pytest.raises(DependencyTransientError) as info:
        await validator.validate(token)
    assert info.value.status == 503
    assert fetcher.calls == 2
    # Within the interval no further fetch is attempted and stale keys are still not served.
    clock.advance(10)
    with pytest.raises(DependencyTransientError) as again:
        await validator.validate(token)
    assert again.value.retry_after_seconds == INTERVAL - 10
    assert fetcher.calls == 2
    # Recovery after the interval.
    fetcher.error = None
    clock.advance(INTERVAL)
    await validator.validate(signer().sign(entra_claims(now=clock.now)))
    assert fetcher.calls == 3


async def test_fetch_failure_with_fresh_cache_keeps_known_keys() -> None:
    validator, fetcher, clock = make_validator()
    await validator.validate(_token())
    clock.advance(INTERVAL)
    fetcher.error = DependencyTransientError("down", reason="jwks_unavailable")
    with pytest.raises(DependencyTransientError):
        await validator.validate(_token("new-kid"))  # unknown kid: cannot decide, fail closed
    await validator.validate(signer().sign(entra_claims(now=clock.now)))  # known kid still served
    with pytest.raises(UnauthorizedError):
        await validator.validate(_token("new-kid"))  # interval consumed: plain 401
    assert fetcher.calls == 2


def _rsa_jwk(kid: str, bits: int = 2048, **extra: Any) -> dict[str, Any]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=bits)
    jwk = RSAAlgorithm.to_jwk(key.public_key(), as_dict=True)
    assert isinstance(jwk, dict)
    return {**jwk, "kid": kid, **extra}


def _private_jwk(kid: str) -> dict[str, Any]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = RSAAlgorithm.to_jwk(key, as_dict=True)
    assert isinstance(jwk, dict)
    return {**jwk, "kid": kid}


GOOD = signer().jwks()["keys"][0]

INVALID_DOCUMENTS: list[tuple[str, Any]] = [
    ("not_object", ["keys"]),
    ("no_keys", {"kty": "RSA"}),
    ("keys_not_list", {"keys": {"a": 1}}),
    ("entry_not_object", {"keys": ["x"]}),
    ("missing_kid", {"keys": [{k: v for k, v in GOOD.items() if k != "kid"}]}),
    ("duplicate_kid", {"keys": [GOOD, GOOD]}),
    ("over_bound", {"keys": [{**GOOD, "kid": f"k{i}"} for i in range(33)]}),
    ("only_hmac", {"keys": [{"kty": "oct", "kid": "h", "k": "c2VjcmV0", "alg": "HS256"}]}),
    ("only_ec", {"keys": [{"kty": "EC", "kid": "e", "crv": "P-256", "x": "AA", "y": "AA"}]}),
    ("only_hs256_alg_on_rsa", {"keys": [{**GOOD, "alg": "HS256"}]}),
    ("only_rs512", {"keys": [{**GOOD, "alg": "RS512"}]}),
    ("only_encryption", {"keys": [{**GOOD, "use": "enc"}]}),
    ("only_private", {"keys": [_private_jwk("p")]}),
    ("only_small_rsa", {"keys": [_rsa_jwk("s", bits=1024)]}),
]


@pytest.mark.parametrize(("case", "doc"), INVALID_DOCUMENTS, ids=[c for c, _ in INVALID_DOCUMENTS])
def test_parse_rejects_unusable_documents(case: str, doc: Any) -> None:
    with pytest.raises(JwksDocumentError):
        parse_jwks(doc)


def test_parse_keeps_only_rs256_signing_keys() -> None:
    doc = {
        "keys": [
            GOOD,
            {"kty": "oct", "kid": "hmac", "k": "c2VjcmV0"},
            {**GOOD, "kid": "enc", "use": "enc"},
            {**_rsa_jwk("no-alg")},  # alg absent: pinned to RS256 from the key type
        ]
    }
    keys = parse_jwks(doc)
    assert set(keys) == {ENTRA_KID, "no-alg"}
    assert {k.algorithm for k in keys.values()} == {"RS256"}


@pytest.mark.parametrize(("case", "doc"), INVALID_DOCUMENTS, ids=[c for c, _ in INVALID_DOCUMENTS])
async def test_invalid_document_is_502_and_does_not_replace_keys(case: str, doc: Any) -> None:
    validator, fetcher, clock = make_validator()
    await validator.validate(_token())
    fetcher.document = doc
    clock.advance(INTERVAL)
    with pytest.raises(DependencyTransientError) as info:
        await validator.validate(_token("new-kid"))
    assert info.value.status == 502 and info.value.reason == "jwks_invalid", case
    await validator.validate(signer().sign(entra_claims(now=clock.now)))


def test_cache_rejects_ttl_shorter_than_interval() -> None:
    with pytest.raises(InvalidSchemaError):
        JwksCache(FakeFetcher(URL, {}), ttl_seconds=10, min_refresh_interval_seconds=60)
    with pytest.raises(InvalidSchemaError):
        JwksCache(FakeFetcher(URL, {}), ttl_seconds=10, min_refresh_interval_seconds=0)


# --- HTTP fetcher (respx; no network) ---------------------------------------------------------

HTTP_FAILURES: list[tuple[str, Any, int, str]] = [
    ("server_error", httpx.Response(500), 503, "jwks_unavailable"),
    ("throttled", httpx.Response(429), 503, "jwks_unavailable"),
    ("not_found", httpx.Response(404), 502, "jwks_unavailable"),
    (
        "redirect_not_followed",
        httpx.Response(302, headers={"location": "https://evil.example/k"}),
        502,
        "jwks_unavailable",
    ),
    ("not_json", httpx.Response(200, content=b"<html>"), 502, "jwks_invalid"),
    ("oversize", httpx.Response(200, content=b" " * (64 * 1024 + 1)), 502, "jwks_invalid"),
    ("timeout", httpx.ConnectTimeout("t"), 503, "jwks_unavailable"),
    ("refused", httpx.ConnectError("c"), 503, "jwks_unavailable"),
]


@pytest.mark.parametrize(
    ("case", "outcome", "status", "reason"), HTTP_FAILURES, ids=[c[0] for c in HTTP_FAILURES]
)
async def test_http_fetcher_failures_map_to_taxonomy(
    case: str, outcome: Any, status: int, reason: str
) -> None:
    with respx.mock(assert_all_called=True) as router:
        route = router.get(URL)
        if isinstance(outcome, Exception):
            route.side_effect = outcome
        else:
            route.return_value = outcome
        async with httpx.AsyncClient() as client:
            with pytest.raises(DependencyTransientError) as info:
                await HttpJwksFetcher(client, URL).fetch()
    assert info.value.status == status, case
    assert info.value.reason == reason, case
    assert "evil.example" not in str(info.value)


async def test_http_fetcher_requires_https() -> None:
    async with httpx.AsyncClient() as client:
        with pytest.raises(InvalidSchemaError):
            HttpJwksFetcher(client, "http://login.microsoftonline.com/x/keys")


async def test_end_to_end_with_httpx_client() -> None:
    clock = FakeClock()
    config = JwtConfig(
        env="prod", cloud=CloudName.COMMERCIAL, tenant_id=TENANT, audiences=(AUDIENCE,)
    )
    with respx.mock(assert_all_called=True) as router:
        route = router.get(URL).respond(200, json=signer().jwks())
        async with httpx.AsyncClient() as client:
            validator = create_jwt_validator(config, client, clock=clock)
            tenants = {(await validator.validate(_token())).tenant_id for _ in range(3)}
    assert tenants == {TENANT}
    assert route.call_count == 1


def _token_at(clock: FakeClock, kid: str = ENTRA_KID) -> str:
    return signer(kid).sign(entra_claims(now=clock.now))


AHEAD_START = TTL - 300  # the default refresh-ahead window opens 300 s before expiry


async def test_refresh_ahead_renews_before_expiry_so_there_is_no_gap() -> None:
    validator, fetcher, clock = make_validator(ttl=TTL, interval=INTERVAL)
    await validator.validate(_token_at(clock))
    assert fetcher.calls == 1

    clock.advance(AHEAD_START - 1)  # still outside the window
    await validator.validate(_token_at(clock))
    assert fetcher.calls == 1

    clock.advance(1)  # window opens: this request renews the key set
    await validator.validate(_token_at(clock))
    assert fetcher.calls == 2

    clock.advance(400)  # past the original expiry; the renewed set is still fresh
    await validator.validate(_token_at(clock))
    assert fetcher.calls == 2


async def test_failed_refresh_ahead_keeps_serving_cache_and_never_extends_expiry() -> None:
    validator, fetcher, clock = make_validator(ttl=TTL, interval=INTERVAL)
    await validator.validate(_token_at(clock))
    clock.advance(AHEAD_START)
    fetcher.error = DependencyTransientError("jwks down", reason="jwks_unavailable")

    await validator.validate(_token_at(clock))  # served from the unexpired cache
    assert fetcher.calls == 2
    clock.advance(INTERVAL - 1)
    await validator.validate(_token_at(clock))  # interval consumed by the failed attempt
    assert fetcher.calls == 2

    clock.advance(1)  # at the original expiry the cache is dead: fail closed, not stale
    with pytest.raises(DependencyTransientError):
        await validator.validate(_token_at(clock))


async def test_refresh_ahead_that_drops_a_key_makes_its_tokens_untrusted() -> None:
    validator, fetcher, clock = make_validator(ttl=TTL, interval=INTERVAL)
    await validator.validate(_token_at(clock))
    clock.advance(AHEAD_START)
    fetcher.document = _jwks("rotated-in")  # the old kid is gone from the issuer's set

    with pytest.raises(UnauthorizedError) as info:
        await validator.validate(_token_at(clock))
    assert info.value.reason == "unknown_kid"


def test_refresh_ahead_window_must_be_shorter_than_the_ttl() -> None:
    fetcher = FakeFetcher(URL, _jwks(ENTRA_KID))
    with pytest.raises(InvalidSchemaError):
        JwksCache(
            fetcher, ttl_seconds=600, min_refresh_interval_seconds=300, refresh_ahead_seconds=600
        )
