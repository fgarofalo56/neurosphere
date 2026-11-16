"""PRP-51: ``NS_READYZ_DETAIL=full|summary`` (default full)."""

from __future__ import annotations

from collections.abc import Mapping

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from neurosphere_api.health.probes import ReasonCode
from neurosphere_api.health.router import build_router, readyz_detail_from_env


class _Probe:
    def __init__(self, name: str, code: ReasonCode) -> None:
        self.name = name
        self._code: ReasonCode = code

    async def check(self) -> ReasonCode:
        return self._code


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(build_router())
    app.state.health_probes = (
        _Probe("cosmos", "ok"),
        _Probe("composition", "unavailable"),
        _Probe("composition.authz.tenant_id_missing", "unavailable"),
    )
    return TestClient(app)


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        ({}, "full"),
        ({"NS_READYZ_DETAIL": "full"}, "full"),
        ({"NS_READYZ_DETAIL": "summary"}, "summary"),
        ({"NS_READYZ_DETAIL": "weird"}, "summary"),
    ],
)
def test_detail_selection(env: Mapping[str, str], expected: str) -> None:
    assert readyz_detail_from_env(env) == expected


def test_default_is_full(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NS_READYZ_DETAIL", raising=False)
    response = _client().get("/readyz")
    assert response.status_code == 503
    assert set(response.json()["dependencies"]) == {
        "cosmos",
        "composition",
        "composition.authz.tenant_id_missing",
    }


def test_summary_returns_status_and_the_aggregate_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NS_READYZ_DETAIL", "summary")
    response = _client().get("/readyz")
    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "dependencies": {"composition": "unavailable"},
    }
