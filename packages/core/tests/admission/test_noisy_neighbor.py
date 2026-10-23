"""Simulated load: skew, hot key and permission-heavy multi-domain principals (PRD section 3)."""

from __future__ import annotations

import statistics

from neurosphere_core.admission import (
    QuotaLimit,
    QuotaPolicy,
    TokenBucketLimiter,
    derive_limiter_key,
)
from neurosphere_core.errors import RateLimitedError

from .admission_helpers import FakeClock, make_scope

RATE = 10.0
BURST = 20
TICK = 0.1  # seconds per simulated tick
TICKS = 100  # 10 simulated seconds
OTHERS = 8


def _limiter() -> tuple[TokenBucketLimiter, FakeClock]:
    clock = FakeClock()
    policy = QuotaPolicy(default=QuotaLimit(rate_per_second=RATE, burst=BURST))
    return TokenBucketLimiter(policy, clock=clock), clock


def test_hot_domain_at_20x_median_is_throttled_others_unaffected() -> None:
    limiter, clock = _limiter()
    keys = {f"d{n}": derive_limiter_key(make_scope((f"d{n}",))) for n in range(OTHERS)}
    hot = derive_limiter_key(make_scope(("hot",)))
    normal_per_tick = 0.5 * RATE * TICK  # half of quota: 0.5 req/tick
    median_rate = normal_per_tick / TICK  # req/s
    hot_per_tick = int(20 * median_rate * TICK)  # 20x the median -> 10 req/tick

    admitted = dict.fromkeys([*keys, "hot"], 0)
    rejected = dict.fromkeys([*keys, "hot"], 0)
    carry = dict.fromkeys(keys, 0.0)
    max_retry = 0
    for _ in range(TICKS):
        for _ in range(hot_per_tick):
            try:
                limiter.admit(hot)
                admitted["hot"] += 1
            except RateLimitedError as exc:
                rejected["hot"] += 1
                max_retry = max(max_retry, exc.retry_after_seconds or 0)
        for name, key in keys.items():
            carry[name] += normal_per_tick
            while carry[name] >= 1.0:
                carry[name] -= 1.0
                try:
                    limiter.admit(key)
                    admitted[name] += 1
                except RateLimitedError:
                    rejected[name] += 1
        clock.advance(TICK)

    assert all(rejected[n] == 0 for n in keys), rejected
    assert all(admitted[n] == 50 for n in keys), admitted
    assert rejected["hot"] > 0
    assert max_retry >= 1
    # hot domain admitted no more than burst + rate * duration
    assert admitted["hot"] <= BURST + RATE * TICK * TICKS
    assert statistics.median(admitted[n] for n in keys) == 50


def test_permission_heavy_principal_cannot_multiply_or_starve() -> None:
    limiter, clock = _limiter()
    big_domains = tuple(f"x{n}" for n in range(40))
    big = make_scope(big_domains, principal="big")
    victim = make_scope(("finance",), principal="vic")

    # No route domain: all 40 domains share ONE per-scope bucket (no 40x multiplier).
    big_key = derive_limiter_key(big)
    admitted = 0
    for _ in range(1000):
        try:
            limiter.admit(big_key)
            admitted += 1
        except RateLimitedError:
            pass
    assert admitted == BURST

    # Choosing a route domain outside the scope does not open a fresh bucket either.
    outside = derive_limiter_key(big, "commercial:contoso:catalog:domain:elsewhere")
    assert outside == big_key

    # The victim is unaffected, and refill is independent over time.
    victim_key = derive_limiter_key(victim)
    for _ in range(BURST):
        limiter.admit(victim_key)
    clock.advance(1.0)
    limiter.admit(victim_key)


def test_multi_domain_principal_with_route_domains_charges_each_domain() -> None:
    limiter, _ = _limiter()
    multi = make_scope(("a", "b"), principal="m")
    key_a = derive_limiter_key(multi, "commercial:contoso:catalog:domain:a")
    key_b = derive_limiter_key(multi, "commercial:contoso:catalog:domain:b")
    for _ in range(BURST):
        limiter.admit(key_a)
    try:
        limiter.admit(key_a)
        raise AssertionError("domain a should be exhausted")
    except RateLimitedError:
        pass
    limiter.admit(key_b)  # b has its own bucket
