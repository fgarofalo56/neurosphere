"""Hash chain: sealing a draft into a contract ``AuditRecord`` and verifying a chain.

Each record stores ``previous_hash`` (the preceding record's ``record_hash``; null only at the
chain head, sequence 0) and ``record_hash`` (sha256 over the JCS form of the record without
``record_hash``). Verification walks records in the order given and reports the FIRST index at
which the chain stops verifying:

* altered record (hash not recomputed)  -> that index, ``record_hash_mismatch``
* altered and re-hashed record          -> the next index, ``previous_hash_mismatch``
* removed record / reordered records    -> the first displaced index, ``sequence_mismatch``
* forked chain (two records, same seq)  -> the duplicate's index, ``sequence_mismatch``
* truncated tail (tail pointer ahead)   -> ``len(records)``, ``tail_mismatch``
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, Final, Literal

from neurosphere_contracts.audit.v1.audit_record import AuditRecord
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from neurosphere_core.audit.builders import AuditDraft
from neurosphere_core.audit.canonical import RECORD_HASH_FIELD, compute_record_hash, digests_equal
from neurosphere_core.audit.content_guard import assert_metadata_only

AUDIT_SCHEMA_VERSION: Final = "1.0.0"

FailureReason = Literal[
    "invalid_record",
    "chain_id_mismatch",
    "sequence_mismatch",
    "record_hash_mismatch",
    "previous_hash_mismatch",
    "tail_mismatch",
]


class TailPointer(BaseModel):
    """Last sealed record of a chain: the append cursor and the truncation anchor."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    chain_id: str
    sequence: int = Field(ge=0)
    record_hash: str


class ChainVerification(BaseModel):
    """Result of verifying one chain. ``first_invalid_index`` is a position in the input."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    chain_id: str
    ok: bool
    records_checked: int = Field(ge=0)
    first_invalid_index: int | None = None
    first_invalid_sequence: int | None = None
    reason: FailureReason | None = None


def format_timestamp(instant: datetime) -> str:
    """Contract UtcTimestamp: RFC 3339, UTC, ``Z`` suffix, microsecond precision."""
    if instant.tzinfo is None:
        raise ValueError("audit timestamps must be timezone-aware")
    utc = instant.astimezone(UTC)
    return utc.strftime("%Y-%m-%dT%H:%M:%S") + f".{utc.microsecond:06d}Z"


def check_structure(record: AuditRecord) -> None:
    """Contract rules the generated model cannot express (schema allOf if/then branches)."""
    if (record.sequence == 0) != (record.previous_hash is None):
        raise ValueError("previous_hash must be null exactly at the chain head (sequence 0)")
    if record.kind == "before" and (
        record.subject is None or record.outcome is not None or record.denial is not None
    ):
        raise ValueError("before records need a subject and no outcome or denial")
    if record.kind == "after" and (
        record.subject is None or record.outcome is None or record.denial is not None
    ):
        raise ValueError("after records need a subject and an outcome, and no denial")
    if record.kind == "denied" and (record.denial is None or record.outcome is not None):
        raise ValueError("denied records need a denial and no outcome")


def seal(
    draft: AuditDraft,
    *,
    chain_id: str,
    sequence: int,
    previous_hash: str | None,
    audit_id: str,
    recorded_at: datetime,
) -> AuditRecord:
    """Build, hash, validate and guard one record. The only constructor of stored records."""
    body: dict[str, Any] = {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "audit_id": audit_id,
        "chain_id": chain_id,
        "sequence": sequence,
        "previous_hash": previous_hash,
        "recorded_at": format_timestamp(recorded_at),
        **draft.model_dump(mode="json"),
    }
    body[RECORD_HASH_FIELD] = compute_record_hash(body)
    record = AuditRecord.model_validate(body)
    check_structure(record)
    assert_metadata_only(record.model_dump(mode="json"))
    return record


def _as_document(record: AuditRecord | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(record, AuditRecord):
        return record.model_dump(mode="json")
    return dict(record)


def _seq(document: Mapping[str, Any]) -> int | None:
    value = document.get("sequence")
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def verify_chain(
    records: Sequence[AuditRecord | Mapping[str, Any]],
    *,
    chain_id: str,
    start_sequence: int = 0,
    anchor_hash: str | None = None,
    tail: TailPointer | None = None,
) -> ChainVerification:
    """Verify ``records`` as the contiguous run of ``chain_id`` starting at ``start_sequence``.

    ``anchor_hash`` is the ``record_hash`` of record ``start_sequence - 1`` (``None`` when
    verifying from the head). ``tail``, when given, must point at a record inside the run with
    a matching hash; a tail beyond the last record means records were removed from the end.
    """

    def fail(index: int, reason: FailureReason, sequence: int | None) -> ChainVerification:
        return ChainVerification(
            chain_id=chain_id,
            ok=False,
            records_checked=index,
            first_invalid_index=index,
            first_invalid_sequence=sequence,
            reason=reason,
        )

    expected_previous = anchor_hash
    hashes: list[str] = []
    for index, raw in enumerate(records):
        document = _as_document(raw)
        sequence = _seq(document)
        try:
            record = AuditRecord.model_validate(document)
            check_structure(record)
        except (ValidationError, ValueError):
            return fail(index, "invalid_record", sequence)
        if record.chain_id != chain_id:
            return fail(index, "chain_id_mismatch", sequence)
        if record.sequence != start_sequence + index:
            return fail(index, "sequence_mismatch", sequence)
        stored_hash = record.record_hash.root
        if not digests_equal(stored_hash, compute_record_hash(document)):
            return fail(index, "record_hash_mismatch", sequence)
        previous = record.previous_hash.root if record.previous_hash is not None else None
        if not digests_equal(previous, expected_previous):
            return fail(index, "previous_hash_mismatch", sequence)
        expected_previous = stored_hash
        hashes.append(stored_hash)

    if tail is not None:
        position = tail.sequence - start_sequence
        if (
            tail.chain_id != chain_id
            or position < 0
            or position >= len(hashes)
            or not digests_equal(tail.record_hash, hashes[position])
        ):
            return fail(len(hashes), "tail_mismatch", tail.sequence)
    return ChainVerification(chain_id=chain_id, ok=True, records_checked=len(hashes))
