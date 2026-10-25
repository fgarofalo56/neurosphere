"""The authz builder: real deriver composition, failure reasons, and the production validator."""

from __future__ import annotations

import asyncio
import base64

import pytest
from authz.authz_helpers import (  # pyright: ignore[reportMissingImports]
    CUSTOMER,
    FINANCE,
    TENANT,
    FakeClock,
    at,
)
from neurosphere_api import main
from neurosphere_api.authz import AuthzState
from neurosphere_api.runtime.builders import SCOPE_DERIVER
from neurosphere_core.auth.jwt import JwtValidator, entra_jwks_uri
from neurosphere_core.auth.revocation import InMemoryRevocationStore, RevocationEntry
from neurosphere_core.auth.scope import ScopeDeriver
from neurosphere_core.cloud import CloudName, Settings

from .runtime_helpers import (
    ALICE,
    FakeCosmosClient,
    builders_with_stubs,
    compose,
    composed_principal_id,
    configure_auth_env,
    configured_overrides,
)

ME = "/api/v1/me/domains"
OTHER_TENANT = "11111111-2222-4333-8444-555555555555"


def _dummy_emulator_key() -> str:
    return base64.b64encode(b"emulator-ignores-this").decode()


def test_configured_composition_serves_a_protected_route(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_auth_env(monkeypatch)
    clock = FakeClock()
    composed = compose(configured_overrides(clock), builders=builders_with_stubs(), clock=clock)
    assert composed.registry.get("authz").state == "ok"
    state = composed.app.state.authz
    assert isinstance(state, AuthzState)
    # The scope source is the REAL deriver, composed from the overridden stores.
    assert isinstance(state.scope_source, ScopeDeriver)
    with composed.client() as client:
        response = client.get(ME, headers=composed.auth())
    assert response.status_code == 200, response.text
    assert [item["domain_id"] for item in response.json()["items"]] == [FINANCE]


def test_unauthenticated_request_is_401_once_composed(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_auth_env(monkeypatch)
    clock = FakeClock()
    composed = compose(configured_overrides(clock), builders=builders_with_stubs(), clock=clock)
    with composed.client() as client:
        response = client.get(ME)
    assert response.status_code == 401


def test_revoked_principal_is_forbidden(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_auth_env(monkeypatch)
    clock = FakeClock()
    store = InMemoryRevocationStore()
    pid = composed_principal_id(ALICE)
    entry = RevocationEntry(
        principal_id=pid, revoked_at=at(10), reason="offboarded", revoked_by=pid
    )
    asyncio.run(store.put(entry))
    overrides = configured_overrides(clock, revocation_store=store)
    composed = compose(overrides, builders=builders_with_stubs(), clock=clock)
    with composed.client() as client:
        response = client.get(ME, headers=composed.auth())
    assert response.status_code == 403
    assert response.json()["reason"] == "principal_revoked"


def test_missing_tenant_fails_authz_and_routes_stay_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_auth_env(monkeypatch)
    monkeypatch.delenv("NS_AUTH_TENANT_ID")
    clock = FakeClock()
    composed = compose(configured_overrides(clock), builders=builders_with_stubs(), clock=clock)
    status = composed.registry.get("authz")
    assert (status.state, status.reason) == ("failed", "tenant_id_missing")
    assert composed.registry.get("policy_store").state == "ok"
    assert not hasattr(composed.app.state, "authz")
    with composed.client() as client:
        response = client.get(ME, headers=composed.auth())
    assert response.status_code == 503
    assert response.json()["reason"] == "authz_unconfigured"


@pytest.mark.parametrize(
    ("env", "reason"),
    [
        ({"TENANT_ID": "common"}, "tenant_id_invalid"),
        ({"AUDIENCES": ""}, "audiences_missing"),
        ({"CUSTOMER_ID": "Not A Slug"}, "scope_config_invalid"),
    ],
)
def test_invalid_auth_settings_name_a_reason(
    monkeypatch: pytest.MonkeyPatch, env: dict[str, str], reason: str
) -> None:
    configure_auth_env(monkeypatch, **env)
    fake = FakeCosmosClient()
    composed = compose(
        configured_overrides(FakeClock(), authenticator=None, cosmos_client_factory=lambda: fake),
        builders=builders_with_stubs(),
    )
    status = composed.registry.get("authz")
    assert (status.state, status.reason) == ("failed", reason)


def test_validator_and_deriver_bound_to_different_tenants_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_auth_env(monkeypatch, TENANT_ID=OTHER_TENANT)  # the test validator trusts TENANT
    clock = FakeClock()
    composed = compose(configured_overrides(clock), builders=builders_with_stubs(), clock=clock)
    status = composed.registry.get("authz")
    assert (status.state, status.reason) == ("failed", "authz_binding_mismatch")


def test_outside_local_customer_id_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_auth_env(monkeypatch, PSEUDONYM_KEY="k" * 40)
    monkeypatch.setenv(
        "NS_AUTH_PSEUDONYM_KEY_REFERENCE", "https://ns-test-kv.vault.azure.net/secrets/pseudonym"
    )
    monkeypatch.delenv("NS_AUTH_CUSTOMER_ID")
    settings = Settings(env="dev", cloud=CloudName.COMMERCIAL)
    clock = FakeClock()
    composed = compose(
        configured_overrides(clock), builders=builders_with_stubs(), clock=clock, settings=settings
    )
    status = composed.registry.get("authz")
    assert (status.state, status.reason) == ("failed", "customer_id_missing")


def test_local_customer_defaults_to_the_synthetic_sandbox_customer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_auth_env(monkeypatch)
    monkeypatch.delenv("NS_AUTH_CUSTOMER_ID")
    clock = FakeClock()
    composed = compose(configured_overrides(clock), builders=builders_with_stubs(), clock=clock)
    assert composed.app.state.authz.scope_source.config.customer_id == "synthco"
    assert CUSTOMER != "synthco"  # the test policy is for another customer: nothing is granted


def test_main_create_wires_the_entra_validator_and_cosmos_deriver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_auth_env(monkeypatch)
    monkeypatch.setenv("NS_COSMOS_KEY", _dummy_emulator_key())  # client construction only
    app = main.create()
    registry = app.state.composition
    for name in ("authz", "policy_store", "revocation"):
        assert registry.get(name).state == "ok", registry.get(name)
    state = app.state.authz
    assert isinstance(state, AuthzState)
    validator = state.authenticator
    assert isinstance(validator, JwtValidator)
    assert validator.config.jwks_uri == entra_jwks_uri(CloudName.COMMERCIAL, TENANT)
    assert validator.config.dev_issuer is None  # Entra keys only, in every NS_ENV
    assert isinstance(state.scope_source, ScopeDeriver)
    assert state.scope_source.config.tenant_id == TENANT


def test_main_create_without_any_settings_is_not_ready_but_starts() -> None:
    app = main.create()
    registry = app.state.composition
    assert not registry.ready
    assert registry.get("authz").reason == "tenant_id_missing"
    assert registry.get("policy_store").reason == "cosmos_unconfigured"


def test_the_composed_deriver_is_published_for_later_builders(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from neurosphere_api.runtime.builders import BuildContext, BuilderSpec

    configure_auth_env(monkeypatch)
    seen: list[object] = []

    def probe(ctx: BuildContext) -> None:
        seen.append(ctx.shared(SCOPE_DERIVER))
        ctx.ok("catalog")

    builders = (*builders_with_stubs()[:1], BuilderSpec("probe", ("catalog",), probe))
    clock = FakeClock()
    composed = compose(configured_overrides(clock), builders=builders, clock=clock)
    assert seen == [composed.app.state.authz.scope_source]
