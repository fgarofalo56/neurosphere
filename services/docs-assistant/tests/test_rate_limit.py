from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from docs_assistant.app import create
from docs_assistant.config import Settings
from docs_assistant.ratelimit import RateLimiter


def _client(repo: Path, **kw: object) -> TestClient:
    settings = Settings(site_dir=repo / "site", **kw)  # type: ignore[arg-type]
    return TestClient(create(settings))


def test_beyond_limit_returns_429_rate_limited(repo: Path) -> None:
    client = _client(repo, rate_limit_requests=3, rate_limit_window_seconds=60)
    for _ in range(3):
        assert client.post("/ask", json={"question": "docs site tool"}).status_code == 200
    resp = client.post("/ask", json={"question": "docs site tool"})
    assert resp.status_code == 429
    assert resp.json()["error"]["code"] == "rate_limited"
    assert int(resp.headers["Retry-After"]) >= 1
    # Health checks are not rate limited.
    assert client.get("/healthz").status_code == 200


def test_sliding_window_recovers() -> None:
    now = [0.0]
    limiter = RateLimiter(2, 10, clock=lambda: now[0])
    assert limiter.check("a") is None
    assert limiter.check("a") is None
    assert limiter.check("a") == 10
    assert limiter.check("b") is None  # other clients are independent
    now[0] = 10.1
    assert limiter.check("a") is None


def test_forwarded_for_ignored_by_default(repo: Path) -> None:
    client = _client(repo, rate_limit_requests=1)
    body = {"question": "docs site tool"}
    assert client.post("/ask", json=body, headers={"X-Forwarded-For": "1.1.1.1"}).status_code == 200
    # A spoofed header must not mint a fresh bucket.
    assert client.post("/ask", json=body, headers={"X-Forwarded-For": "2.2.2.2"}).status_code == 429


def test_forwarded_for_used_when_proxy_trusted(repo: Path) -> None:
    client = _client(repo, rate_limit_requests=1, trusted_proxy_hops=1)
    body = {"question": "docs site tool"}
    ok = client.post("/ask", json=body, headers={"X-Forwarded-For": "spoof, 1.1.1.1"})
    assert ok.status_code == 200
    again = client.post("/ask", json=body, headers={"X-Forwarded-For": "other, 1.1.1.1"})
    assert again.status_code == 429
    other = client.post("/ask", json=body, headers={"X-Forwarded-For": "x, 2.2.2.2"})
    assert other.status_code == 200


def test_oversized_body_rejected_413(repo: Path) -> None:
    client = _client(repo, max_body_bytes=256)
    resp = client.post("/ask", json={"question": "x" * 1000})
    assert resp.status_code == 413
    assert resp.json()["error"]["code"] == "request_too_large"


def test_overlong_question_and_bad_shape_rejected_422(repo: Path) -> None:
    client = _client(repo, max_question_chars=20)
    long_q = client.post("/ask", json={"question": "y" * 21})
    assert long_q.status_code == 422
    assert long_q.json()["error"]["code"] == "invalid_request"
    assert client.post("/ask", json={"question": "ok", "extra": 1}).status_code == 422
    assert client.post("/ask", content=b"not json").status_code == 422


def test_only_read_routes_exist(repo: Path) -> None:
    client = _client(repo)
    app_routes = getattr(client.app, "routes")  # noqa: B009 - ASGIApp type hides .routes
    routes = {(m, getattr(r, "path")) for r in app_routes for m in getattr(r, "methods", set())}  # noqa: B009
    assert routes == {("GET", "/healthz"), ("POST", "/ask")}
    for method in ("put", "delete", "patch"):
        assert getattr(client, method)("/ask").status_code == 405
    assert client.get("/openapi.json").status_code == 404


def test_prompt_text_is_not_logged(repo: Path, caplog) -> None:
    client = _client(repo)
    secret_q = "uniquequestionmarker about the docs site tool"
    with caplog.at_level("DEBUG", logger="docs_assistant"):
        client.post("/ask", json={"question": secret_q})
    assert "uniquequestionmarker" not in caplog.text
    assert "len=" in caplog.text
