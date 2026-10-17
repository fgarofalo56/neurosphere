"""Connector health, rate-limit, coverage and freshness reporting models and tracker.

Unknown is ``None``, never zero: a connector that has not measured freshness lag reports
``lag_ms=None``. Errors map to states by ``NeuroSphereError.code`` only; exception text is never
copied into a report (it could hold provider response bodies).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from neurosphere_core.errors import NeuroSphereError, RateLimitedError
from pydantic import BaseModel, ConfigDict, Field, model_validator

__all__ = [
    "Clock",
    "CoverageReport",
    "FreshnessReport",
    "HealthReport",
    "HealthState",
    "HealthTracker",
    "RateLimitStatus",
    "utc_now",
]

Clock = Callable[[], datetime]


def utc_now() -> datetime:
    return datetime.now(UTC)


class HealthState(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    RATE_LIMITED = "rate_limited"
    FAILING = "failing"
    UNKNOWN = "unknown"


class FreshnessReport(BaseModel):
    """Observed data lag. ``lag_ms`` is None when unknown (never 0)."""

    model_config = ConfigDict(extra="forbid")
    lag_ms: int | None = Field(default=None, ge=0)
    watermark: datetime | None = None
    observed_at: datetime | None = None


class CoverageReport(BaseModel):
    """What fraction of expected sources answered. Unknown counts are None."""

    model_config = ConfigDict(extra="forbid")
    expected_sources: int | None = Field(default=None, ge=0)
    answered_sources: int | None = Field(default=None, ge=0)
    partial: bool | None = None

    @model_validator(mode="after")
    def _answered_within_expected(self) -> CoverageReport:
        if (
            self.expected_sources is not None
            and self.answered_sources is not None
            and self.answered_sources > self.expected_sources
        ):
            raise ValueError("answered_sources exceeds expected_sources")
        return self

    @property
    def fraction(self) -> float | None:
        """answered / expected; None when unknown or nothing was expected."""
        if not self.expected_sources or self.answered_sources is None:
            return None
        return self.answered_sources / self.expected_sources


class RateLimitStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")
    limited: bool = False
    retry_after_seconds: int | None = Field(default=None, ge=0)
    limited_until: datetime | None = None
    remaining: int | None = Field(default=None, ge=0)


class HealthReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    state: HealthState
    checked_at: datetime
    rate_limit: RateLimitStatus
    freshness: FreshnessReport
    coverage: CoverageReport
    consecutive_failures: int = Field(ge=0)
    last_error_code: str | None = None


# Non-retryable codes (and unclassified errors) will not heal by waiting.
_HARD_FAILURES = frozenset(
    {"unauthorized", "forbidden", "invalid_schema", "capability_unavailable", "internal_error"}
)


class HealthTracker:
    """Accumulates call outcomes and renders a ``HealthReport``."""

    def __init__(self, *, clock: Clock = utc_now, failing_after: int = 3) -> None:
        self._clock = clock
        self._failing_after = failing_after
        self._seen = False
        self._failures = 0
        self._last_code: str | None = None
        self._rate_limited = False
        self._limited_until: datetime | None = None
        self._retry_after: int | None = None
        self._remaining: int | None = None
        self._freshness = FreshnessReport()
        self._coverage = CoverageReport()

    def record_success(
        self,
        *,
        freshness: FreshnessReport | None = None,
        coverage: CoverageReport | None = None,
        remaining: int | None = None,
    ) -> None:
        self._seen = True
        self._failures = 0
        self._last_code = None
        self._rate_limited = False
        self._limited_until = None
        self._retry_after = None
        self._remaining = remaining
        if freshness is not None:
            self._freshness = freshness
        if coverage is not None:
            self._coverage = coverage

    def record_error(self, exc: BaseException) -> None:
        self._seen = True
        self._failures += 1
        self._rate_limited = False
        if not isinstance(exc, NeuroSphereError):
            self._last_code = "internal_error"
            return
        self._last_code = exc.code
        if isinstance(exc, RateLimitedError):
            self._rate_limited = True
            self._remaining = 0
            self._retry_after = exc.retry_after_seconds
            if exc.retry_after_seconds is not None:
                self._limited_until = self._clock() + timedelta(seconds=exc.retry_after_seconds)

    def snapshot(self) -> HealthReport:
        now = self._clock()
        limited = self._rate_limited and (self._limited_until is None or now < self._limited_until)
        if not self._seen:
            state = HealthState.UNKNOWN
        elif limited:
            state = HealthState.RATE_LIMITED
        elif self._failures == 0:
            state = HealthState.HEALTHY
        elif self._failures >= self._failing_after or self._last_code in _HARD_FAILURES:
            state = HealthState.FAILING
        else:
            state = HealthState.DEGRADED
        return HealthReport(
            state=state,
            checked_at=now,
            rate_limit=RateLimitStatus(
                limited=limited,
                retry_after_seconds=self._retry_after if limited else None,
                limited_until=self._limited_until if limited else None,
                remaining=self._remaining,
            ),
            freshness=self._freshness,
            coverage=self._coverage,
            consecutive_failures=self._failures,
            last_error_code=self._last_code,
        )
