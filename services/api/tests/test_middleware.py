from __future__ import annotations

import pytest
from fastapi import APIRouter, FastAPI, Request
from fastapi.testclient import TestClient
from neurosphere_api.app import create_app
from neurosphere_core.cloud import Settings

VALID = "client-corr-1234"


def _client(max_bytes: int = 1024 * 1024) -> TestClient:
    router = APIRouter()

    @router.post("/echo")
    async def echo(request: Request) -> dict[str, int]:
        return {"n": len(await request.body())}

    @router.get("/state")
    def state(request: Request) -> dict[str, str]:
        return {"cid": request.state.correlation_id}

    app: FastAPI = create_app(
        Settings(env="local"), max_request_bytes=max_bytes, extra_routers={"/t": router}
    )
    return TestClient(app, raise_server_exceptions=False)


def test_valid_id_is_echoed_and_bound() -> None:
    r = _client().get("/t/state", headers={"x-correlation-id": VALID})
    assert r.headers["x-correlation-id"] == VALID
    assert r.json()["cid"] == VALID


@pytest.mark.parametrize("bad", ["short", "has space here", "x" * 65, "bad/chars/here!"])
def test_invalid_id_is_replaced(bad: str) -> None:
    r = _client().get("/t/state", headers={"x-correlation-id": bad})
    got = r.headers["x-correlation-id"]
    assert got != bad
    assert len(got) == 36


def test_generated_when_absent_on_404_and_422() -> None:
    c = _client()
    assert len(c.get("/missing").headers["x-correlation-id"]) == 36
    r = c.post("/t/state")  # 405 on a GET-only route
    assert r.status_code == 405
    assert len(r.headers["x-correlation-id"]) == 36


def test_span_attribute_set_when_recording() -> None:
    pytest.importorskip("opentelemetry.sdk.trace")
    from opentelemetry.sdk.trace import TracerProvider

    tracer = TracerProvider().get_tracer("t")
    with tracer.start_as_current_span("req") as span:
        _client().get("/t/state", headers={"x-correlation-id": VALID})
        attrs = getattr(span, "attributes", None)
        assert attrs is not None
        assert attrs["ns.correlation_id"] == VALID


def test_oversize_declared_length_rejected_with_correlation() -> None:
    r = _client(max_bytes=10).post("/t/echo", content=b"x" * 50)
    body = r.json()
    assert r.status_code == 422
    assert body["code"] == "invalid_schema"
    assert body["reason"] == "request_too_large"
    assert r.headers["x-correlation-id"] == body["correlation_id"]


def test_oversize_streamed_body_rejected() -> None:
    def chunks():
        yield b"x" * 8
        yield b"x" * 8

    r = _client(max_bytes=10).post("/t/echo", content=chunks())
    assert r.status_code in (400, 422)
    assert r.headers["x-correlation-id"]


def test_within_limit_passes() -> None:
    r = _client(max_bytes=10).post("/t/echo", content=b"x" * 10)
    assert r.status_code == 200
    assert r.json() == {"n": 10}
