"""DR command line (PRP-21 item 5).

    python infra/dr/ns_dr.py backup  --out DIR --database DB [--cosmos-container C ...]
                                     [--blob-container C ...]
    python infra/dr/ns_dr.py restore --from DIR --database DB [--cosmos-container C ...]
                                     [--blob-container C ...]
    python infra/dr/ns_dr.py drill   [--evidence-dir docs/evidence/G07/dr]

Defaults address the local compose emulators only. A non-local endpoint is refused unless
``NS_LIVE_APPROVED=1`` AND ``--target NAME`` are given; a restore to a non-local target also
needs ``--confirm-target NAME`` (identical). ``restore`` upserts and never deletes. The drill
touches only ``drill-`` namespaced resources.

Exit codes: 0 ok, 1 failed or mismatch, 2 refused target or bad arguments.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ns_dr_stores as stores
from azure.cosmos.aio import CosmosClient
from azure.storage.blob.aio import BlobServiceClient
from ns_dr_emulator import Connections, load_connections
from ns_dr_safety import (
    TargetPolicy,
    TargetRefusedError,
    authorize,
    blob_endpoint_from_connection_string,
)

EXIT_OK, EXIT_FAILED, EXIT_REFUSED = 0, 1, 2
REPO_ROOT = Path(__file__).resolve().parents[2]
DRILL_COMMAND = "uv run python infra/dr/ns_dr.py drill --evidence-dir docs/evidence/G07/dr"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ns_dr", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("backup", "restore", "drill"):
        p = sub.add_parser(name)
        p.add_argument("--target", help="name of an approved non-local target")
        p.add_argument("--confirm-target", help="must equal --target for a non-local restore")
        if name == "drill":
            p.add_argument("--evidence-dir", type=Path, default=None)
            p.add_argument("--work-dir", type=Path, default=None)
        else:
            p.add_argument("--database", required=True)
            p.add_argument("--cosmos-container", action="append", default=[])
            p.add_argument("--blob-container", action="append", default=[])
            if name == "backup":
                p.add_argument("--out", type=Path, required=True)
            else:
                p.add_argument("--from", dest="source", type=Path, required=True)
    return parser


def check_target(args: argparse.Namespace, conn: Connections, env: dict[str, str]) -> None:
    """Raise ``TargetRefusedError`` unless all endpoints are local or a live target is approved."""
    endpoints = [
        conn.cosmos_endpoint,
        blob_endpoint_from_connection_string(conn.blob_connection_string),
    ]
    policy = TargetPolicy(target=args.target, confirm_target=args.confirm_target, env=env)
    authorize(endpoints, policy, restore=args.command in {"restore", "drill"})


async def _backup(args: argparse.Namespace, conn: Connections) -> int:
    manifest: dict[str, Any] = {"taken_at": datetime.now(UTC).isoformat(), "stores": {}}
    async with CosmosClient(
        conn.cosmos_endpoint, conn.cosmos_key, enable_endpoint_discovery=False
    ) as cosmos:
        db = cosmos.get_database_client(args.database)
        for name in args.cosmos_container:
            d = await stores.backup_cosmos_container(db, name, args.out)
            manifest["stores"][f"cosmos:{name}"] = {"count": d.count, "sha256": d.sha256}
    async with BlobServiceClient.from_connection_string(conn.blob_connection_string) as blob:
        for name in args.blob_container:
            d = await stores.backup_blob_container(blob, name, name, args.out)
            manifest["stores"][f"blob:{name}"] = {"count": d.count, "sha256": d.sha256}
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", "utf-8")
    print(json.dumps(manifest["stores"], indent=2))
    return EXIT_OK


async def _restore(args: argparse.Namespace, conn: Connections) -> int:
    async with CosmosClient(
        conn.cosmos_endpoint, conn.cosmos_key, enable_endpoint_discovery=False
    ) as cosmos:
        db = await stores.ensure_cosmos(cosmos, args.database, args.cosmos_container)
        for name in args.cosmos_container:
            n = await stores.restore_cosmos_container(db, name, args.source)
            print(f"restored cosmos:{name} documents={n}")
    async with BlobServiceClient.from_connection_string(conn.blob_connection_string) as blob:
        for name in args.blob_container:
            n = await stores.restore_blob_container(blob, name, name, args.source)
            print(f"restored blob:{name} blobs={n}")
    return EXIT_OK


def _git_sha() -> str:
    out = subprocess.run(
        ["git", "rev-parse", "HEAD"],  # noqa: S607
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return out.stdout.strip() or "unknown"


async def _drill(args: argparse.Namespace, conn: Connections) -> int:
    import ns_dr_drill as drill

    result = await drill.run_drill(conn, work_dir=args.work_dir)
    doc = drill.result_to_dict(result)
    evidence: dict[str, Any] = {
        "schema_version": "1",
        "gate": "G07",
        "item": "PRP-21 item 5 backup-restore-and-failover",
        "environment_label": drill.ENV_LABEL,
        "date": datetime.now().astimezone().date().isoformat(),  # operator-local calendar day
        "git_sha": _git_sha(),
        "command": DRILL_COMMAND,
        "method": (
            "Seed drill-namespaced stores from the sandbox generator (seed 7, tiny profile), "
            "export each store, write extra data after the backup, delete the drill namespace, "
            "restore from the export, and compare live count and content-hash digests of the "
            "restored store with the digests taken before the backup."
        ),
        "dataset": "sandbox generator seed 7, tiny profile, synthetic only",
        "provisional_targets": {
            "rto": "4 h (provisional target)",
            "rpo": "15 min (provisional target)",
        },
        "measured": doc,
        "notes": [
            "A restore drill proves a restore, not a failover.",
            "The recovery point gap here follows from the short, test-chosen interval between "
            "the last backed-up write and the simulated loss; it says nothing about a 15 min "
            "backup cadence.",
            "Event Hubs emulator has no persistence: event-data recovery on compose is replay "
            "from the redacted archive (scripts/replay) plus source producers; not exercised "
            "here beyond archive blob restore.",
            "Search is rebuilt from the restored catalog into the in-process fixture index.",
        ],
        "open": [
            "Real Event Hubs failover and failback (needs an approved environment).",
            "Event Hubs data geo-replication (Premium/Dedicated; Government unverified).",
            "Production-sized restore time and recovery point.",
            "Azure AI Search index rebuild time.",
        ],
    }
    print(json.dumps(evidence, indent=2))
    if args.evidence_dir is not None:
        args.evidence_dir.mkdir(parents=True, exist_ok=True)
        name = f"restore-drill-compose-{evidence['date']}.json"
        (args.evidence_dir / name).write_text(json.dumps(evidence, indent=2) + "\n", "utf-8")
    return EXIT_OK if result.all_match else EXIT_FAILED


def main(argv: list[str] | None = None, env: dict[str, str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    environ = dict(os.environ) if env is None else env
    conn = load_connections(environ)
    try:
        check_target(args, conn, environ)
    except TargetRefusedError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    runner = {"backup": _backup, "restore": _restore, "drill": _drill}[args.command]
    return asyncio.run(runner(args, conn))


if __name__ == "__main__":
    sys.exit(main())
