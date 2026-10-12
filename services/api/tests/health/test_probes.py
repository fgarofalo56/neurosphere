from __future__ import annotations

import asyncio
import json
from typing import cast

import pytest
from fastapi.testclient import TestClient
from neurosphere_api.app import create_app
from neurosphere_api.health import (
    DependencyProbe,
    ReasonCode,
    TcpProbe,
    probes_from_env,
    run_probes,
    timeout_from_env,
)
from neurosphere_core.cloud import Settings

FAKE_SECRET = "AccountKey=c2VjcmV0LXZhbHVl;SharedAccessSignature=sig%3Dabc"  # noqa: S105
FAKE_HOST = "secret-account.documents.example.invalid"


class FakeProbe:
    def __init__(self, name: str, outcome: ReasonCode | BaseException) -> None:
        self.name = name
        self._outcome = outcome

    async def check(self) -> ReasonCode:
        if isinstance(self._outcome, BaseException):
            raise self._outcome
        return cast(ReasonCode, self._outcome)


class HangingProbe:
    name = "eventhubs"

    async def check(self) -> ReasonCode:
        await asyncio.sleep(30)
        return "ok"


def _client(probes: list[DependencyProbe], timeout: float = 0.2) -> TestClient:
    app = create_app(Settings())
    app.state.health_probes = probes
    app.state.health_timeout = timeout
    return TestClient(app)


def test_healthz_is_200_even_when_dependencies_fail() -> None:
    client = _client([FakeProbe("cosmos", ConnectionRefusedError())])
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readyz_all_ok() -> None:
    client = _client([FakeProbe("cosmos", "ok"), FakeProbe("blob", "ok")])
    response = client.get("/readyz")
    assert response.status_code == 200
    assert response.json() == {"status": "ready", "dependencies": {"cosmos": "ok", "blob": "ok"}}


def test_readyz_timeout_is_503_with_reason() -> None:
    client = _client([FakeProbe("cosmos", "ok"), HangingProbe()], timeout=0.1)
    response = client.get("/readyz")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    assert body["dependencies"] == {"cosmos": "ok", "eventhubs": "timeout"}


def test_readyz_refused_is_503_with_reason() -> None:
    client = _client([FakeProbe("cosmos", ConnectionRefusedError()), FakeProbe("blob", "ok")])
    response = client.get("/readyz")
    assert response.status_code == 503
    assert response.json()["dependencies"] == {"cosmos": "connection_refused", "blob": "ok"}


def test_readyz_generic_failure_is_unavailable() -> None:
    client = _client([FakeProbe("blob", RuntimeError("boom"))])
    response = client.get("/readyz")
    assert response.status_code == 503
    assert response.json()["dependencies"] == {"blob": "unavailable"}


def test_readyz_unknown_probe_result_fails_closed() -> None:
    bad = FakeProbe("blob", "healthy-ish")  # type: ignore[arg-type]
    assert asyncio.run(run_probes([bad], 1.0)) == {"blob": "unavailable"}


def test_readyz_no_probes_fails_closed() -> None:
    assert _client([]).get("/readyz").status_code == 503


def test_probes_run_concurrently() -> None:
    async def go() -> float:
        loop = asyncio.get_running_loop()
        start = loop.time()
        await run_probes([HangingProbe(), HangingProbe(), HangingProbe()], 0.3)
        return loop.time() - start

    # Three 0.3s timeouts in series would take ~0.9s.
    assert asyncio.run(go()) < 0.7


def test_failure_body_leaks_nothing() -> None:
    errors: list[BaseException] = [
        ConnectionRefusedError(f"connect to {FAKE_HOST}:443 failed {FAKE_SECRET}"),
        RuntimeError(f"https://{FAKE_HOST}/?{FAKE_SECRET}"),
        TimeoutError(FAKE_SECRET),
    ]
    probes: list[DependencyProbe] = [FakeProbe(f"dep{i}", e) for i, e in enumerate(errors)]
    response = _client(probes).get("/readyz")
    assert response.status_code == 503
    text = json.dumps(response.json())
    for needle in (FAKE_SECRET, FAKE_HOST, "AccountKey", "https://", "SharedAccessSignature"):
        assert needle not in text
    assert set(response.json()["dependencies"].values()) <= {
        "ok",
        "timeout",
        "connection_refused",
        "unavailable",
    }


def test_real_tcp_probe_reports_refused_for_closed_port() -> None:
    probe = TcpProbe("blob", "127.0.0.1:1")
    # Windows retries refused connects, so a short timeout may win; never "ok" either way.
    result = asyncio.run(run_probes([probe], 1.0))
    assert result["blob"] in {"connection_refused", "unavailable", "timeout"}


def test_timeout_and_endpoint_env_parsing() -> None:
    assert timeout_from_env({}) == 2.0
    assert timeout_from_env({"NS_PROBE_TIMEOUT_SECONDS": "0.5"}) == 0.5
    assert timeout_from_env({"NS_PROBE_TIMEOUT_SECONDS": "nope"}) == 2.0
    assert timeout_from_env({"NS_PROBE_TIMEOUT_SECONDS": "-1"}) == 2.0
    names = [p.name for p in probes_from_env({"NS_PROBE_BLOB_HOSTPORT": "azurite:10000"})]
    assert names == ["cosmos", "eventhubs", "blob"]


def test_bad_hostport_rejected() -> None:
    with pytest.raises(ValueError):
        TcpProbe("blob", "no-port")
