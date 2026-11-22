"""Telemetry agent identity resolution (PRP-137): alias first, derived id otherwise."""

from neurosphere_core.agent_identity.keys import (
    agent_alias_key,
    derive_agent_id,
    is_owned_agent,
    slug,
)
from neurosphere_core.agent_identity.lookup import (
    AliasLookup,
    CatalogAliasLookup,
    DeclaredAlias,
    declare_agent_alias,
)
from neurosphere_core.agent_identity.resolver import (
    AgentIdentityResolver,
    AgentResolution,
    ResolutionStats,
    ResolutionStatus,
)
from neurosphere_core.agent_identity.settings import AgentIdentitySettings

__all__ = [
    "AgentIdentityResolver",
    "AgentIdentitySettings",
    "AgentResolution",
    "AliasLookup",
    "CatalogAliasLookup",
    "DeclaredAlias",
    "ResolutionStats",
    "ResolutionStatus",
    "agent_alias_key",
    "declare_agent_alias",
    "derive_agent_id",
    "is_owned_agent",
    "slug",
]
