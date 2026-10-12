"""Dev issuer (PRP-06 C3): accepted only with NS_ENV=local; configured elsewhere, startup fails."""

from __future__ import annotations

import pytest
from neurosphere_core.auth.jwt import DevIssuer, DevIssuerTrust, JwtConfig, JwtValidator
from neurosphere_core.auth.jwt.config import dev_issuer_for
from neurosphere_core.cloud import CloudName
from neurosphere_core.errors import InvalidSchemaError, UnauthorizedError
from pydantic import ValidationError

from .jwt_helpers import (
    AUDIENCE,
    OBJECT_ID,
    OTHER_TENANT,
    T0,
    TENANT,
    entra_claims,
    make_validator,
    settings,
    signer,
)

NON_LOCAL = ["dev", "test", "staging", "prod"]


def _dev() -> DevIssuer:
    return signer("dev-local-kid")


def _dev_token(**extra: object) -> str:
    return _dev().mint(audience=AUDIENCE, object_id=OBJECT_ID, now=T0, extra=extra)


async def test_dev_token_accepted_when_local() -> None:
    validator, fetcher, _ = make_validator(env="local", dev=_dev())
    claims = await validator.validate(_dev_token())
    assert claims.issuer_kind == "dev"
    assert claims.issuer == dev_issuer_for(TENANT)
    assert fetcher.calls == 0  # dev keys are local; the cloud JWKS is not consulted


@pytest.mark.parametrize("env", NON_LOCAL)
async def test_dev_token_rejected_outside_local(env: str) -> None:
    validator, fetcher, _ = make_validator(env=env)
    with pytest.raises(UnauthorizedError) as info:
        await validator.validate(_dev_token())
    assert info.value.status == 401
    assert info.value.reason == "unknown_kid"
    assert fetcher.calls == 1  # one JWKS refresh, then 401


@pytest.mark.parametrize("env", NON_LOCAL)
def test_startup_fails_when_dev_issuer_configured_outside_local(env: str) -> None:
    trust = _dev().trust()
    with pytest.raises(InvalidSchemaError) as info:
        JwtConfig.from_settings(
            settings(env), tenant_id=TENANT, audiences=[AUDIENCE], dev_issuer=trust
        )
    assert info.value.reason == "config"
    assert info.value.status == 422
    with pytest.raises(ValidationError):
        JwtConfig(
            env=env,  # pyright: ignore[reportArgumentType]
            cloud=CloudName.COMMERCIAL,
            tenant_id=TENANT,
            audiences=(AUDIENCE,),
            dev_issuer=trust,
        )


@pytest.mark.parametrize("env", NON_LOCAL)
def test_dev_issuer_cannot_be_created_outside_local(env: str) -> None:
    with pytest.raises(InvalidSchemaError) as info:
        DevIssuer(settings(env), tenant_id=TENANT)
    assert info.value.reason == "config"


async def test_bypassing_config_validation_still_ignores_dev_keys() -> None:
    validator, _, _ = make_validator(env="local", dev=_dev())
    tampered = validator.config.model_copy(update={"env": "prod"})  # skips validators
    prod_validator = JwtValidator(
        tampered,
        validator._jwks,  # pyright: ignore[reportPrivateUsage]
        clock=lambda: T0,
    )
    with pytest.raises(UnauthorizedError):
        await prod_validator.validate(_dev_token())


async def test_dev_key_cannot_mint_entra_issuer() -> None:
    validator, _, _ = make_validator(env="local", dev=_dev())
    forged = _dev().sign(entra_claims())  # Entra issuer string, dev key
    with pytest.raises(UnauthorizedError) as info:
        await validator.validate(forged)
    assert info.value.reason == "wrong_issuer"


async def test_entra_key_cannot_mint_dev_issuer() -> None:
    validator, _, _ = make_validator(env="local", dev=_dev())
    forged = signer().sign(entra_claims(iss=dev_issuer_for(TENANT)))
    with pytest.raises(UnauthorizedError) as info:
        await validator.validate(forged)
    assert info.value.reason == "wrong_issuer"


async def test_dev_token_still_fully_validated() -> None:
    validator, _, _ = make_validator(env="local", dev=_dev())
    cases = {
        "wrong_audience": _dev_token(aud="api://other"),
        "wrong_tenant": _dev_token(tid=OTHER_TENANT),
        "token_expired": _dev_token(exp=int(T0) - 3600),
    }
    for reason, token in cases.items():
        with pytest.raises(UnauthorizedError) as info:
            await validator.validate(token)
        assert info.value.reason == reason


def test_dev_trust_bound_to_tenant_and_dev_host() -> None:
    other = DevIssuer(settings("local"), tenant_id=OTHER_TENANT)
    with pytest.raises(InvalidSchemaError):
        JwtConfig.from_settings(
            settings("local"), tenant_id=TENANT, audiences=[AUDIENCE], dev_issuer=other.trust()
        )
    with pytest.raises(ValidationError):
        DevIssuerTrust(issuer=f"https://login.microsoftonline.com/{TENANT}/v2.0", jwks={})


def test_dev_jwks_has_no_private_material() -> None:
    (key,) = _dev().jwks()["keys"]
    assert {"d", "p", "q", "dp", "dq", "qi"}.isdisjoint(key)
    assert key["alg"] == "RS256" and key["use"] == "sig"
