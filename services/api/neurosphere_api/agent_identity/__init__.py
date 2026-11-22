"""Agent identity API (PRP-137 item 5): declare and read an alias from an external agent id to
a catalog agent, under ``/api/v1/agent-identity``."""

from __future__ import annotations

from typing import TYPE_CHECKING

from neurosphere_api.agent_identity.service import (
    STATE_ATTRIBUTE,
    AgentIdentityPlane,
    configure_agent_identity,
)

if TYPE_CHECKING:
    from neurosphere_api.routers import RouterRegistry

__all__ = [
    "STATE_ATTRIBUTE",
    "AgentIdentityPlane",
    "configure_agent_identity",
    "register",
]


def register(registry: RouterRegistry) -> None:
    """Router-registry hook (``neurosphere_api/routers.py``)."""
    from neurosphere_api.agent_identity.router import PREFIX, build_router

    registry.register(PREFIX, build_router())
