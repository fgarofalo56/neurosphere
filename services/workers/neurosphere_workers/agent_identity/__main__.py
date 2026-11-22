"""``python -m neurosphere_workers.agent_identity reresolve ...`` (PRP-137 item 4).

Operator job run after declaring or repointing an alias. Exit codes: 0 done, 1 done but the scan
was truncated by ``--max-events``, 2 usage or refused (no customer), 3 dependencies are not wired.

``build_reresolve_dependencies`` is the seam PRP-137 item 6 completes: it needs the aggregates
and catalog handlers built on the RESOLVING source, which only the wiring in
``runtime/factories.py`` can assemble (that file is owned by item 6). Until then the CLI exits 3
with a clear message rather than running with an unresolved source.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime

from neurosphere_core.agent_identity import AgentIdentitySettings, ResolutionStats
from neurosphere_core.aggregates import AggregateStore

from neurosphere_workers.agent_identity.reresolve import (
    EntryHandler,
    ReresolveError,
    reresolve_external_id,
)
from neurosphere_workers.aggregates.handler import AggregateProjection
from neurosphere_workers.runtime.archive_reader import ArchiveReader

__all__ = ["ReresolveDependencies", "build_arg_parser", "build_reresolve_dependencies", "main"]

EXIT_OK = 0
EXIT_TRUNCATED = 1
EXIT_USAGE = 2
EXIT_NOT_WIRED = 3


@dataclass(slots=True)
class ReresolveDependencies:
    reader: ArchiveReader
    store: AggregateStore
    aggregates: AggregateProjection
    catalog: EntryHandler | None
    resolver_stats: ResolutionStats | None = None


DependencyBuilder = Callable[[], Awaitable[ReresolveDependencies]]


class DependenciesNotWiredError(RuntimeError):
    pass


async def build_reresolve_dependencies() -> ReresolveDependencies:
    """SEAM for item 6: build the archive reader, aggregate store, and the aggregates and catalog
    handlers over resolving sources (``ResolvingTraceEventSource`` + ``CatalogAliasLookup``)."""
    raise DependenciesNotWiredError(
        "re-resolution dependencies are not wired yet (PRP-137 item 6 builds them in "
        "runtime/factories.py)"
    )


def _iso(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"not an ISO 8601 timestamp: {value!r}") from exc


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise ReresolveError(message)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="python -m neurosphere_workers.agent_identity")
    sub = parser.add_subparsers(dest="command", required=True)
    job = sub.add_parser("reresolve", help="re-apply archived telemetry after an alias change")
    job.add_argument("--customer", default="", help="customer id (required)")
    job.add_argument("--source-id", required=True)
    job.add_argument("--external-agent-id", required=True)
    job.add_argument("--since", type=_iso, default=None, help="ISO 8601; skip older events")
    job.add_argument("--max-events", type=int, default=None, help="archive records to examine")
    return parser


async def _run(args: argparse.Namespace, builder: DependencyBuilder) -> int:
    customer = str(args.customer).strip()
    if not customer:
        raise ReresolveError("--customer is required")
    max_events = args.max_events or AgentIdentitySettings().rescan_max_events
    deps = await builder()
    report = await reresolve_external_id(
        customer_id=customer,
        source_id=args.source_id,
        external_agent_id=args.external_agent_id,
        since=args.since,
        reader=deps.reader,
        aggregates=deps.aggregates,
        store=deps.store,
        catalog=deps.catalog,
        max_events=max_events,
        resolver_stats=deps.resolver_stats,
    )
    print(json.dumps(report.as_dict(), sort_keys=True))
    return EXIT_TRUNCATED if report.truncated else EXIT_OK


def main(
    argv: Sequence[str] | None = None, *, builder: DependencyBuilder = build_reresolve_dependencies
) -> int:
    try:
        args = build_arg_parser().parse_args(argv)
        return asyncio.run(_run(args, builder))
    except ReresolveError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except DependenciesNotWiredError as exc:
        print(f"not wired: {exc}", file=sys.stderr)
        return EXIT_NOT_WIRED


if __name__ == "__main__":
    sys.exit(main())
