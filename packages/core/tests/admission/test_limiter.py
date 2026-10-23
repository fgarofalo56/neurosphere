"""Limiter, quota config, keying and middleware behaviour (deterministic clock, no sleeps)."""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
from pathlib import Path
from typing import Any

import pytest
from neurosphere_core.admission import (
    DEFAULT_LIMIT,
    QuotaLimit,
    QuotaPolicy,
    TokenBucketLimiter,
    admission_middleware,
    derive_limiter_key,
    load_quota_policy,
    parse_quota_policy,
)
from neurosphere_core.errors import RateLimitedError
from neurosphere_core.scope import IdentityScope
from pydantic import ValidationError

from .admission_helpers import FakeClock, domain_id, make_scope

RETAIL = domain_id("retail")
FINANCE = domain_id("finance")


def _policy(rate: float = 1.0, burst: int = 3, **overrides: QuotaLimit) -> QuotaPolicy:
    return QuotaPolicy(
        default=QuotaLimit(rate_per_second=rate, burst=burst),
        domains={domain_id(k): v for k, v in overrides.items()},
    )


def test_burst_then_throttled_with_retry_hint_then_refill() -> None:
    clock = FakeClock()
    limiter = TokenBucketLimiter(_policy(rate=2.0, burst=3), clock=clock)
    key = derive_limiter_key(make_scope(("retail",)))
    for _ in range(3):
        limiter.admit(key)
    with pytest.raises(RateLimitedError) as info:
        limiter.admit(key)
    assert info.value.code == "rate_limited"
    assert info.value.retry_after_seconds == 1
    assert info.value.retryable
    clock.advance(0.5)  # one token back at 2/s
    limiter.admit(key)
    with pytest.raises(RateLimitedError):
        limiter.admit(key)


def test_retry_hint_scales_with_rate() -> None:
    clock = FakeClock()
    limiter = TokenBucketLimiter(_policy(rate=0.1, burst=1), clock=clock)
    key = derive_limiter_key(make_scope(("retail",)))
    limiter.admit(key)
    with pytest.raises(RateLimitedError) as info:
        limiter.admit(key)
    assert info.value.retry_after_seconds == 10


def test_cost_above_burst_is_refused_not_deferred() -> None:
    limiter = TokenBucketLimiter(_policy(burst=3), clock=FakeClock())
    key = derive_limiter_key(make_scope(("retail",)))
    with pytest.raises(RateLimitedError) as info:
        limiter.admit(key, cost=4)
    assert info.value.reason == "cost_exceeds_burst"


def test_per_domain_override_applies() -> None:
    clock = FakeClock()
    policy = _policy(rate=1.0, burst=1, retail=QuotaLimit(rate_per_second=1.0, burst=5))
    limiter = TokenBucketLimiter(policy, clock=clock)
    retail = derive_limiter_key(make_scope(("retail",)))
    finance = derive_limiter_key(make_scope(("finance",)))
    for _ in range(5):
        limiter.admit(retail)
    limiter.admit(finance)
    with pytest.raises(RateLimitedError):
        limiter.admit(finance)


def test_backpressure_signal_levels() -> None:
    limiter = TokenBucketLimiter(_policy(rate=1.0, burst=10), clock=FakeClock())
    key = derive_limiter_key(make_scope(("retail",)))
    levels = [limiter.admit(key).level for _ in range(10)]
    assert levels[0] == "ok"
    assert levels[8] == "elevated"
    assert levels[9] == "saturated"
    assert limiter.signal(key).retry_after_seconds >= 1


@pytest.mark.parametrize(
    "document",
    [
        None,
        {"default": {"rate_per_second": 0, "burst": 1}},
        {"default": {"rate_per_second": -1, "burst": 1}},
        {"default": {"rate_per_second": float("inf"), "burst": 1}},
        {"default": {"rate_per_second": float("nan"), "burst": 1}},
        {"default": {"rate_per_second": 1, "burst": 0}},
        {"default": {"rate_per_second": 1, "burst": None}},
        {"default": {"rate_per_second": 1, "burst": 1}, "unlimited": True},
        {"default": {"rate_per_second": 1, "burst": 1, "unlimited": True}},
        {"default": None},
        {},
    ],
)
def test_bad_or_missing_config_falls_back_to_default_with_warning(
    document: dict[str, Any] | None, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING):
        policy = parse_quota_policy(document)
    assert policy.default == DEFAULT_LIMIT
    assert policy.domains == {}
    assert any("conservative default" in r.getMessage() for r in caplog.records)


def test_no_unlimited_expressible() -> None:
    with pytest.raises(ValidationError):
        QuotaLimit(rate_per_second=float("inf"), burst=1)
    with pytest.raises(ValidationError):
        QuotaLimit(rate_per_second=1, burst=10**12)
    with pytest.raises(ValidationError):
        QuotaPolicy.model_validate({"default": {"rate_per_second": 1, "burst": 1}, "x": 1})
    assert DEFAULT_LIMIT.rate_per_second > 0
    assert DEFAULT_LIMIT.burst < 1000


def test_load_policy_file_and_missing_file(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    good = tmp_path / "quota.json"
    good.write_text(
        json.dumps(
            {
                "default": {"rate_per_second": 5, "burst": 7},
                "domains": {RETAIL: {"rate_per_second": 50, "burst": 100}},
            }
        ),
        encoding="utf-8",
    )
    policy = load_quota_policy(good)
    assert policy.limit_for(RETAIL).burst == 100
    assert policy.limit_for(FINANCE).burst == 7

    yml = tmp_path / "quota.yaml"
    yml.write_text("default:\n  rate_per_second: 3\n  burst: 4\n", encoding="utf-8")
    assert load_quota_policy(yml).default.burst == 4

    with caplog.at_level(logging.WARNING):
        assert load_quota_policy(tmp_path / "absent.json").default == DEFAULT_LIMIT
        assert load_quota_policy(None).default == DEFAULT_LIMIT
    assert sum("conservative default" in r.getMessage() for r in caplog.records) >= 2


def test_keying_rules() -> None:
    single = make_scope(("retail",))
    assert derive_limiter_key(single).domain == RETAIL
    # a route domain outside the scope is not trusted: charged to the scope bucket
    spoof = derive_limiter_key(single, FINANCE)
    assert spoof.domain is None
    assert spoof.scope_hash == single.scope_hash

    multi = make_scope(("retail", "finance"))
    assert derive_limiter_key(multi, FINANCE).domain == FINANCE
    fallback = derive_limiter_key(multi)
    assert fallback.domain is None
    assert fallback.scope_hash == multi.scope_hash

    empty = make_scope(())
    assert derive_limiter_key(empty).scope_hash == empty.scope_hash


def test_keys_do_not_cross_customers_or_clouds() -> None:
    a = derive_limiter_key(make_scope(("retail",), customer="contoso"))
    b = derive_limiter_key(make_scope(("retail",), customer="fabrikam"))
    c = derive_limiter_key(make_scope(("retail",), cloud="government"))
    assert len({a, b, c}) == 3


async def test_concurrent_tasks_never_exceed_burst() -> None:
    limiter = TokenBucketLimiter(_policy(rate=1.0, burst=25), clock=FakeClock())
    key = derive_limiter_key(make_scope(("retail",)))
    admitted = 0

    async def one() -> None:
        nonlocal admitted
        await asyncio.sleep(0)
        try:
            limiter.admit(key)
        except RateLimitedError:
            return
        admitted += 1

    await asyncio.gather(*(one() for _ in range(200)))
    assert admitted == 25


def test_idle_bucket_eviction_bounds_memory() -> None:
    clock = FakeClock()
    limiter = TokenBucketLimiter(_policy(rate=10.0, burst=1), clock=clock, max_buckets=3)
    for n in range(3):
        limiter.admit(derive_limiter_key(make_scope((f"d{n}",))))
    clock.advance(10)
    limiter.admit(derive_limiter_key(make_scope(("d9",))))  # triggers eviction of refilled ones
    assert len(limiter._buckets) == 1  # pyright: ignore[reportPrivateUsage]


# ---- middleware -------------------------------------------------------------------------


class _Capture:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []

    async def send(self, message: dict[str, Any]) -> None:
        self.messages.append(message)

    @property
    def status(self) -> int:
        return int(self.messages[0]["status"])

    @property
    def headers(self) -> dict[str, str]:
        return {k.decode(): v.decode() for k, v in self.messages[0]["headers"]}


async def _ok_app(scope: Any, receive: Any, send: Any) -> None:
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"ok"})


async def _recv() -> dict[str, Any]:
    return {"type": "http.request"}


async def _call(
    app: Any, scope: IdentityScope | None, headers: list[tuple[bytes, bytes]]
) -> _Capture:
    state: dict[str, Any] = {} if scope is None else {"identity_scope": scope}
    asgi: dict[str, Any] = {"type": "http", "path": "/x", "headers": headers, "state": state}
    cap = _Capture()
    await app(asgi, _recv, cap.send)
    return cap


async def test_middleware_renders_problem_json_with_retry_after() -> None:
    limiter = TokenBucketLimiter(_policy(rate=1.0, burst=1), clock=FakeClock())
    app = admission_middleware(limiter)(_ok_app)
    scope = make_scope(("retail",))
    first = await _call(app, scope, [])
    assert first.status == 200
    second = await _call(app, scope, [])
    assert second.status == 429
    assert second.headers["content-type"] == "application/problem+json"
    assert second.headers["retry-after"] == "1"
    body = json.loads(second.messages[1]["body"])
    assert body["code"] == "rate_limited"
    assert body["retry_after_seconds"] == 1
    assert body["retryable"] is True


async def test_middleware_without_scope_is_401() -> None:
    limiter = TokenBucketLimiter(_policy(), clock=FakeClock())
    app = admission_middleware(limiter)(_ok_app)
    cap = await _call(app, None, [])
    assert cap.status == 401


async def test_spoofed_domain_header_is_ignored() -> None:
    limiter = TokenBucketLimiter(_policy(rate=1.0, burst=2), clock=FakeClock())
    app = admission_middleware(limiter)(_ok_app)
    attacker = make_scope(("retail",), principal="atk")
    victim = make_scope(("finance",), principal="vic")
    spoof = [
        (b"x-domain-id", FINANCE.encode()),
        (b"x-ns-domain", FINANCE.encode()),
    ]
    assert (await _call(app, attacker, spoof)).status == 200
    assert (await _call(app, attacker, spoof)).status == 200
    # attacker's bucket (retail) is exhausted despite the finance header...
    assert (await _call(app, attacker, spoof)).status == 429
    # ...and the victim's finance bucket was never charged.
    assert limiter.signal(derive_limiter_key(victim)).utilization == 0.0
    assert limiter.signal(derive_limiter_key(attacker)).level == "saturated"
    assert (await _call(app, victim, [])).status == 200


async def test_route_domain_outside_scope_not_trusted() -> None:
    limiter = TokenBucketLimiter(_policy(rate=1.0, burst=1), clock=FakeClock())
    app = admission_middleware(limiter, route_domain_of=lambda _s: FINANCE)(_ok_app)
    attacker = make_scope(("retail",), principal="atk")
    assert (await _call(app, attacker, [])).status == 200
    assert (await _call(app, attacker, [])).status == 429
    assert limiter.signal(derive_limiter_key(make_scope(("finance",)))).utilization == 0.0


async def test_backpressure_header_when_elevated() -> None:
    limiter = TokenBucketLimiter(_policy(rate=1.0, burst=2), clock=FakeClock())
    app = admission_middleware(limiter)(_ok_app)
    scope = make_scope(("retail",))
    first = await _call(app, scope, [])
    assert "x-ns-backpressure" not in first.headers
    second = await _call(app, scope, [])
    assert second.headers["x-ns-backpressure"] == "saturated"


def test_error_signature_is_bound_correctly() -> None:
    # guards the taxonomy contract this module relies on, without a wrong-signature call
    inspect.signature(RateLimitedError).bind(3, "detail", reason="r")
