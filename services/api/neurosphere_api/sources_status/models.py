"""Response models of the source status API (PRP-139 item 3).

Defined here, not taken from core or contracts: a model used as ``response_model`` that lives in a
shared package renames ``openapi.json`` components. Nothing here can hold an id, name, host or
token: states and reasons are closed sets or codes, counts are integers.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from neurosphere_core.sources_status import SourceSummary
from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "SourceStatusListView",
    "SourceStatusRowView",
    "SourcesAdminListView",
    "SourcesAdminRowView",
    "SourcesConnectorRowView",
    "admin_view",
    "user_view",
]

SourceName = Literal["foundry", "apim_gateway", "billing", "azure_monitor_telemetry"]
SourceStateName = Literal["not_connected", "connected_no_data", "connected", "failing"]
ConnectorKindName = Literal["foundry_discovery", "gateway_poll", "billing_export"]
RunStateName = Literal["ok", "partial", "failed", "idle", "not_configured"]


def _stamp(moment: datetime | None) -> str | None:
    return None if moment is None else moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class SourceStatusRowView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: SourceName
    state: SourceStateName
    last_success_at: str | None
    available: bool


class SourceStatusListView(BaseModel):
    """The four sources in a fixed order, readable by anyone who can read a domain."""

    model_config = ConfigDict(extra="forbid")

    sources: list[SourceStatusRowView]


class SourcesAdminRowView(SourceStatusRowView):
    reason: str | None


class SourcesConnectorRowView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: ConnectorKindName
    state: RunStateName
    reason: str | None
    last_success_at: str | None
    last_attempt_at: str | None
    counts: dict[str, int] = Field(default_factory=lambda: dict[str, int]())


class SourcesAdminListView(BaseModel):
    """The four sources with reason codes, and the run status of each connector kind."""

    model_config = ConfigDict(extra="forbid")

    sources: list[SourcesAdminRowView]
    connectors: list[SourcesConnectorRowView]


def user_view(summary: SourceSummary) -> SourceStatusListView:
    return SourceStatusListView(
        sources=[
            SourceStatusRowView(
                source=i.source,
                state=i.state,
                last_success_at=_stamp(i.last_success_at),
                available=i.available,
            )
            for i in summary.sources
        ]
    )


def admin_view(summary: SourceSummary) -> SourcesAdminListView:
    return SourcesAdminListView(
        sources=[
            SourcesAdminRowView(
                source=i.source,
                state=i.state,
                last_success_at=_stamp(i.last_success_at),
                available=i.available,
                reason=i.reason,
            )
            for i in summary.sources
        ],
        connectors=[
            SourcesConnectorRowView(
                kind=c.kind,
                state=c.state,
                reason=c.reason,
                last_success_at=_stamp(c.last_success_at),
                last_attempt_at=_stamp(c.last_attempt_at),
                counts=dict(c.counts),
            )
            for c in summary.connectors
        ],
    )
