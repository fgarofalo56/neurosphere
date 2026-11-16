"""PRP-51: every startup refusal is one type and the builder loop re-raises it."""

from __future__ import annotations

import pytest
from neurosphere_api.app import create_app
from neurosphere_api.runtime import compose_app
from neurosphere_api.runtime.builders import BuildContext, BuilderSpec
from neurosphere_api.runtime.builders.copilot import CopilotCredentialConfigError
from neurosphere_api.runtime.cors import load_cors_settings
from neurosphere_api.runtime.errors import CorsConfigError, StartupRefusedError
from neurosphere_core.cloud import Settings
from neurosphere_core.errors import InvalidSchemaError


def test_refusals_share_one_base() -> None:
    assert issubclass(CopilotCredentialConfigError, StartupRefusedError)
    assert issubclass(CorsConfigError, StartupRefusedError)
    assert issubclass(StartupRefusedError, Exception)


def test_cors_refusal_keeps_its_problem_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NS_CORS_ALLOWED_ORIGINS", "*")
    with pytest.raises(StartupRefusedError) as caught:
        load_cors_settings()
    assert isinstance(caught.value, InvalidSchemaError)
    assert caught.value.reason == "config"


def test_builder_loop_reraises_a_refusal_but_degrades_other_errors() -> None:
    def refuse(ctx: BuildContext) -> None:
        raise StartupRefusedError("refused")

    def boom(ctx: BuildContext) -> None:
        raise RuntimeError("secret detail")

    settings = Settings(env="local")
    with pytest.raises(StartupRefusedError, match="refused"):
        compose_app(
            create_app(settings),
            settings,
            builders=(BuilderSpec("refuser", ("copilot",), refuse),),
            env_probes=(),
        )
    registry = compose_app(
        create_app(settings),
        settings,
        builders=(BuilderSpec("boomer", ("copilot",), boom),),
        env_probes=(),
    )
    assert registry.get("copilot").code == "build_error"
