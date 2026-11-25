"""Interaction store reasons, errors, query and page shapes (PRP-102 item 4).

The store's own failures raise :class:`InteractionStoreError`, whose text is exactly one reason
code. Envelope failures (``content_integrity_failed``, ``key_wrap_unavailable``,
``key_host_refused``) are :class:`neurosphere_core.crypto.EnvelopeError` and pass through the
store unchanged. No message ever carries content, a key, a vault URI or a document.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Any, Final, Literal

from neurosphere_contracts.interactions.v1.interaction_record import InteractionRecord
from pydantic import AfterValidator, BaseModel, ConfigDict, Field, ValidationError

__all__ = [
    "CONTENT_CONTAINER_MISSING",
    "CONTENT_NOT_SECRET_FREE",
    "CONTENT_PURGED",
    "CONTENT_RECORD_MISMATCH",
    "CONTENT_RETENTION_NOT_ENABLED",
    "DATA_CLASS_INTERACTION",
    "DEFAULT_QUERY_PAGE_SIZE",
    "INTERACTION_EXISTS",
    "INTERACTION_INDEX_INVALID",
    "INTERACTION_NOT_FOUND",
    "INTERACTION_STORE_UNAVAILABLE",
    "INVALID_QUERY",
    "MAX_QUERY_PAGE_SIZE",
    "IndexPage",
    "InteractionQuery",
    "InteractionStoreError",
    "InteractionStoreReason",
    "decode_continuation",
    "encode_continuation",
    "format_timestamp",
    "index_document",
    "parse_timestamp",
    "query_fingerprint",
    "record_from_document",
]

#: Lifecycle data class of captured interaction content (index record plus encrypted blob).
DATA_CLASS_INTERACTION: Final = "interaction_content"

CONTENT_RETENTION_NOT_ENABLED: Final = "content_retention_not_enabled"
CONTENT_NOT_SECRET_FREE: Final = "content_not_secret_free"  # noqa: S105 - a reason code
CONTENT_PURGED: Final = "content_purged"
INTERACTION_NOT_FOUND: Final = "interaction_not_found"
INTERACTION_EXISTS: Final = "interaction_exists"
#: The record and the content disagree (interaction id, redaction state, detector set).
CONTENT_RECORD_MISMATCH: Final = "content_record_mismatch"
#: A stored index document no longer validates as ``InteractionRecord``.
INTERACTION_INDEX_INVALID: Final = "interaction_index_invalid"
#: The index or the content storage failed (outage, throttling, unexpected SDK error).
INTERACTION_STORE_UNAVAILABLE: Final = "interaction_store_unavailable"
#: Outside ``NS_ENV=local`` the content container must already exist (PRP-109 provisions it).
CONTENT_CONTAINER_MISSING: Final = "content_container_missing"
#: A continuation token that is malformed or belongs to another query.
INVALID_QUERY: Final = "invalid_query"

InteractionStoreReason = Literal[
    "content_retention_not_enabled",
    "content_not_secret_free",
    "content_purged",
    "interaction_not_found",
    "interaction_exists",
    "content_record_mismatch",
    "interaction_index_invalid",
    "interaction_store_unavailable",
    "content_container_missing",
    "invalid_query",
]

MAX_QUERY_PAGE_SIZE: Final = 100
DEFAULT_QUERY_PAGE_SIZE: Final = 50


class InteractionStoreError(Exception):
    """An interaction store operation was refused or failed. ``str()`` is the reason code only."""

    def __init__(self, reason: InteractionStoreReason) -> None:
        super().__init__(reason)
        self.reason: InteractionStoreReason = reason

    def __str__(self) -> str:
        return self.reason


def _aware(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        raise ValueError("captured-at bounds must be timezone-aware")
    return value


_Slug = Annotated[str, Field(min_length=1, max_length=512)]


class InteractionQuery(BaseModel):
    """A partition-scoped, page-bounded index query. Customer and domain are always required."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    customer_id: Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[a-z0-9._-]+$")]
    domain_id: _Slug
    agent_id: _Slug | None = None
    principal_id: _Slug | None = None
    tool_id: _Slug | None = None
    data_asset_id: _Slug | None = None
    #: A ``SensitivityCategory`` the interaction touched (``sensitivity_categories``).
    sensitivity_category: Annotated[str, Field(min_length=1, max_length=64)] | None = None
    #: A ``DetectedCategory`` in ``findings_summary``.
    detected_category: Annotated[str, Field(min_length=1, max_length=64)] | None = None
    #: Inclusive lower bound on ``captured_at``.
    captured_from: Annotated[datetime | None, AfterValidator(_aware)] = None
    #: Exclusive upper bound on ``captured_at``.
    captured_before: Annotated[datetime | None, AfterValidator(_aware)] = None
    page_size: Annotated[int, Field(ge=1, le=MAX_QUERY_PAGE_SIZE)] = DEFAULT_QUERY_PAGE_SIZE
    continuation: Annotated[str, Field(min_length=1, max_length=16384)] | None = None


@dataclass(frozen=True, slots=True)
class IndexPage:
    """One page of index records, newest ``captured_at`` first, and an opaque continuation."""

    items: tuple[InteractionRecord, ...]
    continuation: str | None = None


# --- shared helpers for the index backends ------------------------------------------------------

_TIMESTAMP_FORMAT: Final = "%Y-%m-%dT%H:%M:%S.%fZ"
_CURSOR_PREFIX: Final = "nsq1."
_BOOKKEEPING: Final = frozenset({"id"})


def format_timestamp(value: datetime) -> str:
    """Canonical index timestamp: UTC, always six fractional digits, ``Z``.

    One fixed width keeps string order equal to time order, so ``captured_at`` range filters
    and ``ORDER BY`` are correct in Cosmos and in the in-memory twin alike.
    """
    if value.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    return value.astimezone(UTC).strftime(_TIMESTAMP_FORMAT)


def parse_timestamp(value: str) -> datetime:
    """Parse a contract ``Timestamp`` (RFC 3339 UTC, ``Z``)."""
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("timestamp has no offset")
    return parsed.astimezone(UTC)


def index_document(record: InteractionRecord) -> dict[str, Any]:
    """The stored index document: the record's JSON plus the Cosmos ``id`` (the interaction id)."""
    body = record.model_dump(mode="json")
    body["id"] = body["interaction_id"]
    return body


def record_from_document(row: Mapping[str, Any]) -> InteractionRecord:
    """Validate a stored index document; anything that fails is ``interaction_index_invalid``."""
    body = {k: v for k, v in row.items() if not k.startswith("_") and k not in _BOOKKEEPING}
    try:
        record = InteractionRecord.model_validate(body)
    except ValidationError:
        raise InteractionStoreError(INTERACTION_INDEX_INVALID) from None
    if row.get("id") != record.interaction_id.root:
        raise InteractionStoreError(INTERACTION_INDEX_INVALID)
    return record


def query_fingerprint(query: InteractionQuery) -> str:
    """Binds a continuation token to its exact partition and filters (never page size)."""
    shape = query.model_dump(mode="json", exclude={"page_size", "continuation"})
    canonical = json.dumps(shape, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]


def encode_continuation(query: InteractionQuery, position: Any) -> str:
    """Opaque, URL-safe token carrying the query fingerprint and a backend position."""
    payload = json.dumps({"q": query_fingerprint(query), "p": position}, separators=(",", ":"))
    return _CURSOR_PREFIX + base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii")


def decode_continuation(query: InteractionQuery) -> Any:
    """The backend position of ``query.continuation``; ``invalid_query`` when foreign or bad."""
    token = query.continuation
    if token is None:
        return None
    if not token.startswith(_CURSOR_PREFIX):
        raise InteractionStoreError(INVALID_QUERY)
    try:
        raw = base64.urlsafe_b64decode(token[len(_CURSOR_PREFIX) :].encode("ascii"))
        payload = json.loads(raw.decode("utf-8"))
    except (binascii.Error, UnicodeError, ValueError):
        raise InteractionStoreError(INVALID_QUERY) from None
    if not isinstance(payload, dict) or payload.get("q") != query_fingerprint(query):
        raise InteractionStoreError(INVALID_QUERY)
    position = payload.get("p")
    if position is None:
        raise InteractionStoreError(INVALID_QUERY)
    return position
