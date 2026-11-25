"""Opt-in captured interaction content: encrypted store, metadata index, settings (PRP-102).

Only already-redacted, schema-checked ``RedactedContent`` can be written, and only when the
customer retention policy opts in to bodies and has an ``interaction_content`` rule
(:func:`content_writes_enabled`). Content rests as an AES-256-GCM envelope in blob storage; the
Cosmos ``interaction_index`` document is metadata only (PRP-99 ``InteractionRecord``).
"""

from neurosphere_core.interactions.blob_content import (
    BlobInteractionContent,
    ContentBackend,
    InMemoryInteractionContent,
    content_blob_name,
    parse_content_blob_name,
)
from neurosphere_core.interactions.capture import (
    AUDIT_OP_CAPTURE,
    AUDIT_OP_CAPTURE_DROPPED,
    CaptureAuditEvent,
    CaptureAuditWriter,
    CaptureEvent,
    CapturePipeline,
    CaptureRateLimiter,
    CaptureStats,
    CaptureStore,
    CaptureTarget,
    ExtractedBody,
    ExtractedPart,
    MinuteRateLimiter,
    extract_body_parts,
    interaction_pointer,
    redaction_config_for,
)
from neurosphere_core.interactions.cosmos_index import (
    CosmosInteractionIndex,
    IndexBackend,
    InMemoryInteractionIndex,
)
from neurosphere_core.interactions.models import (
    CONTENT_NOT_SECRET_FREE,
    CONTENT_PURGED,
    CONTENT_RETENTION_NOT_ENABLED,
    DATA_CLASS_INTERACTION,
    INTERACTION_EXISTS,
    INTERACTION_NOT_FOUND,
    MAX_QUERY_PAGE_SIZE,
    IndexPage,
    InteractionQuery,
    InteractionStoreError,
    InteractionStoreReason,
)
from neurosphere_core.interactions.settings import (
    ENV_INTERACTION_LOCAL_KEY_FILE,
    InteractionSettings,
    build_key_wrapper,
)
from neurosphere_core.interactions.store import (
    EncryptedInteractionStore,
    InMemoryInteractionStore,
    InteractionStore,
    content_writes_enabled,
    validate_redacted_content,
)

__all__ = [
    "AUDIT_OP_CAPTURE",
    "AUDIT_OP_CAPTURE_DROPPED",
    "CONTENT_NOT_SECRET_FREE",
    "CONTENT_PURGED",
    "CONTENT_RETENTION_NOT_ENABLED",
    "DATA_CLASS_INTERACTION",
    "ENV_INTERACTION_LOCAL_KEY_FILE",
    "INTERACTION_EXISTS",
    "INTERACTION_NOT_FOUND",
    "MAX_QUERY_PAGE_SIZE",
    "BlobInteractionContent",
    "CaptureAuditEvent",
    "CaptureAuditWriter",
    "CaptureEvent",
    "CapturePipeline",
    "CaptureRateLimiter",
    "CaptureStats",
    "CaptureStore",
    "CaptureTarget",
    "ContentBackend",
    "CosmosInteractionIndex",
    "EncryptedInteractionStore",
    "ExtractedBody",
    "ExtractedPart",
    "InMemoryInteractionContent",
    "InMemoryInteractionIndex",
    "InMemoryInteractionStore",
    "IndexBackend",
    "IndexPage",
    "InteractionQuery",
    "InteractionSettings",
    "InteractionStore",
    "InteractionStoreError",
    "InteractionStoreReason",
    "MinuteRateLimiter",
    "build_key_wrapper",
    "content_blob_name",
    "content_writes_enabled",
    "extract_body_parts",
    "interaction_pointer",
    "parse_content_blob_name",
    "redaction_config_for",
    "validate_redacted_content",
]
