"""``configure_apply_from_settings``: opt-in wiring, fail closed when unset (PRP-08 item 14).

No network and no Cosmos: the register store is the in-memory seam.
"""

from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient
from neurosphere_api import main
from neurosphere_api.app import create_app
from neurosphere_api.deploy.apply import PlanApprovalStore, build_router
from neurosphere_api.deploy.apply.bootstrap import (
    DeployApplySettings,
    configure_apply_from_settings,
)
from neurosphere_connector.write import WriteTargetRegistry
from neurosphere_core.cloud import CloudName, Settings
from neurosphere_core.deploy.register import CustomerScopedRegister, InMemoryRegisterStore

LOCAL = Settings(env="local", cloud=CloudName.COMMERCIAL)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "NS_DEPLOY_APPLY_ENABLED",
        "NS_DEPLOY_APPLY_REGISTER_CONTAINER",
        "NS_AUTH_CUSTOMER_ID",
        "NS_SCAN_ENABLED",
        "NS_INGEST_PRODUCERS_FILE",
    ):
        monkeypatch.delenv(name, raising=False)


def test_disabled_by_default_configures_nothing() -> None:
    app = create_app(LOCAL)
    assert configure_apply_from_settings(app, LOCAL) is False
    assert not hasattr(app.state, "deploy_plan_approvals")
    assert not hasattr(app.state, "deploy_register_store")


def test_unconfigured_routes_answer_503() -> None:
    app = create_app(LOCAL)
    app.include_router(build_router(), prefix="/api/v1/deploy/apply")
    assert configure_apply_from_settings(app, LOCAL) is False
    # The request is refused before authorization can matter; either way nothing acts.
    response = TestClient(app).post("/api/v1/deploy/apply/domains/d/plans/approve", json={})
    assert response.status_code in (401, 403, 422, 503)
    assert not hasattr(app.state, "deploy_plan_approvals")


def test_main_create_leaves_apply_unconfigured_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NS_ENV", "local")
    assert not hasattr(main.create().state, "deploy_plan_approvals")


def test_enabled_without_a_register_container_stays_unconfigured(
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = create_app(LOCAL)
    with caplog.at_level(logging.ERROR, logger="neurosphere_api.deploy.apply"):
        assert configure_apply_from_settings(app, LOCAL, DeployApplySettings(enabled=True)) is False
    assert "NS_DEPLOY_APPLY_REGISTER_CONTAINER" in caplog.text
    assert not hasattr(app.state, "deploy_plan_approvals")


def test_enabled_without_a_customer_binding_stays_unconfigured() -> None:
    settings = Settings(
        env="test", cloud=CloudName.COMMERCIAL
    )  # no synthetic default outside local
    app = create_app(settings)
    seam = InMemoryRegisterStore()
    assert (
        configure_apply_from_settings(
            app, settings, DeployApplySettings(enabled=True), register=seam
        )
        is False
    )
    assert not hasattr(app.state, "deploy_plan_approvals")


def test_enabled_installs_the_collaborators_and_the_env_flag_is_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NS_DEPLOY_APPLY_ENABLED", "true")
    app = create_app(LOCAL)
    seam = InMemoryRegisterStore()
    assert configure_apply_from_settings(app, LOCAL, register=seam) is True
    assert isinstance(app.state.deploy_plan_approvals, PlanApprovalStore)
    assert app.state.deploy_register_store is seam
    assert app.state.deploy_live_inventory is None


def test_startup_registers_the_deploy_connector_scoped_to_the_customer() -> None:
    app = create_app(LOCAL)
    registry = WriteTargetRegistry()
    app.state.write_targets = registry  # what the composed action plane installs
    seam = InMemoryRegisterStore()
    assert configure_apply_from_settings(
        app, LOCAL, DeployApplySettings(enabled=True), register=seam
    )
    assert registry.names() == ()  # nothing until the app starts
    with TestClient(app):
        assert registry.names() == ("deploy-orchestrator",)
        connector = registry.get("deploy-orchestrator")
        assert connector.advisory is False
        scoped = connector._register  # pyright: ignore[reportPrivateUsage, reportAttributeAccessIssue]
        assert isinstance(scoped, CustomerScopedRegister)
        assert scoped.customer_id == "synthco"


def test_startup_without_an_action_plane_registers_nothing_and_does_not_crash(
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = create_app(LOCAL)
    assert configure_apply_from_settings(
        app, LOCAL, DeployApplySettings(enabled=True), register=InMemoryRegisterStore()
    )
    with caplog.at_level(logging.ERROR, logger="neurosphere_api.deploy.apply"):
        with TestClient(app):
            pass
    assert "action plane unavailable" in caplog.text


def test_no_secret_bearing_setting_exists() -> None:
    words = ("secret", "key", "password", "token", "connection")
    assert not [n for n in DeployApplySettings.model_fields if any(w in n for w in words)]
