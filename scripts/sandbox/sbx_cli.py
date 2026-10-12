"""Sandbox seed / replay / reset CLI (PRP-03 item 4).

    python scripts/sandbox/sbx_cli.py seed   [--data-dir temp/sandbox]
    python scripts/sandbox/sbx_cli.py replay [--data-dir temp/sandbox] [--rate N] [--order ...]
    python scripts/sandbox/sbx_cli.py reset

Everything is local-emulator only: sandbox- prefixed Cosmos names, loopback endpoints, settings
from NS_SANDBOX_* environment variables. See sbx_guard.py.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sbx_guard import GuardError
from sbx_seam import DATABASE, CosmosSeam, HubSeam, SeedStats

ENTITY_FILES = (
    "domains.ndjson",
    "owners.ndjson",
    "persons.ndjson",
    "model_deployments.ndjson",
    "grounding_sources.ndjson",
    "tools.ndjson",
    "agents.ndjson",
    "agent_versions.ndjson",
)
RELATION_FILES = ("relations.ndjson",)
CONTAINERS = {"sandbox-entities": ENTITY_FILES, "sandbox-relations": RELATION_FILES}
ORDERS = ("arrival", "event-time", "reverse")


def read_docs(path: Path) -> Iterator[dict[str, Any]]:
    with path.open("rb") as handle:
        for raw in handle:
            if raw.strip():
                yield json.loads(raw)


def read_lines(path: Path) -> list[bytes]:
    """Raw telemetry lines without the trailing newline (malformed lines kept verbatim)."""
    with path.open("rb") as handle:
        return [raw.rstrip(b"\r\n") for raw in handle if raw.strip()]


def _event_time_key(item: tuple[int, bytes]) -> tuple[int, float, int]:
    index, line = item
    try:
        value = json.loads(line)["event_time"]
        return (0, datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp(), index)
    except (ValueError, KeyError, TypeError, AttributeError):
        return (1, 0.0, index)  # unparsable lines sort last, in arrival order


def order_lines(lines: list[bytes], order: str) -> list[bytes]:
    if order == "arrival":
        return list(lines)
    if order == "reverse":
        return lines[::-1]
    if order == "event-time":
        return [line for _, line in sorted(enumerate(lines), key=_event_time_key)]
    raise ValueError(f"unknown order {order!r}")


def _require_data(data_dir: Path) -> None:
    if not (data_dir / "run-manifest.json").is_file():
        raise SystemExit(
            f"no generated data in {data_dir}; run: python -m sandbox.generate --seed 1 "
            f"--profile tiny --cloud commercial --out {data_dir}"
        )


def publish_events(
    data_dir: Path, rate: float, order: str, append: bool, hub: HubSeam
) -> dict[str, int]:
    """Idempotent unless `append`: skips when the hub already holds the expected count."""
    lines = read_lines(data_dir / "telemetry.ndjson")
    expected = len(lines)
    present = hub.event_count()
    if not append and present == expected:
        return {"expected": expected, "present_before": present, "sent": 0}
    if not append and present != 0:
        raise SystemExit(
            f"hub holds {present} events, expected 0 or {expected}; the emulator keeps no "
            "persistence control here, run `make dev-reset` or `make seed-reset`"
        )
    sent = hub.publish(iter(order_lines(lines, order)), rate=rate)
    return {"expected": expected, "present_before": present, "sent": sent}


def cmd_seed(args: argparse.Namespace) -> int:
    data_dir = Path(args.data_dir)
    _require_data(data_dir)
    cosmos = CosmosSeam()
    db = cosmos.ensure_database(DATABASE)
    stats = SeedStats()
    for name, files in CONTAINERS.items():
        container = cosmos.ensure_container(db, name)
        for file in files:
            cosmos.upsert_all(container, name, read_docs(data_dir / file), stats)
    result: dict[str, Any] = {
        "database": DATABASE,
        "documents": {
            "created": stats.created,
            "updated": stats.updated,
            "unchanged": stats.unchanged,
        },
        "per_container": stats.per_container,
        "totals": {name: cosmos.count(DATABASE, name) for name in CONTAINERS},
    }
    if not args.no_events:
        result["events"] = publish_events(data_dir, 0.0, "arrival", False, HubSeam())
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def cmd_replay(args: argparse.Namespace) -> int:
    data_dir = Path(args.data_dir)
    _require_data(data_dir)
    result = publish_events(data_dir, args.rate, args.order, args.append, HubSeam())
    print(json.dumps({"events": result}, indent=2, sort_keys=True))
    return 0


def cmd_reset(_args: argparse.Namespace) -> int:
    cosmos = CosmosSeam()
    dropped = cosmos.list_sandbox_databases()
    for name in dropped:
        cosmos.drop_database(name)
    print(json.dumps({"dropped_databases": dropped}, sort_keys=True))
    print(
        "Event Hubs emulator has no purge API; restart it for an empty hub "
        "(`make seed-reset` does this)."
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    sub = parser.add_subparsers(dest="command", required=True)
    seed = sub.add_parser("seed", help="load Cosmos (idempotent) and the telemetry hub")
    seed.add_argument("--data-dir", default="temp/sandbox")
    seed.add_argument("--no-events", action="store_true", help="skip the hub")
    seed.set_defaults(func=cmd_seed)
    replay = sub.add_parser("replay", help="push telemetry (incl. bad events) to the hub")
    replay.add_argument("--data-dir", default="temp/sandbox")
    replay.add_argument("--rate", type=float, default=0.0, help="events/second; 0 = unthrottled")
    replay.add_argument("--order", choices=ORDERS, default="arrival")
    replay.add_argument(
        "--append", action="store_true", help="send even if events are already present"
    )
    replay.set_defaults(func=cmd_replay)
    reset = sub.add_parser("reset", help="drop sandbox- Cosmos databases")
    reset.set_defaults(func=cmd_reset)
    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except GuardError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
