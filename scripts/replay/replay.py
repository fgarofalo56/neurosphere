"""Quarantine replay CLI (PRP-07 item 3).

    python scripts/replay/replay.py list [--reason R] [--customer C] [--date YYYY-MM-DD]
    python scripts/replay/replay.py inspect <doc_id>
    python scripts/replay/replay.py replay (--id <doc_id> | --reason R | --customer C | --date D)
                                          [--dry-run]

Replay re-injects a quarantined record through the SAME ``process_batch`` the normalizer runs
(validation, redaction re-check, dedupe, sinks). It never writes the ledger directly. The
``replayed/{doc_id}.json`` marker is written only after ``process_batch`` accepted the event.
``--dry-run`` validates against in-memory fakes and writes nothing anywhere.

Exit codes: 0 ok, 1 refused or failed, 2 bad arguments.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import UTC, date, datetime
from io import TextIOWrapper
from typing import Any, TextIO, cast

from neurosphere_core.payload import find_body_fields
from neurosphere_workers.ingestion.fakes import (
    FakeArchiveSink,
    FakeLedgerSink,
    FakeMarkerStore,
    FakeQuarantineSink,
    FakeWatermarkStore,
)
from neurosphere_workers.ingestion.models import QuarantineRecord, RawMessage
from neurosphere_workers.ingestion.pipeline import PipelineDeps, process_batch
from neurosphere_workers.ingestion.reasons import QuarantineReason
from neurosphere_workers.ingestion.settings import IngestionSettings
from neurosphere_workers.quarantine import BlobContainer, BlobQuarantineReader
from pydantic import ValidationError

ContainerFactory = Callable[[], AbstractAsyncContextManager[BlobContainer]]
DepsFactory = Callable[[], AbstractAsyncContextManager[PipelineDeps]]

EXIT_OK, EXIT_FAILED, EXIT_USAGE = 0, 1, 2


@asynccontextmanager
async def default_container() -> AsyncIterator[BlobContainer]:
    from neurosphere_core.clients import ClientLifetime
    from neurosphere_core.cloud import load_settings
    from neurosphere_workers.quarantine import create_quarantine_container

    async with ClientLifetime() as lifetime:
        yield cast(BlobContainer, create_quarantine_container(load_settings(), lifetime=lifetime))


@asynccontextmanager
async def default_deps() -> AsyncIterator[PipelineDeps]:
    """Real sinks via ``ingestion.__main__.build_sinks`` plus the Cosmos marker/watermark stores.

    ``build_sinks`` fails closed until the archive and ledger sinks are wired; the CLI then exits 1.
    """
    from neurosphere_core.clients import ClientLifetime, create_cosmos_client
    from neurosphere_core.cloud import CloudName, load_settings
    from neurosphere_workers.ingestion.__main__ import build_sinks
    from neurosphere_workers.ingestion.cosmos_stores import (
        CosmosAcceptedMarkerStore,
        CosmosWatermarkStore,
    )

    settings = load_settings()
    ingestion = IngestionSettings()
    sinks = build_sinks()
    async with ClientLifetime() as lifetime:
        cosmos = create_cosmos_client(settings, lifetime=lifetime, account=ingestion.cosmos_account)
        database = cosmos.get_database_client(ingestion.cosmos_database)
        yield PipelineDeps(
            quarantine=sinks.quarantine,
            archive=sinks.archive,
            ledger=sinks.ledger,
            markers=CosmosAcceptedMarkerStore(
                database.get_container_client(ingestion.markers_container)
            ),
            watermarks=CosmosWatermarkStore(
                database.get_container_client(ingestion.watermarks_container)
            ),
            cloud=(settings.cloud or CloudName.COMMERCIAL).value,
        )


def _dry_run_deps(record: QuarantineRecord) -> PipelineDeps:
    payload = record.payload
    cloud = payload.get("cloud") if isinstance(payload, dict) else None
    return PipelineDeps(
        quarantine=FakeQuarantineSink(),
        archive=FakeArchiveSink(),
        ledger=FakeLedgerSink(),
        markers=FakeMarkerStore(),
        watermarks=FakeWatermarkStore(),
        cloud=cloud if isinstance(cloud, str) else "commercial",
    )


def to_raw_message(record: QuarantineRecord) -> RawMessage:
    """Re-serialize the stored (already body-dropped) payload as the wire bytes."""
    return RawMessage(
        body=json.dumps(record.payload, separators=(",", ":")).encode(),
        partition_id=record.partition_id,
        offset=record.offset,
        sequence_number=record.sequence_number,
        enqueued_time=record.enqueued_time,
    )


def _iso_date(value: str) -> str:
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        raise argparse.ArgumentTypeError("expected YYYY-MM-DD") from None


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> Any:  # exit 2, no traceback
        self.print_usage(sys.stderr)
        self.exit(EXIT_USAGE, f"{self.prog}: error: {message}\n")


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="replay", description="Inspect and replay quarantined telemetry.")
    sub = parser.add_subparsers(dest="command", required=True, parser_class=_Parser)

    def add_filters(p: argparse.ArgumentParser) -> None:
        p.add_argument("--reason", type=QuarantineReason, choices=list(QuarantineReason))
        p.add_argument("--customer", help="customer_id")
        p.add_argument("--date", type=_iso_date, help="quarantined date, YYYY-MM-DD (UTC)")

    add_filters(sub.add_parser("list", help="list quarantined records"))
    inspect = sub.add_parser("inspect", help="show one record (metadata and payload)")
    inspect.add_argument("doc_id")
    rep = sub.add_parser("replay", help="re-inject records through the normalizer pipeline")
    rep.add_argument("--id", dest="doc_id")
    add_filters(rep)
    rep.add_argument("--dry-run", action="store_true", help="validate only; write nothing")
    return parser


class _Out:
    def __init__(self, out: TextIO, err: TextIO) -> None:
        self.out, self.err = out, err

    def line(self, text: str) -> None:
        print(text, file=self.out)

    def problem(self, text: str) -> None:
        print(text, file=self.err)


async def _load(
    reader: BlobQuarantineReader, doc_id: str, io: _Out, *, quiet: bool = False
) -> QuarantineRecord | None:
    """Load a record. A blob that fails the record model (body fields present, or corrupt) is
    refused: it is reported by id only and its content is never printed."""
    try:
        record = await reader.get(doc_id)
    except ValidationError:
        io.problem(f"{doc_id}: refused, redaction check failed or record invalid")
        return None
    if record is None and not quiet:
        io.problem(f"{doc_id}: not found")
    return record


async def _cmd_list(reader: BlobQuarantineReader, args: argparse.Namespace, io: _Out) -> int:
    ids = await reader.list_doc_ids(reason=args.reason, customer_id=args.customer, date=args.date)
    for doc_id in ids:
        record = await _load(reader, doc_id, io, quiet=True)
        if record is None:
            continue
        io.line(
            f"{doc_id}  {record.reason.value}  customer={record.customer_id or '-'}  "
            f"date={record.quarantined_at.astimezone(UTC).date().isoformat()}  "
            f"attempts={record.attempts}  replayable={record.payload is not None}"
        )
    io.line(f"{len(ids)} record(s)")
    return EXIT_OK


async def _cmd_inspect(reader: BlobQuarantineReader, args: argparse.Namespace, io: _Out) -> int:
    record = await _load(reader, args.doc_id, io)
    if record is None:
        return EXIT_FAILED
    if record.payload is not None and find_body_fields(record.payload):
        io.problem(f"refused: {args.doc_id} holds prompt/response fields; not printing")
        return EXIT_FAILED
    shown = json.loads(record.model_dump_json())
    shown["replayed"] = await reader.is_replayed(args.doc_id)
    io.line(json.dumps(shown, indent=2, sort_keys=True))
    return EXIT_OK


async def _replay_one(
    reader: BlobQuarantineReader,
    doc_id: str,
    *,
    dry_run: bool,
    deps_factory: DepsFactory,
    io: _Out,
) -> bool:
    """True when the record is in a good end state (replayed now, or already replayed)."""
    record = await _load(reader, doc_id, io)
    if record is None:
        return False
    if record.payload is None:
        io.problem(f"{doc_id}: not replayable (unparseable payload; only a hash was stored)")
        return False
    if find_body_fields(record.payload):
        io.problem(f"{doc_id}: refused, redaction check failed (prompt/response fields present)")
        return False
    if await reader.is_replayed(doc_id):
        io.line(f"{doc_id}: already replayed")
        return True

    raw = to_raw_message(record)
    settings = IngestionSettings()
    try:
        if dry_run:
            result = await process_batch([raw], _dry_run_deps(record), settings)
        else:
            async with deps_factory() as deps:
                result = await process_batch([raw], deps, settings)
    except Exception as exc:  # report the type only: messages can echo payload content
        io.problem(f"{doc_id}: replay failed ({type(exc).__name__})")
        return False

    if result.quarantined_total or result.accepted + result.duplicates != 1:
        reasons = ",".join(sorted(r.value for r in result.quarantined)) or "none"
        io.problem(f"{doc_id}: refused by the pipeline (quarantined: {reasons})")
        return False
    if dry_run:
        io.line(f"{doc_id}: dry-run ok, would replay (nothing written)")
        return True
    await reader.mark_replayed(doc_id, at=datetime.now(UTC))
    outcome = "duplicate, already accepted" if result.duplicates else "accepted"
    io.line(f"{doc_id}: replayed ({outcome})")
    return True


async def _cmd_replay(
    reader: BlobQuarantineReader,
    args: argparse.Namespace,
    deps_factory: DepsFactory,
    io: _Out,
) -> int:
    if args.doc_id:
        ids = [args.doc_id]
    else:
        ids = await reader.list_doc_ids(
            reason=args.reason, customer_id=args.customer, date=args.date
        )
        io.line(f"{len(ids)} record(s) match")
    ok = True
    for doc_id in ids:
        ok = (
            await _replay_one(
                reader, doc_id, dry_run=args.dry_run, deps_factory=deps_factory, io=io
            )
            and ok
        )
    return EXIT_OK if ok else EXIT_FAILED


async def _run(
    args: argparse.Namespace,
    container_factory: ContainerFactory,
    deps_factory: DepsFactory,
    io: _Out,
) -> int:
    async with container_factory() as container:
        reader = BlobQuarantineReader(container)
        if args.command == "list":
            return await _cmd_list(reader, args, io)
        if args.command == "inspect":
            return await _cmd_inspect(reader, args, io)
        return await _cmd_replay(reader, args, deps_factory, io)


def main(
    argv: Sequence[str] | None = None,
    *,
    container_factory: ContainerFactory = default_container,
    deps_factory: DepsFactory = default_deps,
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> int:
    io = _Out(out or sys.stdout, err or sys.stderr)
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else EXIT_USAGE
    if args.command == "replay" and not (args.doc_id or args.reason or args.customer or args.date):
        parser.print_usage(io.err)
        io.problem("replay: give --id or at least one of --reason/--customer/--date")
        return EXIT_USAGE
    try:
        return asyncio.run(_run(args, container_factory, deps_factory, io))
    except Exception as exc:  # config/auth/connectivity: type only, never a payload
        reason = getattr(exc, "reason", None)
        io.problem(f"failed: {type(exc).__name__}" + (f" ({reason})" if reason else ""))
        return EXIT_FAILED


if __name__ == "__main__":
    if isinstance(sys.stdout, TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
