from __future__ import annotations

import json
from collections.abc import Callable
from types import SimpleNamespace

import pytest
from neurosphere_api.ingest import IngestSettings
from neurosphere_api.ingest.limits import TokenBucketLimiter
from neurosphere_core.errors import RateLimitedError
from neurosphere_core.payload import DEFAULT_MAX_DEPTH

from .conftest import Harness, span, traces_doc

URL = "/v1/ingest/otlp/traces"
JSON = {"content-type": "application/json"}


def test_oversize_body_rejected_before_parse(
    make_harness: Callable[..., Harness], monkeypatch: pytest.MonkeyPatch
) -> None:
    h = make_harness(ingest=IngestSettings(max_body_bytes=200))

    def boom(*_a: object, **_k: object) -> None:
        raise AssertionError("json.loads must not run for an oversize body")

    monkeypatch.setattr("neurosphere_api.ingest.service.json", SimpleNamespace(loads=boom))
    body = json.dumps(traces_doc([span(attrs={"x": "y" * 500})]))
    resp = h.client.post(URL, content=body, headers={**JSON, **h.auth})
    assert resp.status_code == 422
    assert resp.json()["reason"] == "body_too_large"
    assert h.publisher.messages == []


def test_oversize_streamed_without_content_length(make_harness: Callable[..., Harness]) -> None:
    h = make_harness(ingest=IngestSettings(max_body_bytes=200))

    def chunks():
        yield b'{"resourceSpans":[],"pad":"' + b"a" * 150
        yield b"b" * 150 + b'"}'

    resp = h.client.post(URL, content=chunks(), headers={**JSON, **h.auth})
    assert resp.status_code == 422
    assert resp.json()["reason"] == "body_too_large"


def test_deep_nesting_rejected_before_parse(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_a: object, **_k: object) -> None:
        raise AssertionError("json.loads must not run for a too-deep body")

    monkeypatch.setattr("neurosphere_api.ingest.service.json", SimpleNamespace(loads=boom))
    depth = DEFAULT_MAX_DEPTH + 5
    body = '{"a":' * depth + "1" + "}" * depth
    resp = harness.client.post(URL, content=body, headers={**JSON, **harness.auth})
    assert resp.status_code == 422
    assert resp.json()["reason"] == "depth_exceeded"
    assert harness.publisher.messages == []


def test_malformed_json_and_media_type(harness: Harness) -> None:
    bad = harness.client.post(URL, content=b"{not json", headers={**JSON, **harness.auth})
    assert bad.status_code == 422
    assert bad.json()["reason"] == "malformed_json"
    wrong = harness.client.post(
        URL, content=b"{}", headers={"content-type": "application/x-protobuf", **harness.auth}
    )
    assert wrong.status_code == 422
    assert wrong.json()["reason"] == "unsupported_media_type"


def test_throttling_returns_rate_limited_with_retry_after(
    make_harness: Callable[..., Harness],
) -> None:
    now = [100.0]
    limiter = TokenBucketLimiter(1.0, 2, clock=lambda: now[0])
    h = make_harness(limiter=limiter)
    body = json.dumps(traces_doc([span()]))
    codes = [
        h.client.post(URL, content=body, headers={**JSON, **h.auth}).status_code for _ in range(3)
    ]
    assert codes == [202, 202, 429]
    resp = h.client.post(URL, content=body, headers={**JSON, **h.auth})
    assert resp.status_code == 429
    assert resp.json()["code"] == "rate_limited"
    assert int(resp.headers["retry-after"]) >= 1
    now[0] += 5.0  # refill
    assert h.client.post(URL, content=body, headers={**JSON, **h.auth}).status_code == 202


def test_token_bucket_unit() -> None:
    now = [0.0]
    limiter = TokenBucketLimiter(2.0, 1, clock=lambda: now[0])
    limiter.acquire("a")
    with pytest.raises(RateLimitedError) as err:
        limiter.acquire("a")
    assert err.value.retry_after_seconds == 1
    limiter.acquire("b")  # buckets are per producer
    now[0] = 0.5
    limiter.acquire("a")
