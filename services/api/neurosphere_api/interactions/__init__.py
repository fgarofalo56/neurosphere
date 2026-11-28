"""Interaction explorer API (PRP-104): routes under ``/api/v1/domains/{domain_id}``.

Metadata routes need ``data.read``; the audited content read (:mod:`.content`,
:class:`InteractionContentReader`) needs ``interaction.read`` and a purpose; the bounded export
(:mod:`.export`, :class:`InteractionExporter`, blobs in :mod:`.export_storage`) needs
``interaction.export`` and a purpose.

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
from neurosphere_api.interactions.export import (
    AUDIT_OP_DOWNLOAD,
    AUDIT_OP_EXPORT,
    EXPORT_TTL,
    MAX_EXPORT,
    MAX_OPEN_EXPORTS,
    InteractionExporter,
    bundle_aad,
)
from neurosphere_api.interactions.export_storage import (
    BlobExportBackend,
    ExportBackend,
    InMemoryExportBackend,
    InteractionExportStorage,
)
from neurosphere_api.interactions.models import InteractionExportRequest, InteractionPage
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
    "AUDIT_OP_DOWNLOAD",
    "AUDIT_OP_EXPORT",
    "AUDIT_OP_READ",
    "EXPORT_TTL",
    "MAX_EXPORT",
    "MAX_OPEN_EXPORTS",
    "MAX_READ_BATCH",
    "OFF_REASON_ATTRIBUTE",
    "PREFIX",
    "STATE_ATTRIBUTE",
    "UNCONFIGURED_REASON",
    "BlobExportBackend",
    "ContentAccess",
    "ExportBackend",
    "InMemoryExportBackend",
    "InteractionContentReader",
    "InteractionExplorer",
    "InteractionExplorerService",
    "InteractionExportRequest",
    "InteractionExportStorage",
    "InteractionExporter",
    "InteractionPage",
    "InteractionSearch",
    "build_router",
    "bundle_aad",
    "configure_interaction_explorer",
    "get_explorer",
    "register",
    "validate_purpose",
]
