"""Tier capabilities and diagnostics coverage for a registered gateway (matrix-driven)."""

from __future__ import annotations

from typing import Final

from neurosphere_core.capabilities.validate import default_matrix, tier_capability
from neurosphere_core.gateway.models import DiagnosticsState, Tier

__all__ = ["CAPABILITY_FEATURES", "capabilities_for", "coverage_for"]

CAPABILITY_FEATURES: Final = (
    "llm_token_limit",
    "llm_emit_token_metric",
    "gateway_llm_logs",
    "gateway_mcp_logs",
    "mcp_server",
    "backend_pool",
    "anthropic_messages_schema",
)


def capabilities_for(tier: Tier, cloud: str) -> dict[str, str]:
    """Feature -> availability string from the matrix (``unverified`` when no row speaks)."""
    matrix = default_matrix()
    return {
        feature: tier_capability(matrix, tier=tier, feature=feature, cloud=cloud).availability
        for feature in CAPABILITY_FEATURES
    }


def coverage_for(capabilities: dict[str, str], diagnostics: DiagnosticsState) -> float | None:
    """Fraction of the log categories the tier can emit that are actually enabled.

    ``GatewayLogs`` is always expected; the LLM and MCP categories unless the matrix says
    ``unavailable`` (``unverified`` still counts: the category may exist). A category the tier
    cannot emit does not count against coverage.
    """
    expected = [diagnostics.gateway_logs]
    if capabilities.get("gateway_llm_logs") != "unavailable":
        expected.append(diagnostics.gateway_llm_logs)
    if capabilities.get("gateway_mcp_logs") != "unavailable":
        expected.append(diagnostics.gateway_mcp_logs)
    return sum(expected) / len(expected)
