"""Archive record serialization: redact, pseudonymize, compress, hash, name (pure functions)."""

from __future__ import annotations

import gzip
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, Final

from neurosphere_core.errors import ForbiddenError, InvalidSchemaError, ValidationIssue
from neurosphere_core.payload import drop_body_fields, find_body_fields

from neurosphere_workers.archive.pseudonymize import pseudonymize
from neurosphere_workers.ingestion.models import NormalizedEvent

NO_DOMAIN: Final = "_none"
MANIFEST_NAME: Final = "manifest.json"
BLOB_SUFFIX: Final = ".json.gz"

_SAFE_SEGMENT: Final = re.compile(r"[^/\\\x00-\x1f]+")


def _segment(value: str, what: str) -> str:
    if not _SAFE_SEGMENT.fullmatch(value) or value in {".", ".."} or value == NO_DOMAIN:
        detail = f"{what} is not usable as an archive path segment"
        raise InvalidSchemaError(
            detail, errors=[ValidationIssue(f"/{what}", detail)], reason="archive_path"
        )
    return value


def partition_prefix(customer_id: str, domain_id: str | None, day: date) -> str:
    """``{customer}/{domain or _none}/{yyyy}/{mm}/{dd}/`` (trailing slash included)."""
    domain = NO_DOMAIN if domain_id is None else _segment(domain_id, "domain_id")
    return f"{_segment(customer_id, 'customer_id')}/{domain}/{day:%Y/%m/%d}/"


def event_domain_id(event: NormalizedEvent) -> str | None:
    domain = event.contract.domain_id
    if domain is None:
        return None
    return str(getattr(domain, "root", domain))


def event_day(event: NormalizedEvent) -> date:
    return event.event_time.astimezone(UTC).date()


def blob_name(event: NormalizedEvent) -> str:
    prefix = partition_prefix(event.message.customer_id, event_domain_id(event), event_day(event))
    return f"{prefix}{event.doc_id}{BLOB_SUFFIX}"


def redact_record(record: dict[str, Any], pseudonym_key: bytes) -> dict[str, Any]:
    """Drop prompt/response bodies, then pseudonymize person identifiers. Refuses leftovers."""
    cleaned, _counts = drop_body_fields(record)
    if find_body_fields(cleaned):  # defense in depth: paths are never echoed
        raise ForbiddenError("archive record still contains body fields", reason="body_fields")
    redacted = pseudonymize(cleaned, pseudonym_key)
    if find_body_fields(redacted):
        raise ForbiddenError("archive record still contains body fields", reason="body_fields")
    return redacted


@dataclass(frozen=True, slots=True)
class ArchiveBlob:
    name: str
    data: bytes
    sha256: str


def encode_record(record: dict[str, Any]) -> tuple[bytes, str]:
    """Deterministic gzip of compact sorted JSON, and the sha256 (hex) of the compressed bytes."""
    text = json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    data = gzip.compress(text.encode("utf-8"), mtime=0)
    return data, hashlib.sha256(data).hexdigest()


def build_blob(event: NormalizedEvent, pseudonym_key: bytes) -> ArchiveBlob:
    record = redact_record(event.model_dump(mode="json"), pseudonym_key)
    data, digest = encode_record(record)
    return ArchiveBlob(name=blob_name(event), data=data, sha256=digest)


def utc_now() -> datetime:
    return datetime.now(UTC)
