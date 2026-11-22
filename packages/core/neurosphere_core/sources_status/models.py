"""Connector run status (PRP-139 item 3): what one connector kind did on its last tick.

A status carries a closed state, a reason CODE, two timestamps and integer counts. It never
holds an id, name, host, resource id or token: a reason and a count name are validated against a
code pattern (``[a-z][a-z0-9_]{0,63}``), so nothing free-form can reach the store or a response.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Final, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

__all__ = [
    "CONNECTOR_KINDS",
    "NOT_AVAILABLE_IN_RELEASE",
    "SOURCE_ACCESS_DENIED",
    "ConnectorKind",
    "ConnectorRunStatus",
    "RunState",
    "classify_failure",
    "is_code",
]

ConnectorKind = Literal["foundry_discovery", "gateway_poll", "billing_export", "azure_monitor_ai"]
RunState = Literal["ok", "partial", "failed", "idle", "not_configured"]

CONNECTOR_KINDS: Final[tuple[ConnectorKind, ...]] = (
    "foundry_discovery",
    "gateway_poll",
    "billing_export",
    "azure_monitor_ai",
)

# Reason codes are free codes validated only by ``is_code`` (there is no registry here). The
# ``azure_monitor_ai`` worker role (PRP-141) writes: query_budget_exhausted,
# event_budget_exhausted, rate_limited, stalled, ingest_failed, cloud_mismatch,
# refused_government_unverified, plus source_access_denied; the UI owns the plain-language text.

#: The provider answered 401 or 403: the Azure role the connector needs is missing.
SOURCE_ACCESS_DENIED: Final = "source_access_denied"
#: Retired: Application Insights call telemetry now has a connector (``azure_monitor_ai``); the
#: summary no longer produces this code. Kept exported for compatibility.
NOT_AVAILABLE_IN_RELEASE: Final = "not_available_in_release"

_CODE: Final = re.compile(r"[a-z][a-z0-9_]{0,63}")
_MAX_COUNTS: Final = 16
_DENIED_MARKERS: Final = ("unauthorized", "forbidden")


def is_code(value: str) -> bool:
    return _CODE.fullmatch(value) is not None


def classify_failure(text: str) -> str | None:
    """``source_access_denied`` when ``text`` names a 401 or 403 error class, else ``None``.

    ``text`` is what a poller already keeps: an exception class name (``ForbiddenError``) or a
    taxonomy code (``forbidden``). Nothing else is inspected, and nothing from it is stored.
    """
    lowered = text.lower()
    if any(marker in lowered for marker in _DENIED_MARKERS):
        return SOURCE_ACCESS_DENIED
    return None


def _utc(value: datetime | None) -> datetime | None:
    return None if value is None else value.astimezone(UTC)


class ConnectorRunStatus(BaseModel):
    """The last run of one connector kind for one customer (stored once per kind)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: ConnectorKind
    state: RunState
    reason: str | None = None
    last_success_at: AwareDatetime | None = None
    last_attempt_at: AwareDatetime
    counts: dict[str, int] = Field(default_factory=lambda: dict[str, int]())

    @field_validator("reason")
    @classmethod
    def _reason_is_a_code(cls, value: str | None) -> str | None:
        if value is not None and not is_code(value):
            raise ValueError("reason must be a code")
        return value

    @field_validator("counts")
    @classmethod
    def _counts_are_names_and_integers(cls, value: dict[str, int]) -> dict[str, int]:
        if len(value) > _MAX_COUNTS:
            raise ValueError("too many counts")
        for name, number in value.items():
            if not is_code(name):
                raise ValueError("count names must be codes")
            if number < 0:
                raise ValueError("counts are not negative")
        return value

    @field_validator("last_success_at", "last_attempt_at")
    @classmethod
    def _to_utc(cls, value: datetime | None) -> datetime | None:
        return _utc(value)
