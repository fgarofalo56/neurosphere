"""MCP client for approved external servers (PRP-22 item 2).

The SDK-facing half of the client: :class:`ExternalMcpClient` (connect, sync, call) and the
pinned, guarded egress transport. Registry models, SSRF policy, manifest validation and result
bounds are SDK-free in :mod:`neurosphere_core.mcp`. This package exposes no HTTP routes; the
administrator API (item 3) wires :class:`ExternalMcpClient` and the registry into the app.
"""

from neurosphere_api.mcp.client.connector import (
    MAX_ARGUMENT_BYTES,
    MCP_EGRESS_REFUSED,
    MCP_RESPONSE_TOO_LARGE,
    ExternalMcpClient,
    TransportFactory,
)
from neurosphere_api.mcp.client.transport import (
    STRIPPED_HEADERS,
    EgressRefusedError,
    GuardedTransport,
    PinnedNetworkBackend,
    PinnedTransport,
    ResponseTooLargeError,
    pinned_transport,
)

__all__ = [
    "MAX_ARGUMENT_BYTES",
    "MCP_EGRESS_REFUSED",
    "MCP_RESPONSE_TOO_LARGE",
    "STRIPPED_HEADERS",
    "EgressRefusedError",
    "ExternalMcpClient",
    "GuardedTransport",
    "PinnedNetworkBackend",
    "PinnedTransport",
    "ResponseTooLargeError",
    "TransportFactory",
    "pinned_transport",
]
