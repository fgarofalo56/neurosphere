"""Reading the approval state of an agent version or an agent (PRP-99 ``AgentVersionApproval``).

``None`` means no approval was recorded. An agent's state is the state of its current version;
an agent with no current version has no approval.
"""

from __future__ import annotations

from neurosphere_contracts.catalog.v1.agent import Agent
from neurosphere_contracts.catalog.v1.agent_version import AgentVersion

from neurosphere_core.catalog.protocol import CatalogEntity, CatalogRepository
from neurosphere_core.governance.policy.rules.base import RuleContext, text_of

__all__ = ["APPROVED", "NO_APPROVAL", "approval_state", "subject_approval_state"]

APPROVED = "approved"
NO_APPROVAL = "none"
"""Category name used when no approval record exists."""


def approval_state(version: AgentVersion) -> str:
    """The version's approval state name, ``none`` when no approval was recorded."""
    if version.approval is None:
        return NO_APPROVAL
    return text_of(version.approval.state) or NO_APPROVAL


async def subject_approval_state(
    repo: CatalogRepository, ctx: RuleContext, entity: CatalogEntity
) -> str:
    """Approval state of an agent version, or of an agent's current version.

    Any other entity type has no approval (``none``). A current version outside the scope reads
    as missing, so as ``none``.
    """
    if isinstance(entity, AgentVersion):
        return approval_state(entity)
    if isinstance(entity, Agent):
        current = text_of(entity.current_version_id)
        if current is None:
            return NO_APPROVAL
        version = await repo.get_entity(ctx.scope, current)
        if isinstance(version, AgentVersion):
            return approval_state(version)
    return NO_APPROVAL
