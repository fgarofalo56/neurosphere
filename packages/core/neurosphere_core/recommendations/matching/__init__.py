"""Agent and tool matching: signals, combiner, feedback and the matcher service (PRP-72)."""

from __future__ import annotations

from .combine import (
    COLD_START_CAP,
    COLD_START_FACTOR,
    TELEMETRY_SIGNALS,
    combine,
    confidence_for,
    rank_candidates,
)
from .cosmos_store import CosmosFeedbackStore
from .feedback import FeedbackStore, InMemoryFeedbackStore, feedback_signal
from .models import CombinedResult, ProximityPath, SignalValue
from .service import AgentMatcher, AgentMatchReader, MatchResult
from .settings import DEFAULT_WEIGHTS, SIGNAL_NAMES, MatchSettings
from .signals import (
    USAGE_SATURATION,
    latency_pool_median,
    lexical_signal,
    proximity_signal,
    tag_signal,
    telemetry_signal,
)
from .tokens import STOP_WORDS, TOKEN_LIMIT, normalize_tokens

__all__ = [
    "COLD_START_CAP",
    "COLD_START_FACTOR",
    "DEFAULT_WEIGHTS",
    "SIGNAL_NAMES",
    "STOP_WORDS",
    "TELEMETRY_SIGNALS",
    "TOKEN_LIMIT",
    "USAGE_SATURATION",
    "AgentMatchReader",
    "AgentMatcher",
    "CombinedResult",
    "CosmosFeedbackStore",
    "FeedbackStore",
    "InMemoryFeedbackStore",
    "MatchResult",
    "MatchSettings",
    "ProximityPath",
    "SignalValue",
    "combine",
    "confidence_for",
    "feedback_signal",
    "latency_pool_median",
    "lexical_signal",
    "normalize_tokens",
    "proximity_signal",
    "rank_candidates",
    "tag_signal",
    "telemetry_signal",
]
