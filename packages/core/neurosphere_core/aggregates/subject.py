"""Per-agent, per-model, per-tool and per-service aggregate series (PRP-49, PRP-100).

The ``subject`` metric holds one :class:`SubjectPoint` per (domain, grain, bucket, subject).
Series keys are ``agent:<id>``, ``tool:<id>``, ``service:<id>`` (canonical ids) and
``model:<provider>/<model>`` (model keys are lower
case so catalog labels can be matched case-insensitively). Unknown stays ``None``, never 0.

:class:`SubjectMetricsReader` is a separate, runtime-checkable capability: the existing
``AggregateReader`` (50-series ceiling) is untouched, and callers use batch reads only when the
reader implements this protocol.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from neurosphere_core.aggregates.models import AggregateWindow, SubjectPoint

__all__ = [
    "HEALTH_DEGRADED_ERROR_RATE",
    "HEALTH_FAILING_ERROR_RATE",
    "KEYS_PER_QUERY",
    "MAX_SUBJECT_KEYS_PER_READ",
    "MAX_SUBJECT_SERIES_PER_BUCKET",
    "SubjectKind",
    "SubjectLookup",
    "SubjectMetricsReader",
    "SubjectPoint",
    "health_for_error_rate",
    "subject_series_key",
]

SubjectKind = Literal["agent", "model", "tool", "service"]
Health = Literal["ok", "degraded", "failing", "unknown"]

MAX_SUBJECT_SERIES_PER_BUCKET: Final = 5000
"""Guard chosen in PRP-49 (not a measurement): subject documents per (domain, grain, bucket)."""
MAX_SUBJECT_KEYS_PER_READ: Final = 2000
"""A viewport carries at most this many nodes; keys beyond it are dropped and flagged."""
KEYS_PER_QUERY: Final = 100
"""Keys per Cosmos ``IN`` query."""
HEALTH_DEGRADED_ERROR_RATE: Final = 0.05
HEALTH_FAILING_ERROR_RATE: Final = 0.25


def subject_series_key(kind: SubjectKind, first: str, second: str | None = None) -> str:
    """``agent:<id>``, ``tool:<id>``, ``service:<id>`` (canonical ids); ``model:<provider>/<model>``
    (lower case) for a model."""
    if kind in ("agent", "tool", "service"):
        return f"{kind}:{first}"
    if second is None:
        raise ValueError("a model key needs provider and model")
    return f"model:{first.strip().lower()}/{second.strip().lower()}"


def health_for_error_rate(error_rate: float | None) -> Health:
    """Same thresholds and meaning as the realtime source; unknown rate gives ``unknown``."""
    if error_rate is None:
        return "unknown"
    if error_rate >= HEALTH_FAILING_ERROR_RATE:
        return "failing"
    if error_rate >= HEALTH_DEGRADED_ERROR_RATE:
        return "degraded"
    return "ok"


class SubjectLookup(BaseModel):
    """Newest point per requested key (absent keys are simply missing, never zero)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    points: dict[str, SubjectPoint]
    truncated: bool = False


@runtime_checkable
class SubjectMetricsReader(Protocol):
    async def latest_subject_points(
        self,
        customer_id: str,
        domain_id: str,
        kind: SubjectKind,
        keys: Sequence[str],
        window: AggregateWindow,
    ) -> SubjectLookup:
        """Newest hour-grain point per key with ``bucket_start`` in the window. Scoped to one
        customer and domain; at most ``MAX_SUBJECT_KEYS_PER_READ`` keys (the rest are dropped and
        ``truncated`` is set)."""
        raise NotImplementedError

    async def newest_subject_points(
        self, customer_id: str, domain_id: str, window: AggregateWindow, limit: int
    ) -> SubjectLookup:
        """The ``limit`` subjects (agents and models only) with the newest hour-grain points."""
        raise NotImplementedError
