"""Local emulator run for the live-map routes (PRP-74 item 5). NOT part of CI.

    docker compose up -d --wait cosmos
    uv run python -m tests.load.map_topology.run_emulator --entities 50000 \
        --out docs/evidence/G07/map/server-timings.json

Seeds a dedicated throwaway database (deleted afterwards) with one perf domain, then measures the
viewport (cluster overview and one 2000-node page), search, impact at depth 5 and one topology
poll through the real routes, with wall time and Cosmos reads per call. MEASURED, never asserted.
The vNext emulator has no RU accounting, so ``ru_per_call`` is ``null`` unless it sends a charge.
Uses ``127.0.0.1`` (``localhost`` resolves to ``::1`` and the Docker IPv6 forward is flaky).
"""

import argparse
import asyncio
import base64
import ctypes
import json
import os
import platform
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")  # pyright: ignore[reportAttributeAccessIssue]

from neurosphere_core.catalog import PartitionKeyShape
from neurosphere_core.catalog.repo.cosmos import (
    CosmosCatalogRepository,
    create_catalog_container,
)
from neurosphere_core.clients import ClientLifetime, create_cosmos_client
from neurosphere_core.cloud import Settings

from .measure import CALL_NAMES, CountingContainer, run_calls
from .world import (
    IMPACT_AGENTS,
    PERF_DOMAIN,
    background_docs,
    background_edges,
    build_api,
    impact_docs,
    impact_edges,
    load_world,
)

ENDPOINT = "http://127.0.0.1:8081"
SHAPE = PartitionKeyShape.FLAT_DOMAIN
SLOW_MS = 2000.0
ROOT = Path(__file__).resolve().parents[3]


def _git(*args: str) -> str:
    done = subprocess.run(  # fixed argv, no shell
        ["git", *args], capture_output=True, text=True, cwd=ROOT, check=False
    )
    return done.stdout.strip()


def hardware() -> dict[str, Any]:
    cpu: str | None = None
    ram_gb: float | None = None
    if sys.platform == "win32":
        import winreg

        try:
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
            )
            cpu = str(winreg.QueryValueEx(key, "ProcessorNameString")[0]).strip()
        except OSError:
            cpu = None

        class _Mem(ctypes.Structure):
            _fields_ = (
                ("length", ctypes.c_ulong),
                ("load", ctypes.c_ulong),
                ("total_phys", ctypes.c_ulonglong),
                ("avail_phys", ctypes.c_ulonglong),
                ("total_page", ctypes.c_ulonglong),
                ("avail_page", ctypes.c_ulonglong),
                ("total_virtual", ctypes.c_ulonglong),
                ("avail_virtual", ctypes.c_ulonglong),
                ("avail_ext", ctypes.c_ulonglong),
            )

        mem = _Mem()
        mem.length = ctypes.sizeof(_Mem)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(mem)):  # type: ignore[attr-defined]
            ram_gb = round(mem.total_phys / 2**30, 1)
    return {
        "cpu_model": cpu or platform.processor() or None,
        "logical_cores": os.cpu_count(),
        "ram_gb": ram_gb,
        "os": platform.platform(),
        "python": platform.python_version(),
    }


async def _emulator_reachable() -> str | None:
    """``None`` when the emulator answers on TCP 8081, else the exact reason."""
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection("127.0.0.1", 8081), 5)
    except (OSError, TimeoutError) as exc:
        return f"emulator not reachable at 127.0.0.1:8081: {type(exc).__name__}: {exc}"
    writer.close()
    return None


async def _cleanup(client: Any, db_name: str) -> str | None:
    """Delete the throwaway database; return the failure text instead of losing the results."""
    try:
        await client.delete_database(db_name)
    except Exception as exc:  # cleanup must never discard the measurements
        return f"throwaway database {db_name} NOT deleted: {type(exc).__name__}: {str(exc)[:200]}"
    return None


async def measure(entities: int, concurrency: int, repeats: int) -> dict[str, Any]:
    os.environ["NS_ENV"] = "local"
    os.environ["NS_COSMOS_ENDPOINT"] = ENDPOINT
    # The emulator ignores the key; any base64 string works (as in the conformance tests).
    os.environ["NS_COSMOS_KEY"] = base64.b64encode(b"emulator-ignores-this").decode()
    db_name = f"ns_perf_prp74_{uuid.uuid4().hex[:10]}"
    async with ClientLifetime() as lifetime:
        client = create_cosmos_client(Settings(env="local"), lifetime=lifetime)
        database = await client.create_database_if_not_exists(db_name)
        try:
            container = await create_catalog_container(database, "catalog", SHAPE)
            counter = CountingContainer(container)
            repo = CosmosCatalogRepository(counter, SHAPE)  # type: ignore[arg-type]
            perf = await build_api(repo)
            background = max(0, entities - IMPACT_AGENTS - 1)
            docs = background_docs(background) + impact_docs()
            edges = background_edges(background) + impact_edges()
            start = time.perf_counter()
            await load_world(perf, docs, edges, concurrency=concurrency)
            seed_seconds = time.perf_counter() - start
            print(f"seeded {len(docs)} entities, {len(edges)} edges in {seed_seconds:.0f}s")
            counter.reads = counter.queries = 0
            results = await run_calls(perf, counter, repeats=repeats, heavy_repeats=3)
            await perf.client.aclose()
        finally:
            cleanup_error = await _cleanup(client, db_name)
    return {
        "dataset": {
            "domain": PERF_DOMAIN,
            "entities": len(docs),
            "edges": len(edges),
            "impact_tree_dependents": IMPACT_AGENTS,
            "seed_seconds": round(seed_seconds, 1),
        },
        "cleanup": cleanup_error or f"throwaway database {db_name} deleted",
        "calls": {r.name: r.summary() for r in results},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--entities", type=int, default=50_000)
    parser.add_argument("--concurrency", type=int, default=32)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    record: dict[str, Any] = {
        "schema": "ns.map.server-timings/1",
        "measured_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "commit": _git("rev-parse", "HEAD"),
        "branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        "hardware": hardware(),
        "target": "Cosmos NoSQL vNext emulator on 127.0.0.1:8081, local loopback, in-process app",
        "no_target_asserted": True,
    }
    reason = asyncio.run(_emulator_reachable())
    if reason is not None:
        record.update(measured=False, not_measured=reason, calls={}, follow_ups=[], notes=[])
    else:
        record.update(
            measured=True, **asyncio.run(measure(args.entities, args.concurrency, args.repeats))
        )
        slow = [
            f"{name}: median {c['wall_ms_median']} ms (p95 {c['wall_ms_p95']} ms) "
            f"exceeds {SLOW_MS:.0f} ms"
            for name, c in record["calls"].items()
            if c["wall_ms_median"] > SLOW_MS
        ]
        record["follow_ups"] = slow
        record["notes"] = [
            "No target is asserted; every number is as measured on this machine, once.",
            "ru_per_call is null: the vNext emulator returns x-ms-request-charge 1 on every "
            "request, a constant, not request units. Real RU needs a live account (gate G03/G07 "
            "OPEN).",
            "cosmos_reads_per_call counts paged query round trips through the repository's "
            "container (point reads are queries here); the Python app and the Cosmos emulator "
            "share one machine, so wall time includes loopback and emulator CPU.",
            "The graph search index is an empty fixture; the four routes scan the repository, "
            "they do not use Azure AI Search.",
            "Entities are seeded straight into the repository backend (not create_entity) to skip "
            "the per-write duplicate lookup; stored documents have the same shape.",
            "Delete of the throwaway database fails on this emulator for every database, even an "
            "empty one (E58P01); see the cleanup field.",
        ]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.out}; calls: {', '.join(CALL_NAMES)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
