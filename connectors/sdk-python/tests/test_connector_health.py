"""Health state mapping, rate-limit status, coverage and freshness reporting."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from neurosphere_connector import (
    BaseConnector,
    CoverageReport,
    FreshnessReport,
    HealthState,
    build_manifest,
)
from neurosphere_contracts.connectors.v1.connector_manifest import ConnectorManifest, Granularity
from neurosphere_core.errors import (
    CapabilityUnavailableError,
    DependencyTransientError,
    InvalidSchemaError,
    RateLimitedError,
)

T0 = datetime(2026, 1, 1, tzinfo=UTC)
LEAK = "leaky-" + "provider-body-7731"


class _Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now


class _Demo(BaseConnector):
    @property
    def manifest(self) -> ConnectorManifest:
        return build_manifest(
            name="demo",
            version="0.1.0",
            capabilities=["telemetry_ingest", "health_reporting"],
            supported_clouds=["commercial"],
            granularity=Granularity(time_grain="event", subject_level="request"),
        )


def _raiser(exc: Exception):
    async def op() -> None:
        raise exc

    return op


async def _ok() -> str:
    return "ok"


async def test_unknown_before_any_call_and_freshness_is_none_not_zero() -> None:
    c = _Demo()
    h = await c.health()
    assert h.state is HealthState.UNKNOWN
    assert h.freshness.lag_ms is None
    assert (await c.freshness()).lag_ms is None
    assert (await c.coverage()).fraction is None


async def test_success_reports_healthy_with_freshness_and_coverage() -> None:
    c = _Demo()
    await c.guarded_call(
        _ok,
        freshness=lambda _r: FreshnessReport(lag_ms=1500, observed_at=T0),
        coverage=lambda _r: CoverageReport(expected_sources=4, answered_sources=3, partial=True),
    )
    h = await c.health()
    assert h.state is HealthState.HEALTHY
    assert h.freshness.lag_ms == 1500
    assert h.coverage.fraction == 0.75


async def test_rate_limited_then_expires() -> None:
    clock = _Clock()
    c = _Demo(clock=clock)
    with pytest.raises(RateLimitedError):
        await c.guarded_call(_raiser(RateLimitedError(30)))
    h = await c.health()
    assert h.state is HealthState.RATE_LIMITED
    assert h.rate_limit.limited
    assert h.rate_limit.retry_after_seconds == 30
    assert h.rate_limit.remaining == 0
    clock.now = T0 + timedelta(seconds=31)
    h = await c.health()
    assert not h.rate_limit.limited
    assert h.state is HealthState.DEGRADED


async def test_transient_degrades_then_fails_then_recovers() -> None:
    c = _Demo()
    for expected in (HealthState.DEGRADED, HealthState.DEGRADED, HealthState.FAILING):
        with pytest.raises(DependencyTransientError):
            await c.guarded_call(_raiser(DependencyTransientError("x")))
        assert (await c.health()).state is expected
    await c.guarded_call(_ok)
    assert (await c.health()).state is HealthState.HEALTHY


@pytest.mark.parametrize(
    "exc", [InvalidSchemaError(LEAK), CapabilityUnavailableError("r", LEAK), ValueError(LEAK)]
)
async def test_hard_errors_fail_immediately_without_leaking_text(exc: Exception) -> None:
    c = _Demo()
    with pytest.raises(type(exc)):
        await c.guarded_call(_raiser(exc))
    h = await c.health()
    assert h.state is HealthState.FAILING
    assert LEAK not in h.model_dump_json()
    assert h.last_error_code is not None


def test_coverage_rejects_answered_over_expected() -> None:
    with pytest.raises(ValueError, match="exceeds"):
        CoverageReport(expected_sources=1, answered_sources=2)
