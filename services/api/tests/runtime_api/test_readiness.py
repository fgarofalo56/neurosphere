"""``/readyz`` with the ``composition`` probe: names and reason codes only, same body shape."""

from __future__ import annotations

from typing import Any

import pytest
from authz.authz_helpers import (  # pyright: ignore[reportMissingImports]
    AUDIENCE,
    TENANT,
    FakeClock,
)
from neurosphere_api.runtime import REQUIRED_COMPONENTS, ComponentRegistry, compose_app
from neurosphere_api.runtime.builders import BuildContext, BuilderSpec, default_builders
from neurosphere_api.runtime.builders import copilot as copilot_builder
from neurosphere_core.cloud import Settings

from .runtime_helpers import (
    builders_with_stubs,
    compose,
    configure_auth_env,
    configured_overrides,
    stub_builder,
)

STORE_COMPONENTS = ("policy_store", "revocation")


def _readyz(composed: Any) -> tuple[int, dict[str, Any]]:
    with composed.client() as client:
        response = client.get("/readyz")
    return response.status_code, response.json()


def test_missing_tenant_is_503_naming_authz(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_auth_env(monkeypatch)
    monkeypatch.delenv("NS_AUTH_TENANT_ID")
    clock = FakeClock()
    status, body = _readyz(
        compose(configured_overrides(clock), builders=builders_with_stubs(), clock=clock)
    )
    assert status == 503
    assert set(body) == {"status", "dependencies"}  # the PRP-05 body shape, unchanged
    assert body["status"] == "not_ready"
    deps = body["dependencies"]
    assert deps["composition"] == "unavailable"
    assert deps["composition.authz.tenant_id_missing"] == "unavailable"
    failing = sorted(k for k, v in deps.items() if v != "ok")
    assert failing == ["composition", "composition.authz.tenant_id_missing"]


def test_missing_cosmos_is_503_naming_the_store_components(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_auth_env(monkeypatch)  # tenant present, NS_COSMOS_KEY absent
    status, body = _readyz(compose())
    assert status == 503
    deps = body["dependencies"]
    for name in STORE_COMPONENTS:
        assert deps[f"composition.{name}.cosmos_unconfigured"] == "unavailable"
    assert deps["composition.authz.policy_store_unavailable"] == "unavailable"
    # Any other required component that reports (a missing upstream, or not built yet) is
    # unavailable; components that need no Cosmos (replay reads Blob) may build ok.
    for key, value in deps.items():
        name = key.split(".")[1] if key.startswith("composition.") else ""
        if name in REQUIRED_COMPONENTS:
            assert value == "unavailable", key


def test_fully_configured_app_is_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_auth_env(monkeypatch)
    clock = FakeClock()
    composed = compose(configured_overrides(clock), builders=builders_with_stubs(), clock=clock)
    status, body = _readyz(composed)
    assert status == 200, body
    assert body["status"] == "ready"
    assert body["dependencies"] == {
        "composition": "ok",
        "composition.copilot.disabled": "ok",
        "composition.mcp_server.disabled": "ok",
        "composition.ingest.disabled": "ok",
        "composition.scan.disabled": "ok",
    }
    assert composed.registry.ready


def test_optional_components_report_disabled_without_failing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_auth_env(monkeypatch)

    def off(ctx: BuildContext) -> None:
        ctx.disabled("copilot")

    builders = tuple(
        BuilderSpec("copilot", ("copilot",), off) if spec.name == "copilot" else spec
        for spec in builders_with_stubs()
    )
    clock = FakeClock()
    status, body = _readyz(compose(configured_overrides(clock), builders=builders, clock=clock))
    assert status == 200
    assert body["dependencies"]["composition.copilot.disabled"] == "ok"
    assert body["dependencies"]["composition.ingest.disabled"] == "ok"


def test_a_failed_optional_component_blocks_readiness(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_auth_env(monkeypatch)

    def misconfigured(ctx: BuildContext) -> None:
        ctx.failed("copilot", "misconfigured")

    builders = tuple(
        BuilderSpec("copilot", ("copilot",), misconfigured) if spec.name == "copilot" else spec
        for spec in builders_with_stubs()
    )
    clock = FakeClock()
    status, body = _readyz(compose(configured_overrides(clock), builders=builders, clock=clock))
    assert status == 503
    assert body["dependencies"]["composition.copilot.misconfigured"] == "unavailable"


def test_readiness_never_echoes_configuration_values(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_auth_env(monkeypatch, PSEUDONYM_KEY="s" * 48)  # key without its reference
    clock = FakeClock()
    composed = compose(configured_overrides(clock), builders=builders_with_stubs(), clock=clock)
    with composed.client() as client:
        text = client.get("/readyz").text
    assert "composition.authz.pseudonym_key_reference_missing" in text
    for value in (TENANT, AUDIENCE, "s" * 48, "contoso"):
        assert value not in text


def test_environment_probes_stay_alongside_composition() -> None:
    settings = Settings()
    from neurosphere_api.app import create_app

    app = create_app(settings)
    compose_app(app, settings, environ={})
    names = [probe.name for probe in app.state.health_probes]
    assert names[:4] == ["cosmos", "eventhubs", "blob", "composition"]


def test_a_raising_builder_fails_only_its_unreported_components() -> None:
    def boom(ctx: BuildContext) -> None:
        ctx.ok("catalog")
        raise RuntimeError("secret detail that must not surface")

    builders = (BuilderSpec("boom", ("catalog", "ledger"), boom),)
    composed = compose(builders=builders)
    assert composed.registry.get("catalog").state == "ok"
    assert composed.registry.get("ledger").reason == "build_error"
    _, body = _readyz(composed)
    assert "secret detail" not in str(body)


def test_unreported_components_are_not_built_and_unclaimed_ones_too() -> None:
    composed = compose(builders=(BuilderSpec("lazy", ("catalog",), lambda ctx: None),))
    assert composed.registry.get("catalog").state == "not_built"
    assert composed.registry.get("ledger").state == "not_built"


def test_a_builder_cannot_report_another_builders_component() -> None:
    def grab(ctx: BuildContext) -> None:
        ctx.ok("authz")

    composed = compose(builders=(BuilderSpec("grab", ("catalog",), grab),))
    assert composed.registry.get("authz").state == "not_built"
    assert composed.registry.get("catalog").reason == "build_error"


def test_two_builders_cannot_claim_one_component() -> None:
    with pytest.raises(ValueError, match="claimed"):
        compose(builders=(stub_builder("a", ["catalog"]), stub_builder("b", ["catalog"])))
    with pytest.raises(ValueError, match="unknown"):
        compose(builders=(stub_builder("a", ["warp_drive"]),))


def test_default_builders_cover_every_component_exactly_once() -> None:
    claimed = [name for spec in default_builders() for name in spec.components]
    assert sorted(claimed) == sorted(ComponentRegistry().components)
    assert [spec.name for spec in default_builders()] == [
        "authz",
        "data",
        "planes",
        "copilot",
        "mcp",
        "edge",
    ]
    assert copilot_builder.BUILDER in default_builders()


def test_registry_rules() -> None:
    registry = ComponentRegistry()
    with pytest.raises(ValueError, match="cannot be disabled"):
        registry.disabled("authz")
    with pytest.raises(ValueError, match="reason code"):
        registry.failed("authz", "https://login.example/tenant")
    with pytest.raises(KeyError):
        registry.ok("warp_drive")
    registry.disabled("copilot")
    assert not registry.get("copilot").blocks_readiness
    registry.failed("copilot", "misconfigured")
    assert registry.get("copilot").blocks_readiness
    registry.failed("ledger", "cosmos_unconfigured")
    assert [s.name for s in registry.blocking()][:2] == ["authz", "policy_store"]


def test_stub_builders_only_replace_placeholders() -> None:
    names = [spec.name for spec in builders_with_stubs()]
    assert names == ["authz", "stub-data", "stub-planes", "copilot", "mcp", "edge"]
    assert {spec.components for spec in builders_with_stubs()} == {
        spec.components for spec in default_builders()
    }
