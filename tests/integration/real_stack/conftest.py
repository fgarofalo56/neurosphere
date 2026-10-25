"""Shared fixtures of the real-stack suite (TEST CODE ONLY).

* ``compose_stack`` (session): asserts the compose emulators answer (Cosmos, Event Hubs, Blob).
  It never starts, stops or restarts compose; the project name is shared across worktrees, so
  the orchestrator (or item 11's suite) brings the stack up: ``docker compose up -d --wait``.
* ``emulator_env``: ``NS_ENV=local`` plus the emulator client variables. The Cosmos key and the
  Blob connection string are assembled at runtime (the emulators ignore the key value); an
  already-exported ``NS_COSMOS_ENDPOINT`` is kept.
* ``stand_in_issuer`` / ``stand_in_token``: an in-memory test issuer for the configured tenant.
  Tokens are minted with the wall clock and validated by a test-only validator that is handed
  to ``compose_app`` through ``CompositionOverrides``. Everything AFTER token validation is the
  composed production path: the ``ScopeDeriver`` over the Cosmos policy store, the Cosmos
  revocation checker and the settings-resolved pseudonym key (the local dev key unless
  ``NS_AUTH_PSEUDONYM_KEY`` is set). Never used by compose or ``main``.
* ``composed_app`` / ``real_stack_client``: ``create_app`` + ``compose_app`` with the default
  builders and only the authenticator overridden; the client runs the lifespan, which bootstraps
  the registry containers on the emulator (``NS_ENV=local``).

Every test module here sets ``pytestmark = pytest.mark.integration``.
"""

from __future__ import annotations

import asyncio
import base64
import os
import time
from collections.abc import Callable, Iterator
from typing import Any, Final

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from neurosphere_api.app import create_app
from neurosphere_api.health.probes import probes_from_env, run_probes
from neurosphere_api.runtime import CompositionOverrides, compose_app
from neurosphere_core.auth.jwt import DevIssuer, JwksCache, JwtConfig, JwtValidator, entra_jwks_uri
from neurosphere_core.cloud import CloudName, Settings

#: Used when ``NS_AUTH_TENANT_ID`` is not exported: a fixed, non-routable test tenant.
DEFAULT_TEST_TENANT: Final = "5e1c0a7d-2b3f-4c8e-9a1d-7f6e5d4c3b2a"
DEFAULT_TEST_AUDIENCE: Final = "api://neurosphere-real-stack-tests"
_STAND_IN_KID: Final = "real-stack-stand-in"


def real_stack_tenant() -> str:
    return os.environ.get("NS_AUTH_TENANT_ID") or DEFAULT_TEST_TENANT


def real_stack_audience() -> str:
    configured = os.environ.get("NS_AUTH_AUDIENCES", "")
    first = next((a.strip() for a in configured.split(",") if a.strip()), "")
    return first or DEFAULT_TEST_AUDIENCE


@pytest.fixture(scope="session")
def compose_stack() -> None:
    """Fail fast (with the fix) when the emulators are not up; never touch compose."""
    results = asyncio.run(run_probes(probes_from_env(dict(os.environ)), 5.0))
    down = sorted(name for name, code in results.items() if code != "ok")
    if down:
        pytest.fail(
            f"emulators not reachable: {', '.join(down)}; run `docker compose up -d --wait`"
        )


@pytest.fixture
def emulator_env(monkeypatch: pytest.MonkeyPatch, compose_stack: None) -> None:
    monkeypatch.setenv("NS_ENV", "local")
    monkeypatch.setenv(
        "NS_COSMOS_ENDPOINT", os.environ.get("NS_COSMOS_ENDPOINT", "http://localhost:8081")
    )
    monkeypatch.setenv("NS_COSMOS_KEY", base64.b64encode(b"emulator-ignores-this").decode())
    monkeypatch.setenv("NS_BLOB_CONNECTION_STRING", "UseDevelopmentStorage=true")
    monkeypatch.setenv("NS_AUTH_TENANT_ID", real_stack_tenant())
    monkeypatch.setenv("NS_AUTH_AUDIENCES", real_stack_audience())


class _UnrelatedEntraKeys:
    """Entra JWKS stand-in with one unrelated key: only the stand-in issuer's kid validates."""

    def __init__(self, url: str, tenant_id: str) -> None:
        self._url = url
        self._jwks = DevIssuer(Settings(env="local"), tenant_id=tenant_id, kid="unrelated").jwks()

    @property
    def url(self) -> str:
        return self._url

    async def fetch(self) -> Any:
        return self._jwks


@pytest.fixture(scope="session")
def stand_in_issuer() -> DevIssuer:
    return DevIssuer(Settings(env="local"), tenant_id=real_stack_tenant(), kid=_STAND_IN_KID)


@pytest.fixture
def stand_in_validator(stand_in_issuer: DevIssuer) -> JwtValidator:
    tenant = real_stack_tenant()
    config = JwtConfig(
        env="local",
        cloud=CloudName.COMMERCIAL,
        tenant_id=tenant,
        audiences=(real_stack_audience(),),
        dev_issuer=stand_in_issuer.trust(),
    )
    fetcher = _UnrelatedEntraKeys(entra_jwks_uri(CloudName.COMMERCIAL, tenant), tenant)
    return JwtValidator(config, JwksCache(fetcher, ttl_seconds=3600))


@pytest.fixture
def stand_in_token(stand_in_issuer: DevIssuer) -> Callable[..., dict[str, str]]:
    """``stand_in_token(object_id, **claims)`` -> an ``Authorization`` header for the operator."""

    def mint(object_id: str, **extra: Any) -> dict[str, str]:
        token = stand_in_issuer.mint(
            audience=real_stack_audience(),
            object_id=object_id,
            now=time.time(),
            extra=extra or None,
        )
        return {"Authorization": f"Bearer {token}"}

    return mint


@pytest.fixture
def composed_app(emulator_env: None, stand_in_validator: JwtValidator) -> FastAPI:
    settings = Settings()
    app = create_app(settings)
    compose_app(app, settings, CompositionOverrides(authenticator=stand_in_validator))
    return app


@pytest.fixture
def real_stack_client(composed_app: FastAPI) -> Iterator[TestClient]:
    with TestClient(composed_app, raise_server_exceptions=False) as client:
        yield client
