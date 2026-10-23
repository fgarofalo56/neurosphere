"""MCP client core (PRP-22 item 2): registry, SSRF policy, manifest validation, result bounds.

SDK-free on purpose: nothing in ``neurosphere_core.mcp`` imports the ``mcp`` SDK, ``httpx2`` or
``neurosphere_core.actions``. The SDK client and the pinned transport live in
``neurosphere_api.mcp.client``.
"""

from neurosphere_core.mcp.cosmos_store import (
    DEFAULT_MCP_SERVER_CONTAINER,
    CosmosMcpServerStore,
    create_mcp_server_container,
)
from neurosphere_core.mcp.limits import ManifestLimits, ResultLimits, TransportLimits
from neurosphere_core.mcp.manifest import ValidatedManifest, validate_manifest
from neurosphere_core.mcp.models import (
    DEFAULT_GOVERNMENT_HOST_SUFFIXES,
    ApprovalState,
    McpClientPolicy,
    RegisteredServer,
    ServerStatus,
    SyncResult,
    ToolApproval,
    ToolManifestEntry,
    ToolRecord,
    compute_tool_hash,
)
from neurosphere_core.mcp.outbound_auth import NoOutboundCredentials, OutboundCredentialProvider
from neurosphere_core.mcp.registry import (
    HASH_CHANGED,
    apply_approval,
    apply_revocation,
    apply_sync,
    check_boundary,
    check_callable,
    new_registration,
)
from neurosphere_core.mcp.results import (
    UNTRUSTED_EXTERNAL,
    ExternalTextBlock,
    ExternalToolProvenance,
    ExternalToolResult,
    build_external_result,
)
from neurosphere_core.mcp.service import McpRegistry, utc_now
from neurosphere_core.mcp.ssrf import (
    Resolver,
    SystemResolver,
    VettedTarget,
    blocked_address_reason,
    vet_target,
)
from neurosphere_core.mcp.store import InMemoryMcpServerStore, McpServerStore
from neurosphere_core.mcp.urls import (
    ServerUrl,
    blocked_hostname,
    normalize_server_url,
    server_id_for,
)

__all__ = [
    "DEFAULT_GOVERNMENT_HOST_SUFFIXES",
    "DEFAULT_MCP_SERVER_CONTAINER",
    "HASH_CHANGED",
    "UNTRUSTED_EXTERNAL",
    "ApprovalState",
    "CosmosMcpServerStore",
    "ExternalTextBlock",
    "ExternalToolProvenance",
    "ExternalToolResult",
    "InMemoryMcpServerStore",
    "ManifestLimits",
    "McpClientPolicy",
    "McpRegistry",
    "McpServerStore",
    "NoOutboundCredentials",
    "OutboundCredentialProvider",
    "RegisteredServer",
    "Resolver",
    "ResultLimits",
    "ServerStatus",
    "ServerUrl",
    "SyncResult",
    "SystemResolver",
    "ToolApproval",
    "ToolManifestEntry",
    "ToolRecord",
    "TransportLimits",
    "ValidatedManifest",
    "VettedTarget",
    "apply_approval",
    "apply_revocation",
    "apply_sync",
    "blocked_address_reason",
    "blocked_hostname",
    "build_external_result",
    "check_boundary",
    "check_callable",
    "compute_tool_hash",
    "create_mcp_server_container",
    "new_registration",
    "normalize_server_url",
    "server_id_for",
    "utc_now",
    "validate_manifest",
    "vet_target",
]
