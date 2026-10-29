"""Gateway plane composition (PRP-33 item 6).

The plane lives on ``app.state.gateway_plane`` (:func:`configure_gateway_plane`); until it is
installed every route fails closed with 503 ``gateway_plane_unconfigured``.
:func:`build_gateway_plane` is the store-selecting factory (in-memory under ``NS_ENV=local``,
Cosmos otherwise).

No ``from __future__ import annotations``: FastAPI inspects these signatures.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

import httpx
from azure.core.credentials_async import AsyncTokenCredential
from fastapi import FastAPI, Request
from neurosphere_core.audit import AuditRepository
from neurosphere_core.clients import ClientLifetime, arm_client, create_cosmos_client
from neurosphere_core.cloud import CloudProfile, Settings
from neurosphere_core.errors import DependencyTransientError
from neurosphere_core.gateway import CosmosGatewayStore, GatewayStore, InMemoryGatewayStore

from neurosphere_api.gateway.settings import GatewaySettings, resolve_store_kind

__all__ = [
    "STATE_ATTRIBUTE",
    "ArmFactory",
    "GatewayPlane",
    "build_gateway_plane",
    "configure_gateway_plane",
    "get_gateway_plane",
]

STATE_ATTRIBUTE: Final = "gateway_plane"
_UNCONFIGURED: Final = "gateway_plane_unconfigured"

ArmFactory = Callable[[CloudProfile], httpx.AsyncClient]
Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class GatewayPlane:
    store: GatewayStore
    audit: AuditRepository
    arm_factory: ArmFactory
    settings: GatewaySettings
    clock: Clock = _utc_now

    def now(self) -> datetime:
        at = self.clock()
        if at.tzinfo is None:
            raise DependencyTransientError(
                "gateway clock is not timezone-aware", reason=_UNCONFIGURED
            )
        return at.astimezone(UTC)


def configure_gateway_plane(app: FastAPI, plane: GatewayPlane) -> None:
    setattr(app.state, STATE_ATTRIBUTE, plane)


def get_gateway_plane(request: Request) -> GatewayPlane:
    plane = getattr(request.app.state, STATE_ATTRIBUTE, None)
    if not isinstance(plane, GatewayPlane):
        raise DependencyTransientError("gateway registry is not configured", reason=_UNCONFIGURED)
    return plane


def build_gateway_plane(
    settings: Settings,
    *,
    audit: AuditRepository,
    lifetime: ClientLifetime,
    gateway: GatewaySettings | None = None,
    credential: AsyncTokenCredential | None = None,
    clock: Clock | None = None,
) -> GatewayPlane:
    """Select the store from ``NS_GATEWAY_*``; ARM clients are bound to the caller's cloud."""
    config = gateway or GatewaySettings.from_env()
    store: GatewayStore
    if resolve_store_kind(settings, config) == "memory":
        store = InMemoryGatewayStore()
    else:
        client = create_cosmos_client(
            settings, lifetime=lifetime, account=config.cosmos_account, credential=credential
        )
        store = CosmosGatewayStore.from_client(
            client, database=config.cosmos_database, container=config.cosmos_container
        )

    def factory(profile: CloudProfile) -> httpx.AsyncClient:
        return arm_client(profile, credential)

    return GatewayPlane(
        store=store, audit=audit, arm_factory=factory, settings=config, clock=clock or _utc_now
    )
