"""Interaction explorer API (PRP-104): routes under ``/api/v1/domains/{domain_id}``.

Metadata routes need ``data.read``; the audited content read (:mod:`.content`,
:class:`InteractionContentReader`) needs ``interaction.read`` and a purpose.

The explorer (``app.state.interaction_explorer``) is installed by
``runtime/builders/interaction_explorer.py``; the routes are in :mod:`.router`, their logic and
the explorer holder in :mod:`.service`, response bodies in :mod:`.models`.
"""

from neurosphere_api.interactions.content import (
    AUDIT_OP_READ,
    MAX_READ_BATCH,
    ContentAccess,
    InteractionContentReader,
    validate_purpose,
)
from neurosphere_api.interactions.models import InteractionPage
from neurosphere_api.interactions.router import PREFIX, build_router, register
from neurosphere_api.interactions.service import (
    OFF_REASON_ATTRIBUTE,
    STATE_ATTRIBUTE,
    UNCONFIGURED_REASON,
    InteractionExplorer,
    InteractionExplorerService,
    InteractionSearch,
    configure_interaction_explorer,
    get_explorer,
)

__all__ = [
    "AUDIT_OP_READ",
    "MAX_READ_BATCH",
    "OFF_REASON_ATTRIBUTE",
    "PREFIX",
    "STATE_ATTRIBUTE",
    "UNCONFIGURED_REASON",
    "ContentAccess",
    "InteractionContentReader",
    "InteractionExplorer",
    "InteractionExplorerService",
    "InteractionPage",
    "InteractionSearch",
    "build_router",
    "configure_interaction_explorer",
    "get_explorer",
    "register",
    "validate_purpose",
]
