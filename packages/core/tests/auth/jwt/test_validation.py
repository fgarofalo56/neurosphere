"""Item 1 acceptance: every invalid token is 401 with a contract-valid reason (table-driven)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

import pytest
from neurosphere_core.auth.jwt import VerifiedClaims, extract_bearer_token
from neurosphere_core.auth.jwt.validator import MAX_TOKEN_LENGTH
from neurosphere_core.cloud import CloudName
from neurosphere_core.errors import UnauthorizedError
from pydantic import ValidationError

from .jwt_helpers import (
    AUDIENCE,
    ENTRA_KID,
    OBJECT_ID,
    OTHER_TENANT,
    T0,
    TENANT,
    entra_claims,
    hs256_with_public_key,
    make_validator,
    signer,
    unsigned_token,
)

LEEWAY = 60


def _sign(**overrides: object) -> str:
    return signer().sign(entra_claims(**overrides))  # pyright: ignore[reportArgumentType]


# (case id, token builder, expected reason). Each must yield UnauthorizedError (401).
REJECTIONS: list[tuple[str, Callable[[], str | None], str]] = [
    ("none", lambda: None, "missing_token"),
    ("empty", lambda: "", "missing_token"),
    ("one_segment", lambda: "abc", "malformed_token"),
    ("two_segments", lambda: "abc.def", "malformed_token"),
    ("four_segments", lambda: "a.b.c.d", "malformed_token"),
    ("bad_charset", lambda: "a$.b.c", "malformed_token"),
    ("header_not_json", lambda: "bm90LWpzb24.e30.c2ln", "malformed_token"),
    ("oversize", lambda: "a" * MAX_TOKEN_LENGTH + ".b.c", "malformed_token"),
    ("wrong_audience", lambda: _sign(aud="api://some-other-api"), "wrong_audience"),
    ("aud_list", lambda: _sign(aud=[AUDIENCE, "api://x"]), "malformed_token"),
    (
        "issuer_other_tenant",
        lambda: _sign(iss=f"https://login.microsoftonline.com/{OTHER_TENANT}/v2.0"),
        "wrong_issuer",
    ),
    (
        "issuer_common",
        lambda: _sign(iss="https://login.microsoftonline.com/common/v2.0"),
        "wrong_issuer",
    ),
    (
        "issuer_template",
        lambda: _sign(iss="https://login.microsoftonline.com/{tenantid}/v2.0"),
        "wrong_issuer",
    ),
    (
        "issuer_lookalike",
        lambda: _sign(iss=f"https://login.microsoftonline.com.evil.example/{TENANT}/v2.0"),
        "wrong_issuer",
    ),
    (
        "issuer_trailing_slash",
        lambda: _sign(iss=f"https://login.microsoftonline.com/{TENANT}/v2.0/"),
        "wrong_issuer",
    ),
    ("wrong_tenant", lambda: _sign(tid=OTHER_TENANT), "wrong_tenant"),
    ("version_mismatch", lambda: _sign(ver="1.0"), "token_version_mismatch"),
    ("expired", lambda: _sign(exp=int(T0) - LEEWAY - 1), "token_expired"),
    ("expired_at_boundary", lambda: _sign(exp=int(T0) - LEEWAY), "token_expired"),
    ("not_yet_valid", lambda: _sign(nbf=int(T0) + LEEWAY + 1), "token_not_yet_valid"),
    ("issued_in_future", lambda: _sign(iat=int(T0) + LEEWAY + 1), "token_not_yet_valid"),
    ("exp_string", lambda: _sign(exp="never"), "malformed_token"),
    ("exp_bool", lambda: _sign(exp=True), "malformed_token"),
    ("roles_not_list", lambda: _sign(roles="Admin"), "malformed_token"),
    ("roles_non_string", lambda: _sign(roles=["Admin", 7]), "malformed_token"),
    ("missing_oid", lambda: _sign(oid=None), "missing_claim"),
    ("missing_tid", lambda: _sign(tid=None), "missing_claim"),
    ("missing_exp", lambda: _sign(exp=None), "missing_claim"),
    ("missing_nbf", lambda: _sign(nbf=None), "missing_claim"),
    ("unknown_kid", lambda: signer("rotated-away").sign(entra_claims()), "unknown_kid"),
    (
        "missing_kid",
        lambda: unsigned_token({"alg": "RS256"}, entra_claims(), "c2ln"),
        "missing_kid",
    ),
    (
        "alg_none",
        lambda: unsigned_token({"alg": "none", "kid": ENTRA_KID}, entra_claims()),
        "disallowed_algorithm",
    ),
    (
        "alg_None_case",
        lambda: unsigned_token({"alg": "None", "kid": ENTRA_KID}, entra_claims()),
        "disallowed_algorithm",
    ),
    ("hs256_public_key", lambda: hs256_with_public_key(entra_claims()), "disallowed_algorithm"),
    (
        "rs512_header",
        lambda: unsigned_token({"alg": "RS512", "kid": ENTRA_KID}, entra_claims(), "c2ln"),
        "disallowed_algorithm",
    ),
    (
        "alg_missing",
        lambda: unsigned_token({"kid": ENTRA_KID}, entra_claims(), "c2ln"),
        "disallowed_algorithm",
    ),
    (
        "forged_signature",
        lambda: signer("attacker").sign(entra_claims(), headers={"kid": ENTRA_KID}),
        "invalid_signature",
    ),
    ("stripped_signature", lambda: _sign().rsplit(".", 1)[0] + ".", "invalid_signature"),
]


@pytest.mark.parametrize(("case", "build", "reason"), REJECTIONS, ids=[r[0] for r in REJECTIONS])
async def test_invalid_tokens_are_401(
    case: str, build: Callable[[], str | None], reason: str
) -> None:
    validator, _, _ = make_validator()
    token = build()
    with pytest.raises(UnauthorizedError) as info:
        await validator.validate(token)
    err = info.value
    assert err.status == 401, case
    assert err.reason == reason, case
    # Reason renders into the contract body (snake_case pattern) and the body never echoes it.
    body = err.to_problem_details("corr-1").model_dump_json()
    if token:
        assert token not in body and token not in str(err)


async def test_unknown_kid_is_401_only_after_one_refresh() -> None:
    validator, fetcher, _ = make_validator()
    with pytest.raises(UnauthorizedError):
        await validator.validate(signer("rotated-away").sign(entra_claims()))
    assert fetcher.calls == 1


@pytest.mark.parametrize("version", ["2.0", "1.0"])
async def test_valid_token_yields_typed_claims(version: str) -> None:
    validator, _, _ = make_validator()
    token = signer().sign(
        entra_claims(version=version, upn="person@example.test", email="person@example.test")
    )
    claims = await validator.validate(token)
    assert isinstance(claims, VerifiedClaims)
    assert claims.issuer_kind == "entra"
    assert claims.cloud is CloudName.COMMERCIAL
    assert claims.tenant_id == TENANT
    assert claims.object_id == OBJECT_ID
    assert claims.audience == AUDIENCE
    assert claims.token_version == version
    assert claims.roles == ("Analyst",)
    assert claims.scopes == ("catalog.read", "reports.read")
    assert claims.client_app_id == "c0ffee00-0000-4000-8000-000000000001"
    assert claims.expires_at == datetime.fromtimestamp(T0 + 3600, tz=UTC)
    dumped = claims.model_dump_json()
    assert "person@example.test" not in dumped  # name/UPN/email claims are not carried


async def test_leeway_boundaries_accept() -> None:
    validator, _, _ = make_validator()
    await validator.validate(_sign(exp=int(T0) - LEEWAY + 1))
    await validator.validate(_sign(nbf=int(T0) + LEEWAY, iat=int(T0) + LEEWAY))


async def test_tenant_claim_case_insensitive() -> None:
    validator, _, _ = make_validator()
    claims = await validator.validate(_sign(tid=TENANT.upper()))
    assert claims.tenant_id == TENANT


async def test_expiry_follows_injected_clock() -> None:
    validator, _, clock = make_validator()
    token = _sign()
    await validator.validate(token)
    clock.advance(3600 + LEEWAY)
    with pytest.raises(UnauthorizedError) as info:
        await validator.validate(token)
    assert info.value.reason == "token_expired"


HEADERS: list[tuple[str | None, str]] = [
    (None, "missing_token"),
    ("", "missing_token"),
    ("   ", "missing_token"),
    ("Bearer", "missing_token"),
    ("Bearer   ", "missing_token"),
    ("Basic dXNlcjpwYXNz", "invalid_scheme"),
    ("Token abc.def.ghi", "invalid_scheme"),
    ("Bearer abc", "malformed_token"),
    ("Bearer a.b.c extra", "malformed_token"),
]


@pytest.mark.parametrize(("header", "reason"), HEADERS)
def test_extract_bearer_token_rejections(header: str | None, reason: str) -> None:
    with pytest.raises(UnauthorizedError) as info:
        extract_bearer_token(header)
    assert info.value.reason == reason
    assert info.value.status == 401


@pytest.mark.parametrize("scheme", ["Bearer", "bearer", "BEARER"])
async def test_authenticate_accepts_bearer_header(scheme: str) -> None:
    validator, _, _ = make_validator()
    claims = await validator.authenticate(f"{scheme} {_sign()}")
    assert claims.object_id == OBJECT_ID


async def test_authenticate_without_header_is_401() -> None:
    validator, fetcher, _ = make_validator()
    with pytest.raises(UnauthorizedError):
        await validator.authenticate(None)
    assert fetcher.calls == 0  # rejected before any key lookup


async def test_verified_claims_is_frozen_and_closed() -> None:
    validator, _, _ = make_validator()
    claims = await validator.validate(_sign())
    with pytest.raises(ValidationError):
        claims.object_id = "other"  # pyright: ignore[reportAttributeAccessIssue]
    with pytest.raises(ValidationError):
        VerifiedClaims.model_validate({**claims.model_dump(), "is_admin": True})
