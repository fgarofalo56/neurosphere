"""The source summary: four sources, each ``not_connected | connected_no_data | connected |
failing`` (PRP-139 item 3).

Pure: it takes the stored run statuses, the connector configurations (kind and enabled flag
only) and the gateway registrations' poll results, and returns the summary. It never sees a
name, id, host or credential, so none can reach a response.

Rules per built-in source (connector kind in parentheses):

* a ``failed`` run is ``failing``;
* a ``not_configured`` run, or no run and no enabled configuration, is ``not_connected``;
* an enabled configuration with no run yet is ``not_connected`` (reason ``awaiting_first_run``:
  a stored configuration applies when the workers next start);
* an ``ok`` or ``partial`` run that delivered something (``records`` > 0, gateways polled, or an
  ``unchanged`` billing export whose rows were delivered earlier) is ``connected``;
* an ``ok`` or ``partial`` run with nothing delivered, and an ``idle`` run of an enabled
  configuration, is ``connected_no_data``.

Application Insights call telemetry is never built in this release: always ``not_connected``,
``available: false``, reason ``not_available_in_release``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Final, Literal

from neurosphere_core.sources_status.models import (
    NOT_AVAILABLE_IN_RELEASE,
    ConnectorKind,
    ConnectorRunStatus,
    RunState,
)

__all__ = [
    "AWAITING_FIRST_RUN",
    "SOURCE_ORDER",
    "ConfiguredConnector",
    "ConnectorSummary",
    "GatewayHealth",
    "SourceKey",
    "SourceState",
    "SourceSummary",
    "SourceSummaryItem",
    "summarize",
]

SourceKey = Literal["foundry", "apim_gateway", "billing", "azure_monitor_telemetry"]
SourceState = Literal["not_connected", "connected_no_data", "connected", "failing"]

SOURCE_ORDER: Final[tuple[SourceKey, ...]] = (
    "foundry",
    "apim_gateway",
    "billing",
    "azure_monitor_telemetry",
)
_KIND_OF: Final[Mapping[str, ConnectorKind]] = {
    "foundry": "foundry_discovery",
    "apim_gateway": "gateway_poll",
    "billing": "billing_export",
}
AWAITING_FIRST_RUN: Final = "awaiting_first_run"
UNCHANGED: Final = "unchanged"
_GATEWAY_OK: Final = frozenset({"ok", "partial", "rate_limited", "stalled"})


@dataclass(frozen=True, slots=True)
class ConfiguredConnector:
    """A stored connector configuration, reduced to what the summary needs."""

    kind: str
    enabled: bool


@dataclass(frozen=True, slots=True)
class GatewayHealth:
    """One gateway registration's last poll: its status code and whether a watermark exists."""

    poll_status: str | None
    has_watermark: bool = False


@dataclass(frozen=True, slots=True)
class ConnectorSummary:
    kind: ConnectorKind
    state: RunState
    reason: str | None
    last_success_at: datetime | None
    last_attempt_at: datetime | None
    counts: Mapping[str, int] = field(default_factory=lambda: dict[str, int]())


@dataclass(frozen=True, slots=True)
class SourceSummaryItem:
    source: SourceKey
    state: SourceState
    last_success_at: datetime | None
    available: bool
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class SourceSummary:
    sources: tuple[SourceSummaryItem, ...]
    connectors: tuple[ConnectorSummary, ...]


def _gateway_evidence(gateways: Sequence[GatewayHealth] | None) -> tuple[bool, bool]:
    """``(any gateway polled fine, any gateway failing)`` from the registrations."""
    if not gateways:
        return False, False
    polled = any(g.has_watermark and g.poll_status in _GATEWAY_OK for g in gateways)
    failing = any(g.poll_status is not None and g.poll_status not in _GATEWAY_OK for g in gateways)
    return polled, failing


def _delivered(kind: ConnectorKind, status: ConnectorRunStatus) -> bool:
    counts = status.counts
    if kind == "gateway_poll":
        return counts.get("gateways_polled", 0) > 0
    return counts.get("records", 0) > 0 or status.reason == UNCHANGED


def _state_for(
    kind: ConnectorKind,
    status: ConnectorRunStatus | None,
    enabled: bool,
    gateways: Sequence[GatewayHealth] | None,
) -> tuple[SourceState, str | None]:
    polled, gateway_failing = (
        _gateway_evidence(gateways) if kind == "gateway_poll" else (False, False)
    )
    if status is None:
        if kind == "gateway_poll" and polled:
            return "connected", None
        if kind == "gateway_poll" and gateway_failing:
            return "failing", None
        return "not_connected", AWAITING_FIRST_RUN if enabled else None
    if status.state == "failed":
        return "failing", status.reason
    if status.state == "not_configured":
        return "not_connected", AWAITING_FIRST_RUN if enabled else status.reason
    if status.state == "idle":
        return ("connected_no_data", status.reason) if enabled else ("not_connected", status.reason)
    if _delivered(kind, status) or polled:
        return "connected", status.reason if status.state == "partial" else None
    return "connected_no_data", status.reason


def summarize(
    statuses: Sequence[ConnectorRunStatus],
    configs: Sequence[ConfiguredConnector],
    gateways: Sequence[GatewayHealth] | None = None,
) -> SourceSummary:
    """The four-source summary and the per-connector view (admin only)."""
    by_kind = {s.kind: s for s in statuses}
    enabled_kinds = {c.kind for c in configs if c.enabled}
    items: list[SourceSummaryItem] = []
    connectors: list[ConnectorSummary] = []
    for source in SOURCE_ORDER:
        kind = _KIND_OF.get(source)
        if kind is None:
            items.append(
                SourceSummaryItem(
                    source, "not_connected", None, False, reason=NOT_AVAILABLE_IN_RELEASE
                )
            )
            continue
        status = by_kind.get(kind)
        enabled = kind in enabled_kinds
        state, reason = _state_for(kind, status, enabled, gateways)
        items.append(
            SourceSummaryItem(
                source,
                state,
                None if status is None else status.last_success_at,
                True,
                reason=reason,
            )
        )
        connectors.append(
            ConnectorSummary(
                kind=kind,
                state="not_configured" if status is None else status.state,
                reason=reason if status is None else status.reason,
                last_success_at=None if status is None else status.last_success_at,
                last_attempt_at=None if status is None else status.last_attempt_at,
                counts={} if status is None else dict(status.counts),
            )
        )
    return SourceSummary(sources=tuple(items), connectors=tuple(connectors))
