"""PRP-29 item 6: the operator grant script makes the composed API authorize the operator.

Needs the compose emulators (Cosmos on 127.0.0.1:8081); never starts or stops compose. The stand-in
token goes through the composed production path after validation: the ``ScopeDeriver`` over the
Cosmos policy store with the settings-resolved pseudonym key. Only the token validator is a test
stand-in (``conftest.py``).
"""

from __future__ import annotations

import importlib.util
import os
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from types import ModuleType

import pytest
from fastapi.testclient import TestClient
from neurosphere_api.app import create_app
from neurosphere_api.runtime import CompositionOverrides, compose_app
from neurosphere_core.auth.jwt import JwtValidator
from neurosphere_core.cloud import Settings

pytestmark = pytest.mark.integration

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "sandbox" / "sbx_grant_operator.py"
LOOPBACK = "http://127.0.0.1:8081"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("sbx_grant_operator_integration", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def loopback_endpoint(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Listed first in the test so ``emulator_env`` keeps this 127.0.0.1 endpoint."""
    monkeypatch.setenv("NS_COSMOS_ENDPOINT", LOOPBACK)
    yield


def test_grant_gives_operator_the_sandbox_domains(
    loopback_endpoint: None,
    real_stack_client: TestClient,
    stand_in_token: Callable[..., dict[str, str]],
    stand_in_validator: JwtValidator,
) -> None:
    mod = _load()
    oid = str(uuid.uuid4())
    headers = stand_in_token(oid)

    # Unknown principal: authenticated but no policy, so no readable domain.
    assert real_stack_client.get("/api/v1/me/domains", headers=headers).status_code == 403

    env = dict(os.environ)
    argv = ["--object-id", oid, "--role", "viewer", "--tenant-id", os.environ["NS_AUTH_TENANT_ID"]]
    assert mod.main(argv, env=env) == 0
    expected = set(
        mod.sandbox_domain_ids(seed=1, profile="tiny", cloud="commercial", customer="synthco")
    )
    assert expected

    # The first app cached "no policy"; a fresh composition sees the grant at once.
    settings = Settings()
    app = create_app(settings)
    compose_app(app, settings, CompositionOverrides(authenticator=stand_in_validator))
    with TestClient(app, raise_server_exceptions=False) as fresh:
        response = fresh.get("/api/v1/me/domains", headers=headers)
    assert response.status_code == 200, response.text
    assert {item["domain_id"] for item in response.json()["items"]} == expected

    # Idempotent: a second run succeeds without error.
    assert mod.main(argv, env=env) == 0
