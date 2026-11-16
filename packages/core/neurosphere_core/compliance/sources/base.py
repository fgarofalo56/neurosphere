"""Evidence source protocol and shared helpers (PRP-56 item 3).

A source reads one existing store read-only and answers with counts, timestamps and ids only:
never an entity body, a prompt, a response or a principal name. Every read takes a window and a
cap and says when it was cut (``truncated``). A store that is missing or down yields
``unavailable`` with a reason code; a quantity the source cannot count is ``None`` (or the whole
observation is ``not_collected``), never 0.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

from neurosphere_contracts.compliance.v1.evidence_observation import EvidenceObservation

from neurosphere_core.scope import IdentityScope

__all__ = [
    "DEFAULT_CAP",
    "EvidenceSource",
    "SourceRequest",
    "format_utc",
    "make_observation",
    "parse_utc",
    "unavailable",
]

#: Default maximum number of records a source reads for one bundle.
DEFAULT_CAP = 2_000


@dataclass(frozen=True, slots=True)
class SourceRequest:
    """One bounded read: the caller's scope, the domain and the half-open window."""

    scope: IdentityScope
    domain_id: str
    window_start: datetime
    window_end: datetime
    cap: int = DEFAULT_CAP

    def __post_init__(self) -> None:
        if self.window_start.tzinfo is None or self.window_end.tzinfo is None:
            raise ValueError("window bounds must be timezone-aware")
        if self.window_start >= self.window_end:
            raise ValueError("window_start must be before window_end")
        if self.cap < 1:
            raise ValueError("cap must be at least 1")


@runtime_checkable
class EvidenceSource(Protocol):
    """A read-only evidence source."""

    source_id: str

    async def observe(self, request: SourceRequest) -> EvidenceObservation:
        """Return one observation for the request window."""
        raise NotImplementedError


def format_utc(instant: datetime) -> str:
    """Whole-second UTC timestamp with a ``Z`` suffix (deterministic bytes)."""
    return instant.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def make_observation(
    source_id: str,
    request: SourceRequest,
    *,
    status: str,
    reason_code: str | None = None,
    latest_at: datetime | None = None,
    truncated: bool = False,
    measures: Mapping[str, int | None] | None = None,
) -> EvidenceObservation:
    return EvidenceObservation.model_validate(
        {
            "schema_version": "1.0.0",
            "source_id": source_id,
            "status": status,
            "reason_code": reason_code,
            "window_start": format_utc(request.window_start),
            "window_end": format_utc(request.window_end),
            "latest_at": None if latest_at is None else format_utc(latest_at),
            "truncated": truncated,
            "measures": [{"name": k, "value": v} for k, v in (measures or {}).items()],
        }
    )


def unavailable(
    source_id: str,
    request: SourceRequest,
    reason_code: str,
    measures: tuple[str, ...] = ("records",),
) -> EvidenceObservation:
    """The store is absent or failed: every named measure is unknown (``None``)."""
    return make_observation(
        source_id,
        request,
        status="unavailable",
        reason_code=reason_code,
        measures=dict.fromkeys(measures),
    )
