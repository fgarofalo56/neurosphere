"""Source status plane and the summary read (PRP-139 item 3).

The plane is installed on ``app.state.source_status`` by the ``sources_status`` builder. The read
takes the caller's server-derived scope only: the customer id comes from it, never from the
request. Gateway registrations are read for the domains the caller can read (bounded), and a
gateway store outage only drops that evidence; it never fails the summary.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

from fastapi import FastAPI, Request
from neurosphere_core.auth.scope import Permission, domains_with_permission
from neurosphere_core.errors import DependencyTransientError, NeuroSphereError
from neurosphere_core.scope import IdentityScope
from neurosphere_core.sources_status import (
    ConfiguredConnector,
    GatewayHealth,
    SourceStatusRepository,
    SourceSummary,
    summarize,
)

from neurosphere_api.gateway.dependencies import GatewayPlane

__all__ = [
    "STATE_ATTRIBUTE",
    "ConfigLister",
    "SourceStatusPlane",
    "configure_source_status",
    "get_plane",
    "read_summary",
]

STATE_ATTRIBUTE: Final = "source_status"
_UNCONFIGURED: Final = "source_status_unconfigured"
_MAX_GATEWAY_DOMAINS: Final = 20
_GATEWAY_PAGE: Final = 50

ConfigLister = Callable[[str], Awaitable[Sequence[ConfiguredConnector]]]


@dataclass(frozen=True)
class SourceStatusPlane:
    """What the routes need: the run status store and a lister of connector configurations."""

    statuses: SourceStatusRepository
    configs: ConfigLister


def configure_source_status(app: FastAPI, plane: SourceStatusPlane | None) -> None:
    setattr(app.state, STATE_ATTRIBUTE, plane)


def get_plane(request: Request) -> SourceStatusPlane:
    plane = getattr(request.app.state, STATE_ATTRIBUTE, None)
    if not isinstance(plane, SourceStatusPlane):
        raise DependencyTransientError("source status is not configured", reason=_UNCONFIGURED)
    return plane


async def _gateways(request: Request, scope: IdentityScope, now: datetime) -> list[GatewayHealth]:
    gateway = getattr(request.app.state, "gateway_plane", None)
    if not isinstance(gateway, GatewayPlane):
        return []
    domains = sorted(domains_with_permission(scope, Permission.DATA_READ, now=now))
    found: list[GatewayHealth] = []
    try:
        for domain_id in domains[:_MAX_GATEWAY_DOMAINS]:
            page = await gateway.store.list(scope.customer_id, domain_id, limit=_GATEWAY_PAGE)
            found.extend(
                GatewayHealth(poll_status=g.poll_status, has_watermark=g.poll_watermark is not None)
                for g in page.items
            )
    except NeuroSphereError:
        return []
    return found


async def read_summary(
    request: Request, scope: IdentityScope, plane: SourceStatusPlane
) -> SourceSummary:
    """The four-source summary for the caller's customer."""
    now = datetime.now(UTC)
    statuses = await plane.statuses.list(scope.customer_id)
    configs = await plane.configs(scope.customer_id)
    gateways = await _gateways(request, scope, now)
    return summarize(statuses, configs, gateways)
