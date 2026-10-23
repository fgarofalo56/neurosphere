"""Outbound credential port for external MCP servers (no token passthrough, clarification 5).

The client NEVER forwards an inbound user token. If an external server needs a credential, it
comes from an :class:`OutboundCredentialProvider` bound to the registered server (for example a
vault-referenced key or a managed-identity token for that server's own audience). The default is
:class:`NoOutboundCredentials`: no credential at all. Providers receive the registration only,
never the caller's request, token or scope.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, runtime_checkable

from neurosphere_core.mcp.models import RegisteredServer

__all__ = ["NoOutboundCredentials", "OutboundCredentialProvider"]


@runtime_checkable
class OutboundCredentialProvider(Protocol):
    async def headers_for(self, server: RegisteredServer) -> Mapping[str, str]:
        """Headers carrying the platform's OWN credential for ``server`` (may be empty)."""
        ...


class NoOutboundCredentials:
    """Default provider: external servers receive no credential."""

    async def headers_for(self, server: RegisteredServer) -> Mapping[str, str]:
        return {}
