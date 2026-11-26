"""What each enforcement point can actually block (PRP-105 "Interfaces provided").

This table is the only source for a "this blocks X" claim: PRP-106 shows it, and nobody may claim
a block outside it. Detective evaluation (the ``policy_eval`` worker) blocks nothing; it records
violations as evidence of a rule match.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

from neurosphere_core.governance.policy.models import EnforcementPointName

__all__ = [
    "DETECTIVE_EVALUATION_CAN_BLOCK",
    "ENFORCEMENT_POINT_CAPABILITIES",
    "PointCapability",
]

#: The worker evaluator is detective only.
DETECTIVE_EVALUATION_CAN_BLOCK: Final = False


@dataclass(frozen=True, slots=True)
class PointCapability:
    """What one enforcement point can block, and which PRP builds it."""

    can_block: bool
    what_it_blocks: str
    owning_prp: str


ENFORCEMENT_POINT_CAPABILITIES: Final[Mapping[EnforcementPointName, PointCapability]] = (
    MappingProxyType(
        {
            "gateway": PointCapability(
                can_block=True,
                what_it_blocks=(
                    "Only model traffic through a NeuroSphere-managed APIM gateway in manage "
                    "mode on NeuroSphere-owned products; Commercial only."
                ),
                owning_prp="PRP-112",
            ),
            "tool_call": PointCapability(
                can_block=True,
                what_it_blocks="NeuroSphere's own copilot tool calls.",
                owning_prp="PRP-113",
            ),
            "mcp_server": PointCapability(
                can_block=True,
                what_it_blocks="Calls to NeuroSphere's MCP server tools.",
                owning_prp="PRP-113",
            ),
            "mcp_client": PointCapability(
                can_block=True,
                what_it_blocks=("NeuroSphere's outbound calls to registered external MCP servers."),
                owning_prp="PRP-113",
            ),
            "sdk": PointCapability(
                can_block=False,
                what_it_blocks="Nothing: cooperative guard in the workload, never a boundary.",
                owning_prp="PRP-114",
            ),
            "budget": PointCapability(
                can_block=False,
                what_it_blocks=(
                    "Nothing automatically: proposes a budget_cap_change action for approval."
                ),
                owning_prp="PRP-115",
            ),
            "registration": PointCapability(
                can_block=True,
                what_it_blocks=(
                    "Withholds activation of an unapproved AgentVersion inside NeuroSphere only."
                ),
                owning_prp="PRP-108",
            ),
        }
    )
)
