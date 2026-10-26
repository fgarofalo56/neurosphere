"""Pseudonym key resolution (PRP-29 C14): configured key, local dev key, refusal elsewhere."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from authz.authz_helpers import FakeClock  # pyright: ignore[reportMissingImports]
from neurosphere_api.runtime import (
    LOCAL_DEV_PSEUDONYM_KEY_REFERENCE,
    AuthSettings,
    local_dev_pseudonym_key,
    resolve_pseudonym_key,
)
from neurosphere_api.runtime import pseudonym as pseudonym_module
from neurosphere_core.cloud import CloudName, Settings
from neurosphere_core.errors import InvalidSchemaError
from pydantic import SecretStr

from .runtime_helpers import (
    builders_with_stubs,
    compose,
    configure_auth_env,
    configured_overrides,
)

REFERENCE = "https://ns-test-kv.vault.azure.net/secrets/principal-pseudonym-key"
MESSAGE = b"0f1e2d3c-4b5a-4968-8776-a5b4c3d2e1f0:6c1d2e3f-4a5b-4c6d-8e7f-90a1b2c3d4e5"


def _secret(char: str = "q", n: int = 40) -> SecretStr:
    return SecretStr(char * n)


def test_local_without_a_key_uses_the_public_dev_key() -> None:
    key = resolve_pseudonym_key(AuthSettings(), env="local")
    assert key.reference == LOCAL_DEV_PSEUDONYM_KEY_REFERENCE
    # Deterministic: the API and the operator grant script derive identical pseudonyms.
    assert key.digest(MESSAGE) == local_dev_pseudonym_key().digest(MESSAGE)
    assert key.digest(MESSAGE) == resolve_pseudonym_key(AuthSettings(), env="local").digest(MESSAGE)


@pytest.mark.parametrize("env", ["dev", "test", "staging", "prod"])
def test_outside_local_a_missing_key_is_refused(env: str) -> None:
    with pytest.raises(InvalidSchemaError) as caught:
        resolve_pseudonym_key(AuthSettings(), env=env)
    assert caught.value.reason == "pseudonym_key_missing"


def test_a_configured_key_wins_and_differs_from_the_dev_key() -> None:
    settings = AuthSettings(pseudonym_key=_secret(), pseudonym_key_reference=REFERENCE)
    for env in ("local", "prod"):
        key = resolve_pseudonym_key(settings, env=env)
        assert key.reference == REFERENCE
        assert key.digest(MESSAGE) != local_dev_pseudonym_key().digest(MESSAGE)


@pytest.mark.parametrize(
    ("settings", "reason"),
    [
        (AuthSettings(pseudonym_key=_secret()), "pseudonym_key_reference_missing"),
        (
            AuthSettings(pseudonym_key=_secret(n=8), pseudonym_key_reference=REFERENCE),
            "pseudonym_key_invalid",
        ),
        (
            AuthSettings(pseudonym_key=_secret(), pseudonym_key_reference="https://kv.example/x"),
            "pseudonym_key_invalid",
        ),
    ],
)
def test_bad_key_configuration_is_refused_without_echoing_it(
    settings: AuthSettings, reason: str
) -> None:
    with pytest.raises(InvalidSchemaError) as caught:
        resolve_pseudonym_key(settings, env="prod")
    assert caught.value.reason == reason
    details = [issue.detail for issue in caught.value.errors or ()]
    rendered = f"{caught.value} {caught.value.detail} {details}"
    assert "q" * 8 not in rendered


def test_key_settings_come_from_the_ns_auth_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NS_AUTH_PSEUDONYM_KEY", "r" * 40)
    monkeypatch.setenv("NS_AUTH_PSEUDONYM_KEY_REFERENCE", REFERENCE)
    settings = AuthSettings()
    assert "r" * 40 not in repr(settings)  # SecretStr
    assert resolve_pseudonym_key(settings, env="prod").reference == REFERENCE


def test_outside_local_without_a_key_authz_is_not_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_auth_env(monkeypatch)
    clock = FakeClock()
    composed = compose(
        configured_overrides(clock),
        builders=builders_with_stubs(),
        clock=clock,
        settings=Settings(env="prod", cloud=CloudName.COMMERCIAL),
    )
    status = composed.registry.get("authz")
    assert (status.state, status.reason) == ("failed", "pseudonym_key_missing")
    with composed.client() as client:
        response = client.get("/readyz")
    assert response.status_code == 503
    assert response.json()["dependencies"]["composition.authz.pseudonym_key_missing"] == (
        "unavailable"
    )


def test_local_composition_uses_the_dev_key(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_auth_env(monkeypatch)
    clock = FakeClock()
    composed = compose(configured_overrides(clock), builders=builders_with_stubs(), clock=clock)
    assert composed.registry.get("authz").state == "ok"
    with composed.client() as client:
        # ALICE's policy is stored under the dev-key pseudonym; a 200 proves the same key.
        response = client.get("/api/v1/me/domains", headers=composed.auth())
    assert response.status_code == 200


def test_the_dev_key_has_no_key_shaped_literal_in_source() -> None:
    source = Path(pseudonym_module.__file__).read_text("utf-8")
    assert not re.search(r"[0-9a-fA-F]{32,}", source)
    assert not re.search(r"[A-Za-z0-9+/]{32,}={0,2}", source)
