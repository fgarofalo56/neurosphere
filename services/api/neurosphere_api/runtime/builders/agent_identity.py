"""Agent identity builder (PRP-137 item 5): installs ``app.state.agent_identity``.

Component ``agent_identity`` is OPTIONAL: a deployment without it still serves and the two routes
answer 503 ``agent_identity_unconfigured``. It binds the catalog repository the data builder
published and reports ``disabled`` when there is none.
"""

from __future__ import annotations

import logging
from typing import Final

from neurosphere_core.catalog.protocol import CatalogRepository

from neurosphere_api.agent_identity import AgentIdentityPlane, configure_agent_identity
from neurosphere_api.runtime.builders import CATALOG_REPOSITORY, BuildContext, BuilderSpec

__all__ = ["BUILDER", "COMPONENTS", "build"]

COMPONENTS: Final = ("agent_identity",)

_log = logging.getLogger("neurosphere_api.runtime")


def build(ctx: BuildContext) -> None:
    configure_agent_identity(ctx.app, None)
    repository = ctx.maybe_shared(CATALOG_REPOSITORY)
    if not isinstance(repository, CatalogRepository):
        _log.warning("component agent_identity disabled: catalog_repository_unavailable")
        ctx.disabled("agent_identity")
        return
    configure_agent_identity(ctx.app, AgentIdentityPlane(repository=repository))
    ctx.ok("agent_identity")


BUILDER: Final = BuilderSpec("agent_identity", COMPONENTS, build)
