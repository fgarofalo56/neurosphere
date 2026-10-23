"""Reason codes and error factories for the MCP client (PRP-22 item 2).

Every refusal uses the PRP-01 taxonomy: ``forbidden`` for policy refusals (unregistered server,
SSRF block, boundary, unapproved tool), ``invalid_schema`` for malformed or oversized input from
an administrator or an external server, ``stale_version`` for ETag and approval-hash races and
``dependency_transient`` for DNS, network and store outages. Messages never echo the external
server's text, a resolved address list or a credential.
"""

from __future__ import annotations

from typing import Final

from neurosphere_core.errors import (
    DependencyTransientError,
    ForbiddenError,
    InvalidSchemaError,
    StaleVersionError,
    ValidationIssue,
)

__all__ = [
    "CLOUD_BOUNDARY_MISMATCH",
    "INVALID_MANIFEST",
    "INVALID_REGISTRATION",
    "INVALID_SERVER_URL",
    "INVALID_TOOL_ARGUMENTS",
    "INVALID_TOOL_RESULT",
    "MANIFEST_TOO_LARGE",
    "MCP_DNS_UNAVAILABLE",
    "MCP_REGISTRY_UNAVAILABLE",
    "MCP_SERVER_DISABLED",
    "MCP_SERVER_NOT_REGISTERED",
    "MCP_SERVER_UNAVAILABLE",
    "MISSING_DATA_READ",
    "OUTSIDE_GOVERNMENT_BOUNDARY",
    "SERVER_ALREADY_REGISTERED",
    "SERVER_MODIFIED",
    "SSRF_BLOCKED_ADDRESS",
    "SSRF_BLOCKED_HOST",
    "TOOL_HASH_CHANGED",
    "TOOL_HASH_MISMATCH",
    "TOOL_NOT_APPROVABLE",
    "TOOL_NOT_APPROVED",
    "TOOL_NOT_FOUND",
    "TOOL_RESULT_TOO_LARGE",
    "forbidden",
    "invalid",
    "stale",
    "unavailable",
]

# forbidden
MCP_SERVER_NOT_REGISTERED: Final = "mcp_server_not_registered"
MCP_SERVER_DISABLED: Final = "mcp_server_disabled"
SSRF_BLOCKED_HOST: Final = "ssrf_blocked_host"
SSRF_BLOCKED_ADDRESS: Final = "ssrf_blocked_address"
OUTSIDE_GOVERNMENT_BOUNDARY: Final = "outside_government_boundary"
CLOUD_BOUNDARY_MISMATCH: Final = "cloud_boundary_mismatch"
TOOL_NOT_APPROVED: Final = "tool_not_approved"
TOOL_HASH_MISMATCH: Final = "tool_hash_mismatch"
MISSING_DATA_READ: Final = "missing_data_read"

# invalid_schema
INVALID_SERVER_URL: Final = "invalid_server_url"
INVALID_MANIFEST: Final = "invalid_manifest"
MANIFEST_TOO_LARGE: Final = "manifest_too_large"
INVALID_TOOL_RESULT: Final = "invalid_tool_result"
INVALID_TOOL_ARGUMENTS: Final = "invalid_tool_arguments"
TOOL_RESULT_TOO_LARGE: Final = "tool_result_too_large"
SERVER_ALREADY_REGISTERED: Final = "server_already_registered"
INVALID_REGISTRATION: Final = "invalid_registration"
TOOL_NOT_FOUND: Final = "tool_not_found"
TOOL_NOT_APPROVABLE: Final = "tool_not_approvable"

# stale_version
SERVER_MODIFIED: Final = "server_modified"
TOOL_HASH_CHANGED: Final = "tool_hash_changed"

# dependency_transient
MCP_DNS_UNAVAILABLE: Final = "mcp_dns_unavailable"
MCP_SERVER_UNAVAILABLE: Final = "mcp_server_unavailable"
MCP_REGISTRY_UNAVAILABLE: Final = "mcp_registry_unavailable"


def forbidden(reason: str, detail: str) -> ForbiddenError:
    return ForbiddenError(detail, reason=reason)


def invalid(
    reason: str, detail: str, *, issues: list[ValidationIssue] | None = None
) -> InvalidSchemaError:
    return InvalidSchemaError(detail, reason=reason, errors=issues)


def stale(reason: str, detail: str) -> StaleVersionError:
    return StaleVersionError(detail, reason=reason)


def unavailable(
    reason: str, detail: str, *, upstream_invalid: bool = False
) -> DependencyTransientError:
    return DependencyTransientError(detail, reason=reason, upstream_invalid=upstream_invalid)
