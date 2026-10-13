"""Cloud isolation: a token from one cloud's authority never validates in the other cloud, and a
deployment never fetches keys from (or falls back to) the other cloud's authority."""

from __future__ import annotations

import httpx
import pytest
import respx
from neurosphere_core.auth.jwt import (
    JwksCache,
    JwtConfig,
    JwtValidator,
    create_jwt_validator,
    entra_issuers,
    entra_jwks_uri,
)
from neurosphere_core.cloud import CloudName
from neurosphere_core.errors import DependencyTransientError, InvalidSchemaError, UnauthorizedError

from .jwt_helpers import (
    AUDIENCE,
    TENANT,
    FakeClock,
    FakeFetcher,
    entra_claims,
    make_validator,
    settings,
    signer,
)

COM = CloudName.COMMERCIAL
GOV = CloudName.GOVERNMENT

# (token cloud, deployment cloud). The same signing key is served to both deployments, which is
# the worst case: rejection must come from the issuer check, not from a key miss.
CROSS = [(COM, GOV), (GOV, COM)]


@pytest.mark.parametrize("version", ["2.0", "1.0"])
@pytest.mark.parametrize(("token_cloud", "deploy_cloud"), CROSS, ids=["com->gov", "gov->com"])
async def test_cross_cloud_token_is_401(
    token_cloud: CloudName, deploy_cloud: CloudName, version: str
) -> None:
    validator, _, _ = make_validator(deploy_cloud)
    token = signer().sign(entra_claims(token_cloud, version=version))
    with pytest.raises(UnauthorizedError) as info:
        await validator.validate(token)
    assert info.value.status == 401
    assert info.value.reason == "wrong_issuer"


@pytest.mark.parametrize("cloud", [COM, GOV])
@pytest.mark.parametrize("version", ["2.0", "1.0"])
async def test_same_cloud_token_is_accepted(cloud: CloudName, version: str) -> None:
    validator, _, _ = make_validator(cloud)
    claims = await validator.validate(signer().sign(entra_claims(cloud, version=version)))
    assert claims.cloud is cloud


async def test_commercial_v1_sts_issuer_rejected_by_government() -> None:
    # Government /common metadata also advertises sts.windows.net; it is deliberately not
    # allowlisted for Government so a Commercial v1 issuer cannot cross over.
    validator, _, _ = make_validator(GOV)
    token = signer().sign(
        entra_claims(GOV, version="1.0", iss=f"https://sts.windows.net/{TENANT}/")
    )
    with pytest.raises(UnauthorizedError) as info:
        await validator.validate(token)
    assert info.value.reason == "wrong_issuer"


def test_issuer_and_jwks_tables_stay_in_their_cloud() -> None:
    com_hosts = ("login.microsoftonline.com", "sts.windows.net")
    gov_hosts = ("login.microsoftonline.us", "sts.usgovcloudapi.net")
    for issuer in entra_issuers(COM, TENANT):
        assert issuer.startswith(tuple(f"https://{h}/{TENANT}/" for h in com_hosts))
        assert not any(h in issuer for h in gov_hosts)
    for issuer in entra_issuers(GOV, TENANT):
        assert issuer.startswith(tuple(f"https://{h}/{TENANT}/" for h in gov_hosts))
        assert not any(h in issuer for h in com_hosts)
    assert entra_jwks_uri(COM, TENANT).startswith("https://login.microsoftonline.com/")
    assert entra_jwks_uri(GOV, TENANT).startswith("https://login.microsoftonline.us/")


@pytest.mark.parametrize(("config_cloud", "jwks_cloud"), CROSS, ids=["com-cfg", "gov-cfg"])
def test_validator_refuses_other_cloud_key_source(
    config_cloud: CloudName, jwks_cloud: CloudName
) -> None:
    config = JwtConfig(env="prod", cloud=config_cloud, tenant_id=TENANT, audiences=(AUDIENCE,))
    cache = JwksCache(FakeFetcher(entra_jwks_uri(jwks_cloud, TENANT), {}), clock=FakeClock())
    with pytest.raises(InvalidSchemaError):
        JwtValidator(config, cache)


async def test_government_never_falls_back_to_commercial_authority() -> None:
    config = JwtConfig.from_settings(settings("prod", GOV), tenant_id=TENANT, audiences=[AUDIENCE])
    with respx.mock(assert_all_called=False) as router:
        gov = router.get(entra_jwks_uri(GOV, TENANT)).respond(503)
        com = router.get(entra_jwks_uri(COM, TENANT)).respond(200, json=signer().jwks())
        async with httpx.AsyncClient() as client:
            validator = create_jwt_validator(config, client, clock=FakeClock())
            with pytest.raises(DependencyTransientError):
                await validator.validate(signer().sign(entra_claims(GOV)))
    assert gov.call_count == 1
    assert com.call_count == 0


async def test_commercial_fetches_only_commercial_authority() -> None:
    config = JwtConfig.from_settings(settings("prod", COM), tenant_id=TENANT, audiences=[AUDIENCE])
    with respx.mock(assert_all_called=False) as router:
        com = router.get(entra_jwks_uri(COM, TENANT)).respond(200, json=signer().jwks())
        gov = router.get(entra_jwks_uri(GOV, TENANT)).respond(200, json=signer().jwks())
        async with httpx.AsyncClient() as client:
            validator = create_jwt_validator(config, client, clock=FakeClock())
            await validator.validate(signer().sign(entra_claims(COM)))
    assert com.call_count == 1
    assert gov.call_count == 0


@pytest.mark.parametrize(
    "tenant",
    ["common", "organizations", "consumers", "{tenantid}", "", "contoso.onmicrosoft.com"],
)
@pytest.mark.parametrize("cloud", [COM, GOV])
def test_multi_tenant_or_non_guid_tenant_rejected_at_startup(cloud: CloudName, tenant: str) -> None:
    with pytest.raises(InvalidSchemaError) as info:
        JwtConfig.from_settings(settings("prod", cloud), tenant_id=tenant, audiences=[AUDIENCE])
    assert info.value.reason == "config"


@pytest.mark.parametrize("audiences", [[], [""], ["*"], [" api://x"]])
def test_audience_must_be_explicit(audiences: list[str]) -> None:
    with pytest.raises(InvalidSchemaError):
        JwtConfig.from_settings(settings("prod"), tenant_id=TENANT, audiences=audiences)
