"""Token-bucket limiter keyed by the server-derived domain (PRP-21 item 2).

Keying rules (fail closed, never unkeyed):

* The caller never supplies the domain. :func:`derive_limiter_key` takes the server-side
  ``IdentityScope`` and, optionally, a route-resolved domain (for example a path segment).
* A route domain is honoured only if it is in ``scope.allowed_domains``; the bucket is then
  ``(cloud, customer, domain)`` using that domain's quota.
* Otherwise (no route domain, an unauthorised one, or several allowed domains and no way to
  choose) the request is charged to a per-scope bucket keyed by ``scope_hash`` with the default
  limit. A principal with many domains therefore cannot multiply its throughput by varying the
  route, and cannot starve a domain it is not charged to.

The clock is injectable (monotonic seconds); the critical section has no awaits, so a plain
lock makes the limiter safe for concurrent asyncio tasks and threads alike.
"""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from neurosphere_core.admission.config import QuotaLimit, QuotaPolicy
from neurosphere_core.errors import RateLimitedError
from neurosphere_core.scope import IdentityScope

Clock = Callable[[], float]
BackpressureLevel = Literal["ok", "elevated", "saturated"]

ELEVATED_UTILIZATION = 0.8
_MAX_BUCKETS = 50_000


@dataclass(frozen=True, slots=True)
class LimiterKey:
    """Bucket identity. ``domain`` is None for the per-scope fallback bucket."""

    cloud: str
    customer_id: str
    domain: str | None
    scope_hash: str | None = None


@dataclass(frozen=True, slots=True)
class BackpressureSignal:
    """Advisory load signal for a bucket after an admitted request."""

    level: BackpressureLevel
    utilization: float
    retry_after_seconds: int


def derive_limiter_key(scope: IdentityScope, route_domain: str | None = None) -> LimiterKey:
    """Derive the bucket key from the server-side scope (see module docstring)."""
    allowed = scope.allowed_domains
    if route_domain is not None and route_domain in allowed:
        return LimiterKey(scope.cloud, scope.customer_id, route_domain)
    if route_domain is None and len(allowed) == 1:
        return LimiterKey(scope.cloud, scope.customer_id, allowed[0])
    return LimiterKey(scope.cloud, scope.customer_id, None, scope.scope_hash)


class _Bucket:
    __slots__ = ("stamp", "tokens")

    def __init__(self, tokens: float, stamp: float) -> None:
        self.tokens = tokens
        self.stamp = stamp


class TokenBucketLimiter:
    """Per-key token buckets with limits drawn from a :class:`QuotaPolicy`."""

    def __init__(
        self,
        policy: QuotaPolicy,
        *,
        clock: Clock = time.monotonic,
        max_buckets: int = _MAX_BUCKETS,
    ) -> None:
        self._policy = policy
        self._clock = clock
        self._max_buckets = max_buckets
        self._buckets: dict[LimiterKey, _Bucket] = {}
        self._lock = threading.Lock()

    def limit_for(self, key: LimiterKey) -> QuotaLimit:
        if key.domain is None:
            return self._policy.default
        return self._policy.limit_for(key.domain)

    def admit(self, key: LimiterKey, cost: int = 1) -> BackpressureSignal:
        """Charge ``cost`` tokens or raise :class:`RateLimitedError` with a retry hint."""
        limit = self.limit_for(key)
        if cost < 1 or cost > limit.burst:
            # A request larger than the burst can never succeed: refuse, do not wait forever.
            raise RateLimitedError(
                _retry_seconds(cost, 0.0, limit.rate_per_second),
                "request cost exceeds the domain burst allowance",
                reason="cost_exceeds_burst",
            )
        now = self._clock()
        with self._lock:
            bucket = self._refill(key, limit, now)
            if bucket.tokens < cost:
                retry = _retry_seconds(cost, bucket.tokens, limit.rate_per_second)
                raise RateLimitedError(
                    retry, "domain request quota exceeded", reason="domain_quota_exceeded"
                )
            bucket.tokens -= cost
            utilization = 1.0 - bucket.tokens / limit.burst
            tokens_left = bucket.tokens
        return _signal(utilization, tokens_left, limit)

    def signal(self, key: LimiterKey) -> BackpressureSignal:
        """Current backpressure for ``key`` without charging a token."""
        limit = self.limit_for(key)
        now = self._clock()
        with self._lock:
            bucket = self._refill(key, limit, now)
            tokens = bucket.tokens
        return _signal(1.0 - tokens / limit.burst, tokens, limit)

    def _refill(self, key: LimiterKey, limit: QuotaLimit, now: float) -> _Bucket:
        bucket = self._buckets.get(key)
        if bucket is None:
            if len(self._buckets) >= self._max_buckets:
                self._evict_idle(now)
            bucket = _Bucket(float(limit.burst), now)
            self._buckets[key] = bucket
            return bucket
        elapsed = max(0.0, now - bucket.stamp)
        bucket.tokens = min(float(limit.burst), bucket.tokens + elapsed * limit.rate_per_second)
        bucket.stamp = now
        return bucket

    def _evict_idle(self, now: float) -> None:
        # A bucket that would be full again is indistinguishable from a fresh one: safe to drop.
        for key in list(self._buckets):
            limit = self.limit_for(key)
            bucket = self._buckets[key]
            refilled = bucket.tokens + max(0.0, now - bucket.stamp) * limit.rate_per_second
            if refilled >= limit.burst:
                del self._buckets[key]


def _retry_seconds(cost: int, tokens: float, rate: float) -> int:
    return max(1, math.ceil((cost - tokens) / rate))


def _signal(utilization: float, tokens: float, limit: QuotaLimit) -> BackpressureSignal:
    level: BackpressureLevel
    if tokens < 1.0:
        level = "saturated"
    elif utilization >= ELEVATED_UTILIZATION:
        level = "elevated"
    else:
        level = "ok"
    retry = _retry_seconds(1, tokens, limit.rate_per_second) if level == "saturated" else 0
    return BackpressureSignal(level, round(utilization, 4), retry)
