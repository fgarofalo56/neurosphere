"""PRP-51: ``CompositionOverrides`` are test-only; composition refuses them outside local."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from neurosphere_api.app import create_app
from neurosphere_api.runtime import CompositionOverrides, compose_app
from neurosphere_api.runtime.errors import StartupRefusedError
from neurosphere_core.cloud import Settings


def _settings(env: str) -> Settings:
    return Settings(env=env, cloud="commercial")  # pyright: ignore[reportArgumentType]


@pytest.mark.parametrize("env", ["dev", "test", "staging", "prod"])
def test_overrides_are_refused_outside_local_naming_only_field_names(env: str) -> None:
    marker = "value-that-must-not-appear"
    overrides = CompositionOverrides(
        cosmos_client_factory=lambda: marker, clock=lambda: 0.0, backends={"x": marker}
    )
    settings = _settings(env)
    with pytest.raises(StartupRefusedError) as refused:
        compose_app(create_app(settings), settings, overrides, builders=(), env_probes=())
    message = str(refused.value)
    assert "backends" in message
    assert "clock" in message
    assert "cosmos_client_factory" in message
    assert marker not in message


def test_empty_overrides_are_accepted_outside_local() -> None:
    settings = _settings("dev")
    app = create_app(settings)
    compose_app(app, settings, CompositionOverrides(), builders=(), env_probes=())


def test_overrides_are_accepted_in_local() -> None:
    settings = Settings(env="local")
    app = create_app(settings)
    compose_app(app, settings, CompositionOverrides(clock=lambda: 0.0), builders=(), env_probes=())
    assert TestClient(app).get("/healthz").status_code == 200
