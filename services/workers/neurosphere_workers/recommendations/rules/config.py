"""Versioned rule configs (PRP-15 item 1).

Every rule is data: a frozen config document with an id, a version, thresholds and windows. The
emitted ``Recommendation.generator`` cites ``rule_id`` and ``version`` so a record can be traced
to the exact thresholds that produced it. Changing a threshold means a new ``version``.

Windows. The evaluator looks at the ``baseline_window_days + recent_window_days`` days ending at
the evaluation window end (exclusive). The baseline is the older part, the recent window the
newer part. ``min_history_days`` is the history an agent needs before a rule may make a claim;
below it the output is a cold-start bounded-rule result with NO score.

Score (documented, deterministic, bounded). For the three time-series rules:

    score = breach_days / recent_window_days            in [0, 1]

where ``breach_days`` is the number of recent-window days that breach the threshold. The
uncertainty is a ``rule_bound`` with a one-day tolerance:

    lower = max(0, breach_days - 1) / recent_window_days
    upper = min(recent_window_days, breach_days + 1) / recent_window_days

so ``lower <= score <= upper`` always holds. For ``unused_agent``:

    score = min(1, covered_days / full_confidence_days)

(evidence strength grows with the number of days whose telemetry coverage is known), with the same
one-day tolerance expressed over ``full_confidence_days``. Neither score is a probability; it is a
rule-derived strength of evidence and is never produced on cold start.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

RuleId = Literal["cost_spike", "latency_degradation", "error_rate_degradation", "unused_agent"]


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _WindowedRule(_Frozen):
    version: str = Field(pattern=r"^[A-Za-z0-9._+-]{1,64}$")
    baseline_window_days: int = Field(ge=1, le=60)
    recent_window_days: int = Field(ge=1, le=60)
    min_history_days: int = Field(ge=2, le=120)
    min_breach_days: int = Field(ge=1, le=60)

    @model_validator(mode="after")
    def _windows_consistent(self) -> _WindowedRule:
        span = self.baseline_window_days + self.recent_window_days
        if self.min_history_days < span:
            raise ValueError("min_history_days must cover baseline plus recent window")
        if self.min_breach_days > self.recent_window_days:
            raise ValueError("min_breach_days cannot exceed recent_window_days")
        return self

    @property
    def lookback_days(self) -> int:
        return self.baseline_window_days + self.recent_window_days


class CostSpikeConfig(_WindowedRule):
    """A recent day breaches when its known cost exceeds ``ratio`` x the baseline median daily
    cost. Needs ``min_baseline_known_days`` baseline days with a known amount and a positive
    median; otherwise the rule cannot be evaluated and is reported as insufficient evidence."""

    rule_id: Literal["cost_spike"] = "cost_spike"
    ratio: Decimal = Field(gt=1)
    min_baseline_known_days: int = Field(ge=1)


class LatencyDegradationConfig(_WindowedRule):
    """A recent day breaches when its daily latency statistic exceeds ``ratio`` x the baseline
    median of that statistic. The rule fires when at least ``min_breach_days`` recent days breach
    AND the recent median also exceeds ``ratio`` x the baseline median. ``percentile`` selects the
    daily statistic of request-span duration: ``p50`` (default) or ``p95``. Measured on the sandbox
    pilot, the daily p95 of a handful of heavy-tailed requests is too noisy to separate a 3x
    regression from ordinary days (control agents reached 9x), the daily median is not, hence the
    default. A day only has a statistic with at least ``min_requests_per_day`` requests."""

    rule_id: Literal["latency_degradation"] = "latency_degradation"
    percentile: Literal["p50", "p95"] = "p50"
    ratio: float = Field(gt=1)
    min_requests_per_day: int = Field(ge=1)
    min_baseline_known_days: int = Field(ge=1)


class ErrorRateConfig(_WindowedRule):
    """A recent day breaches when its error rate (errors / requests) exceeds both
    ``min_error_rate`` and ``ratio`` x the pooled baseline error rate. Days with fewer than
    ``min_requests_per_day`` requests are unknown, not zero."""

    rule_id: Literal["error_rate_degradation"] = "error_rate_degradation"
    ratio: float = Field(gt=1)
    min_error_rate: float = Field(gt=0, le=1)
    min_requests_per_day: int = Field(ge=1)
    min_baseline_requests: int = Field(ge=1)


class UnusedAgentConfig(_Frozen):
    """An active agent with zero events on every day of the window is unused, but only when
    telemetry coverage of its source is known for the whole window. A window shorter than
    ``min_history_days`` covered days is a cold start (no score)."""

    rule_id: Literal["unused_agent"] = "unused_agent"
    version: str = Field(pattern=r"^[A-Za-z0-9._+-]{1,64}$")
    window_days: int = Field(ge=1, le=120)
    min_history_days: int = Field(ge=1, le=120)
    full_confidence_days: int = Field(ge=1, le=365)

    @model_validator(mode="after")
    def _windows_consistent(self) -> UnusedAgentConfig:
        if self.min_history_days > self.window_days:
            raise ValueError("min_history_days cannot exceed window_days")
        if self.full_confidence_days < self.min_history_days:
            raise ValueError("full_confidence_days must be at least min_history_days")
        return self


RuleConfig = CostSpikeConfig | LatencyDegradationConfig | ErrorRateConfig | UnusedAgentConfig


class RuleSet(_Frozen):
    """The four rule configs evaluated together."""

    cost_spike: CostSpikeConfig
    latency_degradation: LatencyDegradationConfig
    error_rate_degradation: ErrorRateConfig
    unused_agent: UnusedAgentConfig


DEFAULT_RULES = RuleSet(
    cost_spike=CostSpikeConfig(
        version="1.0.0",
        baseline_window_days=3,
        recent_window_days=4,
        min_history_days=7,
        min_breach_days=2,
        ratio=Decimal(15),
        min_baseline_known_days=2,
    ),
    latency_degradation=LatencyDegradationConfig(
        version="1.0.0",
        baseline_window_days=3,
        recent_window_days=4,
        min_history_days=7,
        min_breach_days=2,
        ratio=2.0,
        min_requests_per_day=4,
        min_baseline_known_days=2,
    ),
    error_rate_degradation=ErrorRateConfig(
        version="1.0.0",
        baseline_window_days=3,
        recent_window_days=4,
        min_history_days=7,
        min_breach_days=2,
        ratio=3.0,
        min_error_rate=0.2,
        min_requests_per_day=4,
        min_baseline_requests=10,
    ),
    unused_agent=UnusedAgentConfig(
        version="1.0.0",
        window_days=7,
        min_history_days=7,
        full_confidence_days=14,
    ),
)
