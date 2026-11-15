"""Connector configuration admin API (PRP-42), mounted at ``/api/v1/admin/sources/connectors``.

An admin stores the configuration of the data-collection roles (Azure Monitor and APIM gateway
polling, Foundry discovery, billing export, OTel) with credentials by reference only. See
``router`` for the route table and ``service`` for the audit and order of checks.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from neurosphere_api.admin.sources.connectors.service import (
    STATE_ATTRIBUTE,
    ConnectorAdminPlane,
    configure_admin_connectors,
)

if TYPE_CHECKING:
    from neurosphere_api.routers import RouterRegistry

__all__ = [
    "PREFIX",
    "STATE_ATTRIBUTE",
    "ConnectorAdminPlane",
    "configure_admin_connectors",
    "register",
]

PREFIX = "/api/v1/admin/sources/connectors"


def register(registry: RouterRegistry) -> None:
    """Router-registry hook (``neurosphere_api/routers.py``)."""
    from neurosphere_api.admin.sources.connectors.router import build_router

    registry.register(PREFIX, build_router())
