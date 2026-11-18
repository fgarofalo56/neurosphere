"""PRP-138 item 2: the validator flags Entra group overage and then never relies on ``groups``.

Tokens are signed by a local RSA key whose JWKS is served by an in-memory fetcher; no tenant,
credential, network or Microsoft Graph call is involved.
"""

from __future__ import annotations

from functools import cache
from typing import Any

import pytest
from neurosphere_core.auth.jwt import (
    DevIssuer,
    JwksCache,
    JwtConfig,
    JwtValidator,
    VerifiedClaims,
    entra_issuers,
    entra_jwks_uri,
)
from neurosphere_core.cloud import CloudName, Settings

TENANT = "0f1e2d3c-4b5a-4968-8776-a5b4c3d2e1f0"
AUDIENCE = "api://neurosphere-test-api"
T0 = 1_800_000_000.0
KID = "overage-kid-1"
GROUP_A = "11111111-1111-4111-8111-111111111111"
GROUP_B = "22222222-2222-4222-8222-222222222222"


class _Fetcher:
    def __init__(self, url: str, document: Any) -> None:
        self._url = url
        self._document = document

    @property
    def url(self) -> str:
        return self._url

    async def fetch(self) -> Any:
        return self._document


@cache
def _signer() -> DevIssuer:
    settings = Settings(env="local", cloud=CloudName.COMMERCIAL)  # pyright: ignore[reportArgumentType]
    return DevIssuer(settings, tenant_id=TENANT, kid=KID)


def _validator() -> JwtValidator:
    config = JwtConfig(
        env="prod",  # pyright: ignore[reportArgumentType]
        cloud=CloudName.COMMERCIAL,
        tenant_id=TENANT,
        audiences=(AUDIENCE,),
    )
    fetcher = _Fetcher(entra_jwks_uri(CloudName.COMMERCIAL, TENANT), _signer().jwks())
    clock = lambda: T0  # noqa: E731
    jwks = JwksCache(fetcher, clock=clock, ttl_seconds=3600, min_refresh_interval_seconds=300)
    return JwtValidator(config, jwks, clock=clock)


def _claims(**overrides: Any) -> dict[str, Any]:
    issuer = next(i for i, v in entra_issuers(CloudName.COMMERCIAL, TENANT).items() if v == "2.0")
    claims: dict[str, Any] = {
        "iss": issuer,
        "aud": AUDIENCE,
        "tid": TENANT,
        "oid": "6c1d2e3f-4a5b-4c6d-8e7f-90a1b2c3d4e5",
        "sub": "pairwise-subject-1",
        "ver": "2.0",
        "iat": int(T0),
        "nbf": int(T0),
        "exp": int(T0) + 3600,
        "roles": ["admin"],
        "scp": "catalog.read",
        "azp": "c0ffee00-0000-4000-8000-000000000001",
    }
    claims.update(overrides)
    return claims


async def _validate(**overrides: Any) -> VerifiedClaims:
    token = _signer().sign(_claims(**overrides))  # pyright: ignore[reportArgumentType]
    return await _validator().validate(token)


CLAIM_NAMES = {"groups": "src1"}
CLAIM_SOURCES = {"src1": {"endpoint": "https://graph.microsoft.com/v1.0/users/x/getMemberObjects"}}

OVERAGE_SHAPES: list[tuple[str, dict[str, Any]]] = [
    ("hasgroups_true", {"hasgroups": True}),
    ("claim_names_groups", {"_claim_names": CLAIM_NAMES, "_claim_sources": CLAIM_SOURCES}),
    ("claim_names_without_sources", {"_claim_names": CLAIM_NAMES}),
    ("both", {"hasgroups": True, "_claim_names": CLAIM_NAMES, "_claim_sources": CLAIM_SOURCES}),
]


@pytest.mark.parametrize(
    "extra", [shape for _, shape in OVERAGE_SHAPES], ids=[i for i, _ in OVERAGE_SHAPES]
)
async def test_overage_indicator_sets_flag_and_empties_groups(extra: dict[str, Any]) -> None:
    claims = await _validate(**extra)
    assert claims.groups_overage is True
    assert claims.groups == ()
    assert claims.roles == ("admin",)  # app roles are unaffected by group overage


@pytest.mark.parametrize(
    "extra", [shape for _, shape in OVERAGE_SHAPES], ids=[i for i, _ in OVERAGE_SHAPES]
)
async def test_overage_token_group_values_are_never_relied_on(extra: dict[str, Any]) -> None:
    claims = await _validate(groups=[GROUP_A, GROUP_B], **extra)
    assert claims.groups_overage is True
    assert claims.groups == ()


IGNORED_SHAPES: list[tuple[str, dict[str, Any]]] = [
    ("hasgroups_string_true", {"hasgroups": "true"}),
    ("hasgroups_false", {"hasgroups": False}),
    ("hasgroups_one", {"hasgroups": 1}),
    ("hasgroups_null", {"hasgroups": None}),
    ("claim_names_list", {"_claim_names": ["groups"]}),
    ("claim_names_string", {"_claim_names": "groups"}),
    ("claim_names_without_groups", {"_claim_names": {"roles": "src1"}}),
    ("claim_names_empty_object", {"_claim_names": {}}),
    ("claim_sources_only", {"_claim_sources": CLAIM_SOURCES}),
]


@pytest.mark.parametrize(
    "extra", [shape for _, shape in IGNORED_SHAPES], ids=[i for i, _ in IGNORED_SHAPES]
)
async def test_other_shapes_are_ignored(extra: dict[str, Any]) -> None:
    claims = await _validate(groups=[GROUP_A], **extra)
    assert claims.groups_overage is False
    assert claims.groups == (GROUP_A,)


async def test_normal_token_with_groups_is_unchanged() -> None:
    claims = await _validate(groups=[GROUP_A, GROUP_B])
    assert claims.groups_overage is False
    assert claims.groups == (GROUP_A, GROUP_B)
    assert claims.roles == ("admin",)


async def test_token_without_groups_has_no_overage() -> None:
    claims = await _validate()
    assert claims.groups_overage is False
    assert claims.groups == ()


def test_field_defaults_to_false_for_existing_constructors() -> None:
    assert VerifiedClaims.model_fields["groups_overage"].default is False
