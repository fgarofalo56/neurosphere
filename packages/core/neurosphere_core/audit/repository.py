"""Append-only audit repository: append, read by range, verify chain. Nothing else.

There is no update or delete. ``update``/``delete`` (and the usual synonyms) exist only to
refuse loudly with ``forbidden`` (reason ``audit_append_only``) so a caller reaching for them
fails at the call site instead of silently doing nothing. Corrections are new records.

Fail closed: :meth:`AuditRepository.append` raises when the record cannot be durably written
(``dependency_transient``, reason ``audit_write_failed``), and :func:`run_audited_mutation`
writes the ``before`` record first so a failed audit write aborts the mutation before it runs.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, Final, NoReturn

from neurosphere_contracts.audit.v1.audit_record import AuditRecord
from pydantic import ValidationError

from neurosphere_core.audit.builders import AuditDraft
from neurosphere_core.audit.canonical import digests_equal
from neurosphere_core.audit.chain import ChainVerification, TailPointer, seal, verify_chain
from neurosphere_core.audit.siem import SiemExporter
from neurosphere_core.audit.store import (
    AuditStore,
    SequenceTakenError,
    StoredTail,
    TailConflictError,
)
from neurosphere_core.errors import (
    DependencyTransientError,
    ForbiddenError,
    InvalidSchemaError,
    NeuroSphereError,
)

DEFAULT_MAX_APPEND_ATTEMPTS: Final = 64
MAX_RANGE: Final = 500
#: Upper bound on records one verify pass will read; a tail claiming more is reported, not walked.
MAX_VERIFY_RECORDS: Final = 1_000_000
CHAIN_ID_PATTERN: Final = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")

Clock = Callable[[], datetime]
IdFactory = Callable[[], str]


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _uuid4() -> str:
    return str(uuid.uuid4())


def _write_failed(detail: str) -> DependencyTransientError:
    return DependencyTransientError(detail, reason="audit_write_failed")


def _append_only() -> NoReturn:
    raise ForbiddenError("audit records are append-only", reason="audit_append_only")


def validate_chain_id(chain_id: str) -> str:
    if not CHAIN_ID_PATTERN.fullmatch(chain_id):
        raise InvalidSchemaError("invalid audit chain id", reason="invalid_chain_id")
    return chain_id


class AuditRepository:
    """The public audit API. Construct with an injected :class:`AuditStore`."""

    def __init__(
        self,
        store: AuditStore,
        *,
        clock: Clock = _utc_now,
        id_factory: IdFactory = _uuid4,
        exporter: SiemExporter | None = None,
        max_attempts: int = DEFAULT_MAX_APPEND_ATTEMPTS,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        self._store = store
        self._clock = clock
        self._ids = id_factory
        self._exporter = exporter
        self._max_attempts = max_attempts

    # -- append ------------------------------------------------------------------------------

    async def append(self, chain_id: str, draft: AuditDraft) -> AuditRecord:
        """Seal ``draft`` as the next record of ``chain_id`` and write it durably, or raise."""
        validate_chain_id(chain_id)
        for _ in range(self._max_attempts):
            current = await self._guarded(self._store.read_tail(chain_id))
            sequence = 0 if current is None else current.tail.sequence + 1
            previous = None if current is None else current.tail.record_hash
            record = seal(
                draft,
                chain_id=chain_id,
                sequence=sequence,
                previous_hash=previous,
                audit_id=self._ids(),
                recorded_at=self._clock(),
            )
            try:
                await self._guarded(
                    self._store.create_record(chain_id, sequence, record.model_dump(mode="json"))
                )
            except SequenceTakenError:
                await self._repair_tail(chain_id, sequence, current)
                continue
            await self._advance_tail(record, current)
            if self._exporter is not None:
                await self._exporter.export(record)
            return record
        raise DependencyTransientError(
            "audit append contention exceeded the retry budget", reason="audit_write_failed"
        )

    async def _guarded[T](self, operation: Awaitable[T]) -> T:
        """Map any store failure to a fail-closed taxonomy error; pass control signals through."""
        try:
            return await operation
        except (SequenceTakenError, TailConflictError):
            raise
        except NeuroSphereError as exc:
            raise _write_failed("audit store unavailable") from exc
        except Exception as exc:
            raise _write_failed("audit store failed") from exc

    async def _advance_tail(self, record: AuditRecord, current: StoredTail | None) -> None:
        tail = TailPointer(
            chain_id=record.chain_id, sequence=record.sequence, record_hash=record.record_hash.root
        )
        try:
            await self._guarded(
                self._store.write_tail(tail, if_match=None if current is None else current.etag)
            )
        except TailConflictError:
            # Only possible if another writer already advanced the tail onto this record
            # (sequence ids are unique, so nothing else can occupy it). Nothing to do.
            return

    async def _repair_tail(self, chain_id: str, sequence: int, current: StoredTail | None) -> None:
        """Another writer created ``sequence``; move the tail onto it if it still lags."""
        existing = await self._guarded(self._store.read_record(chain_id, sequence))
        if existing is None:
            return
        expected_previous = None if current is None else current.tail.record_hash
        found_previous = existing.get("previous_hash")
        found_hash = existing.get("record_hash")
        if not isinstance(found_hash, str) or not digests_equal(
            found_previous if isinstance(found_previous, str) else None, expected_previous
        ):
            # A record that does not link to the tail: the chain is corrupt. Refuse to extend it.
            raise DependencyTransientError(
                "audit chain does not link; appends are blocked", reason="audit_chain_broken"
            )
        tail = TailPointer(chain_id=chain_id, sequence=sequence, record_hash=found_hash)
        try:
            await self._guarded(
                self._store.write_tail(tail, if_match=None if current is None else current.etag)
            )
        except TailConflictError:
            return

    # -- read / verify -------------------------------------------------------------------------

    async def read_range(
        self, chain_id: str, *, start: int = 0, limit: int = 100
    ) -> list[AuditRecord]:
        """Records with ``start <= sequence < start + limit`` (limit capped at ``MAX_RANGE``)."""
        validate_chain_id(chain_id)
        if start < 0 or not 1 <= limit <= MAX_RANGE:
            raise InvalidSchemaError("invalid audit range", reason="invalid_range")
        documents = await self._store.query_range(chain_id, start, start + limit)
        try:
            return [AuditRecord.model_validate(doc) for doc in documents]
        except ValidationError as exc:
            raise DependencyTransientError(
                "stored audit record failed validation",
                reason="audit_record_invalid",
                upstream_invalid=True,
            ) from exc

    async def tail(self, chain_id: str) -> TailPointer | None:
        validate_chain_id(chain_id)
        current = await self._store.read_tail(chain_id)
        return None if current is None else current.tail

    async def verify(
        self,
        chain_id: str,
        *,
        page_size: int = MAX_RANGE,
        max_records: int = MAX_VERIFY_RECORDS,
    ) -> ChainVerification:
        """Verify the whole chain from the head, anchored on the tail pointer.

        At most ``max_records`` are read. A tail claiming a longer chain (a corrupted or forged
        tail pointer, or a chain beyond the cap) fails closed with ``verify_limit_exceeded``
        instead of paging without bound.
        """
        validate_chain_id(chain_id)
        current = await self._store.read_tail(chain_id)
        tail = None if current is None else current.tail
        if tail is not None and tail.sequence >= max_records:
            return ChainVerification(
                chain_id=chain_id, ok=False, records_checked=0, reason="verify_limit_exceeded"
            )
        documents: list[dict[str, Any]] = []
        start = 0
        while start < max_records:
            page = await self._store.query_range(chain_id, start, start + page_size)
            documents.extend(page)
            start += page_size
            if not page and (tail is None or start > tail.sequence):
                break
        documents.sort(key=lambda d: d.get("sequence", -1))
        return verify_chain(documents, chain_id=chain_id, tail=tail)

    # -- refused operations ------------------------------------------------------------------

    def update(self, *args: Any, **kwargs: Any) -> NoReturn:
        _append_only()

    def delete(self, *args: Any, **kwargs: Any) -> NoReturn:
        _append_only()

    def replace(self, *args: Any, **kwargs: Any) -> NoReturn:
        _append_only()

    def upsert(self, *args: Any, **kwargs: Any) -> NoReturn:
        _append_only()

    def patch(self, *args: Any, **kwargs: Any) -> NoReturn:
        _append_only()

    def remove(self, *args: Any, **kwargs: Any) -> NoReturn:
        _append_only()


async def run_audited_mutation[T](
    repository: AuditRepository,
    chain_id: str,
    *,
    before: AuditDraft,
    mutate: Callable[[], Awaitable[T]],
    after: Callable[[T], AuditDraft],
    on_error: Callable[[BaseException], AuditDraft] | None = None,
) -> T:
    """Before-record, mutation, after-record. A failed audit write aborts (fail closed).

    * ``before`` cannot be written -> raises; ``mutate`` is never called.
    * ``mutate`` raises -> ``on_error`` record is appended (if given), then the error re-raises.
    * ``after`` cannot be written -> raises ``audit_write_failed``. The change already happened;
      the caller must treat the operation as failed and surface it (PRP-17 reconciles).
    """
    await repository.append(chain_id, before)
    try:
        result = await mutate()
    except Exception as exc:
        if on_error is not None:
            await repository.append(chain_id, on_error(exc))
        raise
    await repository.append(chain_id, after(result))
    return result
