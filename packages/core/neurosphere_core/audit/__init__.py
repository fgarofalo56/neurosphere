"""Append-only, hash-chained audit store (PRP-06 item 4).

Public surface: :class:`AuditRepository` (append, read_range, tail, verify; update/delete
refuse with ``forbidden``), record builders over the PRP-01 ``AuditRecord`` contract, chain
verification, the SIEM export hook and the storage port with its Cosmos and in-memory
implementations. ``CosmosAuditStore`` lives in ``neurosphere_core.audit.cosmos_store`` and is
imported explicitly by callers that wire Cosmos.
"""

from neurosphere_core.audit.builders import (
    ALLOW_DETAIL,
    AuditContext,
    AuditDraft,
    build_after,
    build_allowed,
    build_before,
    build_denied,
    is_allow_record,
    make_subject,
)
from neurosphere_core.audit.canonical import (
    canonical_json,
    compute_record_hash,
    digests_equal,
    sha256_digest,
)
from neurosphere_core.audit.chain import (
    ChainVerification,
    TailPointer,
    seal,
    verify_chain,
)
from neurosphere_core.audit.content_guard import assert_metadata_only, find_sensitive_content
from neurosphere_core.audit.repository import (
    AuditRepository,
    run_audited_mutation,
    validate_chain_id,
)
from neurosphere_core.audit.siem import (
    JsonLinesFileSink,
    SiemExporter,
    SiemSink,
    StdoutSink,
    to_siem_event,
)
from neurosphere_core.audit.store import (
    AuditStore,
    InMemoryAuditStore,
    SequenceTakenError,
    StoredTail,
    TailConflictError,
)

__all__ = [
    "ALLOW_DETAIL",
    "AuditContext",
    "AuditDraft",
    "AuditRepository",
    "AuditStore",
    "ChainVerification",
    "InMemoryAuditStore",
    "JsonLinesFileSink",
    "SequenceTakenError",
    "SiemExporter",
    "SiemSink",
    "StdoutSink",
    "StoredTail",
    "TailConflictError",
    "TailPointer",
    "assert_metadata_only",
    "build_after",
    "build_allowed",
    "build_before",
    "build_denied",
    "canonical_json",
    "compute_record_hash",
    "digests_equal",
    "find_sensitive_content",
    "is_allow_record",
    "make_subject",
    "run_audited_mutation",
    "seal",
    "sha256_digest",
    "to_siem_event",
    "validate_chain_id",
    "verify_chain",
]
