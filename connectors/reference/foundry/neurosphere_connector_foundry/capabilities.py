"""Per-cloud Foundry Agent Service capability matrix.

Source: https://learn.microsoft.com/azure/foundry/agents/concepts/azure-government (observed
2026-10-17; the PRP records the same findings retrieved 2026-10-06 and 2026-10-08). The
Government matrix is a documentation fact, not a live probe: availability, GA and
authorization are separate gates, and this table claims none of FedRAMP, ATO or parity.

A capability that the matrix lists as unavailable is reported as ``unavailable`` with a
reason. It is never reported by omission or as an empty list, because an empty list reads as
"none found" when the truth is "cannot exist in this cloud".

Commercial is deliberately ``unknown``: this connector did not enumerate the Commercial matrix,
and it does not guess. ``unknown`` is a distinct status from ``available``.
"""

from __future__ import annotations

from enum import StrEnum

from neurosphere_core.cloud.profile import CloudName
from pydantic import BaseModel, ConfigDict

__all__ = [
    "CAPABILITY_NAMES",
    "CapabilityReport",
    "CapabilityStatus",
    "capability_reports",
]

DOC_URL = "https://learn.microsoft.com/azure/foundry/agents/concepts/azure-government"
OBSERVED = "2026-10-17"


class CapabilityStatus(StrEnum):
    AVAILABLE = "available"
    PREVIEW = "preview"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


class CapabilityReport(BaseModel):
    """One capability's status in one cloud. ``reason`` is set unless status is available."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    capability: str
    status: CapabilityStatus
    reason: str | None = None
    source: str | None = None


# (capability, Government status). Names mirror the rows of the documented tables.
_GOVERNMENT: tuple[tuple[str, CapabilityStatus], ...] = (
    ("prompt_agents", CapabilityStatus.AVAILABLE),
    ("voice_prompt_agents", CapabilityStatus.UNAVAILABLE),
    ("workflows", CapabilityStatus.PREVIEW),
    ("hosted_agents", CapabilityStatus.UNAVAILABLE),
    ("code_interpreter", CapabilityStatus.AVAILABLE),
    ("custom_code_interpreter", CapabilityStatus.PREVIEW),
    ("file_search", CapabilityStatus.AVAILABLE),
    ("azure_ai_search", CapabilityStatus.AVAILABLE),
    ("azure_functions", CapabilityStatus.AVAILABLE),
    ("function_calling", CapabilityStatus.AVAILABLE),
    ("mcp_servers", CapabilityStatus.AVAILABLE),
    ("openapi_tool", CapabilityStatus.AVAILABLE),
    ("web_search", CapabilityStatus.UNAVAILABLE),
    ("bing_grounding", CapabilityStatus.UNAVAILABLE),
    ("image_generation", CapabilityStatus.UNAVAILABLE),
    ("browser_automation", CapabilityStatus.UNAVAILABLE),
    ("computer_use", CapabilityStatus.UNAVAILABLE),
    ("fabric_tool", CapabilityStatus.UNAVAILABLE),
    ("sharepoint_tool", CapabilityStatus.UNAVAILABLE),
    ("agent_to_agent", CapabilityStatus.UNAVAILABLE),
)

CAPABILITY_NAMES: tuple[str, ...] = tuple(name for name, _ in _GOVERNMENT)

_REASONS = {
    CapabilityStatus.UNAVAILABLE: (
        "documented as not available in Azure Government (Foundry Agent Service feature "
        f"availability page, observed {OBSERVED})"
    ),
    CapabilityStatus.PREVIEW: (
        "documented as preview in Azure Government; preview features may not carry the same "
        f"compliance commitments as GA (observed {OBSERVED})"
    ),
}


def capability_reports(cloud: CloudName) -> list[CapabilityReport]:
    """Every known capability for ``cloud``, never filtered: unavailable rows stay visible."""
    if cloud is CloudName.GOVERNMENT:
        return [
            CapabilityReport(
                capability=name,
                status=status,
                reason=_REASONS.get(status),
                source=DOC_URL,
            )
            for name, status in _GOVERNMENT
        ]
    return [
        CapabilityReport(
            capability=name,
            status=CapabilityStatus.UNKNOWN,
            reason="Commercial capability matrix not enumerated by this connector",
            source=None,
        )
        for name in CAPABILITY_NAMES
    ]
