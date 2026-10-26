"""No test-only issuer, stand-in JWKS or bypass is reachable from ``main`` (PRP-29 item 1)."""

from __future__ import annotations

import ast
import base64
import re
from pathlib import Path

import pytest
from neurosphere_api import main
from neurosphere_api.authz import AuthzState
from neurosphere_core.auth.jwt import JwtValidator

from .runtime_helpers import configure_auth_env

_API = Path(__file__).resolve().parents[2] / "neurosphere_api"
_COMPOSITION_FILES = [*sorted((_API / "runtime").rglob("*.py")), _API / "main.py"]
_FORBIDDEN = re.compile(r"DevIssuer|dev_issuer|StandIn")


def test_composition_sources_name_no_test_issuer() -> None:
    assert len(_COMPOSITION_FILES) >= 10
    offenders = {
        str(path.relative_to(_API)): sorted(set(_FORBIDDEN.findall(path.read_text("utf-8"))))
        for path in _COMPOSITION_FILES
        if _FORBIDDEN.search(path.read_text("utf-8"))
    }
    assert offenders == {}


def test_composition_never_imports_the_dev_issuer_module() -> None:
    for path in _COMPOSITION_FILES:
        tree = ast.parse(path.read_text("utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.endswith("dev_issuer"), path
            if isinstance(node, ast.Import):
                assert not any(a.name.endswith("dev_issuer") for a in node.names), path


@pytest.mark.parametrize("env", ["local", "dev", "test", "staging", "prod"])
def test_main_installs_only_the_entra_validator_in_every_env(
    monkeypatch: pytest.MonkeyPatch, env: str
) -> None:
    configure_auth_env(
        monkeypatch,
        PSEUDONYM_KEY="p" * 40,
        PSEUDONYM_KEY_REFERENCE="https://ns-test-kv.vault.azure.net/secrets/pseudonym",
    )
    monkeypatch.setenv("NS_ENV", env)
    monkeypatch.setenv("NS_CLOUD", "commercial")
    if env == "local":
        monkeypatch.setenv("NS_COSMOS_KEY", base64.b64encode(b"emulator-ignores-this").decode())
    else:
        monkeypatch.setenv("NS_STORE_COSMOS_ACCOUNT", "nsdevaccount")
    app = main.create()
    assert app.state.composition.get("authz").state == "ok", app.state.composition.get("authz")
    state = app.state.authz
    assert isinstance(state, AuthzState)
    assert isinstance(state.authenticator, JwtValidator)
    assert state.authenticator.config.dev_issuer is None
    assert state.authenticator.config.env == env


def test_main_create_accepts_no_overrides() -> None:
    import inspect

    assert list(inspect.signature(main.create).parameters) == []
    source = inspect.getsource(main)
    assert "CompositionOverrides" not in source
    assert "overrides" not in source.split("def create", 1)[1]
