"""The normalizer pipeline: a pure ``process_batch`` (no SDK clients) that tests call directly.

Per message, in order: parse and validate (malformed goes straight to quarantine, attempts=1,
no retry), dedupe, watermark/late flag, sink writes with a bounded retry budget, accepted
marker LAST, then watermark advance.

Crash rule: the accepted marker is written only after every sink succeeded. A crash between a
sink write and the marker makes the redelivered message re-run the sink writes, which are
idempotent by ``doc_id`` (see ``protocols.py``): never skipped, never double applied.

Failure model: a sink that keeps raising ``DependencyTransientError`` exhausts its budget and
the message is quarantined (``retry_budget_exhausted``) so a poison event cannot block its
partition. Any other exception, and any failure of the quarantine sink itself, propagates:
the batch is then NOT checkpointable (PRP-07 C4).

TODO(follow-up, PRP-05 owned files): emit a duplicate-event metric. ``BatchResult.duplicates``
carries the count today; new metric names are added only through the PRP-05 observability
constants, not here.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import random
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from neurosphere_contracts.cost.v1.cost_record import CostRecord
from neurosphere_contracts.telemetry.v1.telemetry_event import TelemetryEvent
from neurosphere_core.errors import DependencyTransientError
from neurosphere_core.payload import (
    DEFAULT_MAX_DEPTH,
    HubMessage,
    HubMessageKind,
    drop_body_fields,
    find_body_fields,
    raw_json_exceeds_depth,
)
from pydantic import ValidationError

from neurosphere_workers.ingestion.models import (
    BatchResult,
    NormalizedEvent,
    QuarantineRecord,
    RawMessage,
    compute_doc_id,
    parse_timestamp,
)
from neurosphere_workers.ingestion.protocols import (
    AcceptedMarkerStore,
    ArchiveSink,
    LedgerSink,
    QuarantineSink,
    WatermarkStore,
)
from neurosphere_workers.ingestion.reasons import QuarantineReason
from neurosphere_workers.ingestion.settings import IngestionSettings
from neurosphere_workers.runtime import BackoffPolicy, BatchOutcome, retry_with_backoff

SUPPORTED_SCHEMA_MAJOR = "1"
_MAX_ID_LENGTH = 256


@dataclass
class PipelineDeps:
    """Everything ``process_batch`` touches. Fakes in ``fakes.py`` satisfy all of it."""

    quarantine: QuarantineSink
    archive: ArchiveSink
    ledger: LedgerSink
    markers: AcceptedMarkerStore
    watermarks: WatermarkStore
    cloud: str  # this worker's configured cloud ("commercial" | "government")
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep
    rng: Callable[[], float] = random.random  # backoff jitter only
    clock: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))


class _Rejected(Exception):  # noqa: N818 - internal control flow
    def __init__(
        self,
        reason: QuarantineReason,
        parsed: Any = None,
    ) -> None:
        super().__init__(reason.value)  # never the payload
        self.reason = reason
        self.parsed = parsed


def _event_time(contract: TelemetryEvent | CostRecord) -> datetime:
    if isinstance(contract, TelemetryEvent):
        return parse_timestamp(contract.event_time.root)
    # CostRecord has no event_time: the end of the usage window, else its start, else when the
    # ledger recorded it. billing_period is date-only and not used.
    for candidate in (contract.usage_end, contract.usage_start):
        if candidate is not None:
            return parse_timestamp(candidate.root)
    return parse_timestamp(contract.recorded_at.root)


def _validate_contract(message: HubMessage) -> TelemetryEvent | CostRecord:
    data = message.data
    version = data.get("schema_version")
    if not isinstance(version, str):
        raise _Rejected(QuarantineReason.INVALID_SCHEMA)
    major = version.split(".", 1)[0]
    if major.isdigit() and major != SUPPORTED_SCHEMA_MAJOR:
        raise _Rejected(QuarantineReason.UNSUPPORTED_SCHEMA_VERSION)
    model = TelemetryEvent if message.kind is HubMessageKind.TELEMETRY else CostRecord
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        # Unknown fields only: a newer producer, not a corrupt one.
        if all(err["type"] == "extra_forbidden" for err in exc.errors()):
            raise _Rejected(QuarantineReason.UNSUPPORTED_SCHEMA_VERSION) from None
        raise _Rejected(QuarantineReason.INVALID_SCHEMA) from None


def _parse(raw: RawMessage, cloud: str) -> NormalizedEvent:
    """Raise ``_Rejected`` for every malformed shape. Messages are never echoed in errors."""
    if raw_json_exceeds_depth(raw.body, DEFAULT_MAX_DEPTH):
        raise _Rejected(QuarantineReason.DEPTH_EXCEEDED)
    try:
        parsed: Any = json.loads(raw.body)
    except (ValueError, RecursionError):  # UnicodeDecodeError is a ValueError
        raise _Rejected(QuarantineReason.INVALID_WIRE) from None
    if find_body_fields(parsed):
        raise _Rejected(QuarantineReason.BODY_FIELD_PRESENT, parsed)
    try:
        message = HubMessage.model_validate(parsed)
    except ValidationError:
        raise _Rejected(QuarantineReason.INVALID_WIRE, parsed) from None
    if message.cloud != cloud:
        raise _Rejected(QuarantineReason.CLOUD_MISMATCH, parsed)
    contract = _validate_contract_or_reject(message, parsed)
    try:
        event_time = _event_time(contract)
        ingestion_time = parse_timestamp(message.received_at)
    except ValueError:
        raise _Rejected(QuarantineReason.INVALID_SCHEMA, parsed) from None
    return NormalizedEvent(
        message=message,
        contract=contract,
        event_time=event_time,
        ingestion_time=ingestion_time,
        late=False,  # decided by the watermark step
        doc_id=compute_doc_id(message.customer_id, message.source_id, message.event_id),
        partition_id=raw.partition_id,
        offset=raw.offset,
        sequence_number=raw.sequence_number,
    )


def _validate_contract_or_reject(message: HubMessage, parsed: Any) -> TelemetryEvent | CostRecord:
    try:
        contract = _validate_contract(message)
    except _Rejected as rej:
        raise _Rejected(rej.reason, parsed) from None
    if contract.cloud != message.cloud:
        raise _Rejected(QuarantineReason.CLOUD_MISMATCH, parsed)
    contract_event_id = (
        contract.event_id.root if isinstance(contract, TelemetryEvent) else contract.cost_id.root
    )
    if (
        contract.customer_id.root != message.customer_id
        or contract.source_id.root != message.source_id
        or contract_event_id != message.event_id
    ):
        raise _Rejected(QuarantineReason.INVALID_SCHEMA, parsed)
    return contract


def _known_id(parsed: Any, name: str) -> str | None:
    if isinstance(parsed, dict):
        value = parsed.get(name)
        if isinstance(value, str) and 0 < len(value) <= _MAX_ID_LENGTH:
            return value
    return None


def _origin_doc_id(raw: RawMessage) -> str:
    material = f"quarantine|{raw.partition_id}|{raw.offset}|{raw.sequence_number}"
    return hashlib.sha256(material.encode()).hexdigest()


def _quarantine_record(
    raw: RawMessage,
    reason: QuarantineReason,
    attempts: int,
    parsed: Any,
    now: datetime,
    doc_id: str | None = None,
) -> QuarantineRecord:
    clean: Any = None
    if isinstance(parsed, (dict, list)):
        clean, _ = drop_body_fields(parsed)
    return QuarantineRecord(
        doc_id=doc_id or _origin_doc_id(raw),
        reason=reason,
        attempts=attempts,
        partition_id=raw.partition_id,
        offset=raw.offset,
        sequence_number=raw.sequence_number,
        enqueued_time=raw.enqueued_time,
        quarantined_at=now,
        customer_id=_known_id(parsed, "customer_id"),
        source_id=_known_id(parsed, "source_id"),
        event_id=_known_id(parsed, "event_id"),
        payload=clean,
        # Unparseable bytes may hold a prompt: keep only a hash and a length.
        payload_sha256=None if clean is not None else hashlib.sha256(raw.body).hexdigest(),
        payload_bytes=None if clean is not None else len(raw.body),
    )


async def process_batch(
    messages: Sequence[RawMessage], deps: PipelineDeps, settings: IngestionSettings
) -> BatchResult:
    """Handle every message durably (accept, duplicate-skip or quarantine) or raise.

    Returning means ``BatchResult.checkpoint`` (the last message) is safe to commit. Raising
    means it is not.
    """
    policy = BackoffPolicy(
        max_attempts=settings.max_attempts,
        base_delay_seconds=settings.backoff_base_seconds,
        max_delay_seconds=settings.backoff_max_seconds,
    )
    lateness = timedelta(seconds=settings.lateness_seconds)
    newest: dict[tuple[str, str], datetime | None] = {}
    accepted = duplicates = late = 0
    quarantined: dict[QuarantineReason, int] = {}

    async def with_retry(op: Callable[[], Awaitable[None]]) -> None:
        await retry_with_backoff(op, policy, sleep=deps.sleep, rng=deps.rng)

    async def quarantine(record: QuarantineRecord) -> None:
        await deps.quarantine.write(record)  # a failure here propagates: no checkpoint
        quarantined[record.reason] = quarantined.get(record.reason, 0) + 1

    for raw in messages:
        try:
            event = _parse(raw, deps.cloud)
        except _Rejected as rej:
            await quarantine(_quarantine_record(raw, rej.reason, 1, rej.parsed, deps.clock()))
            continue

        key = event.key
        if await deps.markers.is_accepted(key):
            duplicates += 1
            continue

        wm_key = (key.customer_id, key.source_id)
        if wm_key not in newest:
            newest[wm_key] = await deps.watermarks.get(*wm_key)
        seen = newest[wm_key]
        is_late = seen is not None and event.event_time < seen - lateness
        event = event.model_copy(update={"late": is_late})

        try:
            await with_retry(lambda e=event: deps.archive.write(e))
            await with_retry(lambda e=event: deps.ledger.accept(e))
        except DependencyTransientError:
            await quarantine(
                _quarantine_record(
                    raw,
                    QuarantineReason.RETRY_BUDGET_EXHAUSTED,
                    policy.max_attempts,
                    event.message.model_dump(mode="json"),
                    deps.clock(),
                    doc_id=event.doc_id,
                )
            )
            continue

        # Marker LAST, then the watermark (crash rule, module docstring).
        await deps.markers.mark_accepted(key)
        newest[wm_key] = await deps.watermarks.advance(*wm_key, event.event_time)
        accepted += 1
        late += int(is_late)

    return BatchResult(
        accepted=accepted,
        duplicates=duplicates,
        late=late,
        quarantined=quarantined,
        outcome=(
            BatchOutcome.QUARANTINED if quarantined and not accepted else BatchOutcome.ACCEPTED
        ),
        checkpoint=messages[-1].checkpoint if messages else None,
    )
