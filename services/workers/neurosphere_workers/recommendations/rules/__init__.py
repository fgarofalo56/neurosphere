"""PRP-15 item 1: bounded rules engine (cost spike, latency, error rate, unused agent)."""

from neurosphere_workers.recommendations.rules.config import (
    DEFAULT_RULES,
    CostSpikeConfig,
    ErrorRateConfig,
    LatencyDegradationConfig,
    RuleSet,
    UnusedAgentConfig,
)
from neurosphere_workers.recommendations.rules.evaluator import (
    RuleResult,
    evaluate_rules,
    recommendation_id,
    recommendations,
)
from neurosphere_workers.recommendations.rules.sandbox_source import LoadStats, SandboxSeriesSource
from neurosphere_workers.recommendations.rules.series import (
    AgentDay,
    AgentSeries,
    AgentSeriesSource,
)

__all__ = [
    "DEFAULT_RULES",
    "AgentDay",
    "AgentSeries",
    "AgentSeriesSource",
    "CostSpikeConfig",
    "ErrorRateConfig",
    "LatencyDegradationConfig",
    "LoadStats",
    "RuleResult",
    "RuleSet",
    "SandboxSeriesSource",
    "UnusedAgentConfig",
    "evaluate_rules",
    "recommendation_id",
    "recommendations",
]
