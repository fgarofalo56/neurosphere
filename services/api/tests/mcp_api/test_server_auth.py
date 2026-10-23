"""MCP resource-server authorization (PRP-22 item 1): audience, resource, scope, metadata.

401 for any token that is not a valid MCP token (other audience, other resource, bad signature,
expired, missing), always with a ``WWW-Authenticate`` header naming the RFC 9728 metadata URL;
403 for a valid MCP token without the required scope; REST and MCP tokens are not
interchangeable in either direction. ``validate_token_resource=True`` is asserted both on the
built ``AuthSettings`` and in the factory source.
"""

from __future__ import annotations

import ast
import inspect
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import conftest_server as cs  # pyright: ignore[reportMissingImports]
import pytest
from mcp.server.auth.settings import AuthSettings
from neurosphere_api.mcp.server import (
    MCP_PATH,
    PROTECTED_RESOURCE_METADATA_PATH,
    McpAccessToken,
    McpServerSettings,
    McpTokenVerifier,
    authorization_server_for,
    build_router,
    check_stdio_allowed,
    create_mcp_server,
    load_mcp_server_settings,
    mcp_jwt_config,
    run_stdio_dev,
)
from neurosphere_api.mcp.server import factory as factory_module
from neurosphere_core.auth.jwt import (
    DevIssuer,
    JwksCache,
    JwtConfig,
    JwtValidator,
    VerifiedClaims,
)
from neurosphere_core.cloud import CloudName, Settings
from neurosphere_core.errors import InvalidSchemaError, UnauthorizedError

METADATA_URL = f"https://{cs.MCP_HOST}{PROTECTED_RESOURCE_METADATA_PATH}"
MALFORMED = "not-a-jwt"


def _assert_401(response: Any) -> None:
    assert response.status_code == 401, response.text
    challenge = response.headers["www-authenticate"]
    assert challenge.startswith("Bearer ")
    assert f'resource_metadata="{METADATA_URL}"' in challenge
    assert 'error="invalid_token"' in challenge


# -- validate_token_resource is explicit ---------------------------------------------------------


def test_auth_settings_set_validate_token_resource_true_explicitly() -> None:
    harness = cs.make_harness()
    auth = harness.mount.auth_settings
    assert isinstance(auth, AuthSettings)
    assert auth.validate_token_resource is True  # not None (the SDK default), not False
    assert "validate_token_resource" in auth.model_fields_set
    assert str(auth.resource_server_url) == cs.MCP_RESOURCE
    assert auth.required_scopes == [cs.REQUIRED_SCOPE]


def test_factory_source_passes_validate_token_resource_true_literally() -> None:
    tree = ast.parse(inspect.getsource(factory_module))
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "AuthSettings"
    ]
    assert len(calls) == 1, "exactly one AuthSettings construction"
    keywords = {kw.arg: kw.value for kw in calls[0].keywords}
    value = keywords.get("validate_token_resource")
    assert isinstance(value, ast.Constant) and value.value is True


# -- 401: wrong audience, wrong resource, bad signature, expired, missing ------------------------


async def test_rest_audience_token_is_rejected_by_mcp_with_401() -> None:
    harness = cs.make_harness()
    async with cs.mcp_session(harness) as client:
        response = await cs.rpc(client, "tools/list", token=harness.rest_token(cs.ALICE))
    _assert_401(response)


async def test_token_for_another_audience_is_rejected_on_every_mcp_method() -> None:
    harness = cs.make_harness()
    other = harness.token(cs.ALICE, audience="api://some-other-resource")
    async with cs.mcp_session(harness) as client:
        for method, params, name in (
            ("tools/list", None, None),
            ("tools/call", {"name": "search_catalog", "arguments": {}}, "search_catalog"),
            ("resources/list", None, None),
            ("resources/read", {"uri": "neurosphere://scope/current"}, None),
        ):
            response = await cs.rpc(client, method, params, token=other, name=name)
            _assert_401(response)
        get = await client.get("/mcp", headers=cs.bearer(other))
        _assert_401(get)


async def test_audience_check_and_resource_check_are_separate() -> None:
    """A validator wrongly accepting another audience is still refused by the SDK resource
    check; with the resource check disabled the same token would get through."""
    harness = cs.make_harness()
    loose = cs.make_mcp_validator(harness.clock, audiences=(cs.MCP_AUDIENCE, "api://loose"))
    loose_token = harness.token(cs.ALICE, audience="api://loose")

    class _Wrapped:  # not a JwtValidator: bypasses the factory's exact-audience check
        async def validate(self, token: str | None) -> VerifiedClaims:
            return await loose.validate(token)

    verifier = McpTokenVerifier(
        _Wrapped(), resource_server_url=cs.MCP_RESOURCE, resource_audiences=(cs.MCP_AUDIENCE,)
    )
    access = await verifier.verify_token(loose_token)
    assert access is not None and access.resource == "api://loose"  # audience check passed

    from mcp.server.auth.middleware.bearer_auth import BearerAuthBackend
    from pydantic import AnyHttpUrl
    from starlette.requests import HTTPConnection

    conn = HTTPConnection(
        {"type": "http", "headers": [(b"authorization", ("Bear" + "er " + loose_token).encode())]}
    )
    checked = BearerAuthBackend(verifier, resource_server_url=AnyHttpUrl(cs.MCP_RESOURCE))
    refused = await checked.authenticate(conn)
    assert refused is None  # the resource check refuses it
    unchecked = BearerAuthBackend(verifier, resource_server_url=None)
    passed = await unchecked.authenticate(conn)
    assert passed is not None  # only the resource check stopped it

    # The good token passes both: audience is an MCP audience, resource is the MCP resource.
    good = await verifier.verify_token(harness.token(cs.ALICE))
    assert good is not None and good.resource == cs.MCP_RESOURCE


async def test_bad_signature_expired_missing_and_malformed_tokens_are_401() -> None:
    harness = cs.make_harness()
    # Same issuer string and the trusted kid, but another private key: invalid signature.
    impostor = DevIssuer(
        Settings(env="local"), tenant_id=cs.helpers.TENANT, kid=cs.helpers.dev_issuer().kid
    )
    unknown_kid = cs.helpers.dev_issuer("another-key")
    forged = [
        issuer.mint(
            audience=cs.MCP_AUDIENCE,
            object_id=cs.ALICE,
            now=harness.clock.now,
            lifetime_seconds=cs.LONG_LIFETIME,
            scopes=[cs.REQUIRED_SCOPE],
        )
        for issuer in (impostor, unknown_kid)
    ]
    with pytest.raises(UnauthorizedError) as bad_signature:
        await harness.validator.validate(forged[0])
    assert bad_signature.value.reason == "invalid_signature"
    expired = harness.token(cs.ALICE, lifetime=60)
    async with cs.mcp_session(harness) as client:
        for token in forged:
            _assert_401(await cs.rpc(client, "tools/list", token=token))
        _assert_401(await cs.rpc(client, "tools/list", token=None))
        _assert_401(await cs.rpc(client, "tools/list", token=MALFORMED))
        harness.clock.advance(3600)
        _assert_401(await cs.rpc(client, "tools/list", token=expired))


# -- 403: valid token without the required scope -------------------------------------------------


async def test_valid_token_missing_the_required_scope_is_403() -> None:
    harness = cs.make_harness()
    async with cs.mcp_session(harness) as client:
        response = await cs.rpc(
            client, "tools/list", token=harness.token(cs.ALICE, scopes=("user.read",))
        )
        assert response.status_code == 403, response.text
        challenge = response.headers["www-authenticate"]
        assert 'error="insufficient_scope"' in challenge
        assert f'resource_metadata="{METADATA_URL}"' in challenge

        ok = await cs.rpc(client, "tools/list", token=harness.token(cs.ALICE))
        assert ok.status_code == 200, ok.text


# -- cross-use in the other direction ------------------------------------------------------------


async def test_mcp_token_is_not_accepted_by_the_rest_authenticator() -> None:
    harness = cs.make_harness()
    mcp_token = harness.token(cs.ALICE)
    path = f"/api/v1/actions/domains/{cs.FINANCE}/intents"
    rest_client = harness.api.h.client
    refused = rest_client.get(path, headers=cs.bearer(mcp_token))
    assert refused.status_code == 401, refused.text
    accepted = rest_client.get(path, headers=cs.bearer(harness.rest_token(cs.ALICE)))
    assert accepted.status_code == 200, accepted.text

    # And directly at the authenticator level, both directions.
    with pytest.raises(UnauthorizedError) as rest_side:
        await harness.api.h.validator.validate(mcp_token)
    assert rest_side.value.reason == "wrong_audience"
    with pytest.raises(UnauthorizedError) as mcp_side:
        await harness.validator.validate(harness.rest_token(cs.ALICE))
    assert mcp_side.value.reason == "wrong_audience"


def test_factory_refuses_mcp_audiences_that_overlap_rest() -> None:
    api_harness = cs.make_api()
    overlapping = cs.make_mcp_validator(api_harness.h.clock, audiences=(cs.REST_AUDIENCE,))
    with pytest.raises(InvalidSchemaError) as exc:
        create_mcp_server(
            api_harness.h.app,
            cs.mcp_settings(audiences=(cs.REST_AUDIENCE,)),
            validator=overlapping,
        )
    assert exc.value.reason == "config"


def test_factory_refuses_a_validator_whose_audiences_differ_from_the_settings() -> None:
    api_harness = cs.make_api()
    wider = cs.make_mcp_validator(api_harness.h.clock, audiences=(cs.MCP_AUDIENCE, "api://x"))
    with pytest.raises(InvalidSchemaError):
        create_mcp_server(api_harness.h.app, cs.mcp_settings(), validator=wider)


# -- RFC 9728 metadata -----------------------------------------------------------------------------


def test_protected_resource_metadata_is_served_with_the_cloud_authorization_server() -> None:
    harness = cs.make_harness()
    harness.app.include_router(build_router(), prefix=PROTECTED_RESOURCE_METADATA_PATH)
    response = harness.api.h.client.get(PROTECTED_RESOURCE_METADATA_PATH)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["resource"] == cs.MCP_RESOURCE
    assert body["authorization_servers"] == [
        f"https://login.microsoftonline.com/{cs.helpers.TENANT}/v2.0"
    ]
    assert body["scopes_supported"] == [cs.REQUIRED_SCOPE]
    assert body["bearer_methods_supported"] == ["header"]
    assert PROTECTED_RESOURCE_METADATA_PATH == "/.well-known/oauth-protected-resource" + MCP_PATH


def test_metadata_route_fails_closed_until_the_server_is_built() -> None:
    api_harness = cs.make_api()
    api_harness.h.app.include_router(build_router(), prefix=PROTECTED_RESOURCE_METADATA_PATH)
    response = api_harness.h.client.get(PROTECTED_RESOURCE_METADATA_PATH)
    assert response.status_code == 503
    assert response.json()["reason"] == "mcp_unconfigured"


@pytest.mark.parametrize(
    ("cloud", "login_host"),
    [
        (CloudName.COMMERCIAL, "login.microsoftonline.com"),
        (CloudName.GOVERNMENT, "login.microsoftonline.us"),
    ],
)
def test_authorization_server_follows_the_active_cloud_profile(
    cloud: CloudName, login_host: str
) -> None:
    settings = cs.mcp_settings()
    config = mcp_jwt_config(Settings(env="dev", cloud=cloud), settings, tenant_id=cs.helpers.TENANT)
    assert config.audiences == (cs.MCP_AUDIENCE,)
    assert authorization_server_for(config) == f"https://{login_host}/{cs.helpers.TENANT}/v2.0"


# -- settings ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://mcp.neurosphere.test/mcp",
        "https://mcp.neurosphere.test/other",
        "https://mcp.neurosphere.test/mcp?x=1",
        "https://user@mcp.neurosphere.test/mcp",
        "https:///mcp",
    ],
)
def test_resource_url_must_be_https_and_the_fixed_path(url: str) -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        McpServerSettings(resource_server_url=url)


def test_default_audience_is_the_resource_identifier_and_scope_is_mcp_invoke() -> None:
    settings = McpServerSettings(resource_server_url="https://MCP.neurosphere.test/mcp")
    assert settings.resource_server_url == cs.MCP_RESOURCE
    assert settings.effective_audiences == (cs.MCP_RESOURCE,)
    assert settings.required_scope == "mcp.invoke"
    assert settings.protected_resource_metadata_url == METADATA_URL


def test_settings_load_from_ns_mcp_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NS_MCP_RESOURCE_SERVER_URL", raising=False)
    assert load_mcp_server_settings() is None
    monkeypatch.setenv("NS_MCP_RESOURCE_SERVER_URL", cs.MCP_RESOURCE)
    monkeypatch.setenv("NS_MCP_AUDIENCES", '["api://neurosphere-test-mcp"]')
    monkeypatch.setenv("NS_MCP_REQUIRED_SCOPE", "mcp.use")
    loaded = load_mcp_server_settings()
    assert loaded is not None
    assert loaded.effective_audiences == (cs.MCP_AUDIENCE,)
    assert loaded.required_scope == "mcp.use"
    monkeypatch.setenv("NS_MCP_RESOURCE_SERVER_URL", "http://insecure.test/mcp")
    with pytest.raises(InvalidSchemaError) as exc:
        load_mcp_server_settings()
    assert exc.value.reason == "config"


def test_metadata_path_lives_beside_the_resource_path() -> None:
    assert Path(PROTECTED_RESOURCE_METADATA_PATH).name == Path(MCP_PATH).name


# -- stdio: local development only ---------------------------------------------------------------


class _ProbeStopError(Exception):
    pass


def _probe_transport(seen: list[object]) -> Any:
    from contextlib import asynccontextmanager

    from mcp.server.auth.middleware.auth_context import get_access_token

    @asynccontextmanager
    async def transport() -> AsyncIterator[tuple[Any, Any]]:
        seen.append(get_access_token())
        if seen:  # always true here: stop before the server would read stdin
            raise _ProbeStopError
        yield (None, None)

    return transport


async def test_stdio_entry_point_refuses_outside_ns_env_local() -> None:
    harness = cs.make_harness()
    seen: list[object] = []
    for env in ("dev", "test", "staging", "prod"):
        with pytest.raises(InvalidSchemaError) as exc:
            await run_stdio_dev(
                harness.mount,
                Settings(env=env, cloud=CloudName.COMMERCIAL),
                dev_token=harness.token(cs.ALICE),
                transport=_probe_transport(seen),
            )
        assert exc.value.reason == "stdio_refused"
    assert seen == []


async def test_stdio_entry_point_refuses_without_the_dev_issuer() -> None:
    api_harness = cs.make_api()
    config = JwtConfig(
        env="local",
        cloud=CloudName.COMMERCIAL,
        tenant_id=cs.helpers.TENANT,
        audiences=(cs.MCP_AUDIENCE,),
    )
    fetcher = cs.helpers.StandInJwksFetcher(config.jwks_uri)
    validator = JwtValidator(config, JwksCache(fetcher, clock=api_harness.h.clock))
    mount = create_mcp_server(api_harness.h.app, cs.mcp_settings(), validator=validator)
    with pytest.raises(InvalidSchemaError) as exc:
        check_stdio_allowed(Settings(env="local"), mount)
    assert exc.value.reason == "stdio_refused"


async def test_stdio_entry_point_requires_a_dev_token_for_the_mcp_resource_and_scope() -> None:
    harness = cs.make_harness()
    seen: list[object] = []
    local = Settings(env="local")
    for bad in (
        harness.rest_token(cs.ALICE),
        harness.token(cs.ALICE, scopes=("user.read",)),
        MALFORMED,
    ):
        with pytest.raises(UnauthorizedError) as exc:
            await run_stdio_dev(
                harness.mount, local, dev_token=bad, transport=_probe_transport(seen)
            )
        assert exc.value.reason == "stdio_dev_token"
    assert seen == []

    with pytest.raises(_ProbeStopError):
        await run_stdio_dev(
            harness.mount,
            local,
            dev_token=harness.token(cs.ALICE),
            transport=_probe_transport(seen),
        )
    [access] = seen
    assert isinstance(access, McpAccessToken) and access.verified.issuer_kind == "dev"
    from mcp.server.auth.middleware.auth_context import get_access_token

    assert get_access_token() is None  # the stdio principal does not outlive the session
