"""Restore drill harness (PRP-21 item 5): seed, back up, lose, restore, verify, measure.

Everything runs against the compose emulators and writes ONLY drill-namespaced resources
(``drill-<run>`` Cosmos database, ``drill-<run>-*`` blob containers). The drill seeds its own
synthetic data from the sandbox generator, never reads other data, and removes only its own
resources when finished. A restore drill proves a restore, not a failover.
"""

from __future__ import annotations

import asyncio
import contextlib
import gzip
import hashlib
import io
import json
import shutil
import sys
import tempfile
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import ns_dr_stores as stores
from azure.cosmos.aio import CosmosClient
from azure.eventhub.extensions.checkpointstoreblobaio import BlobCheckpointStore
from azure.storage.blob.aio import BlobServiceClient
from ns_dr_emulator import EVENTHUBS_NAMESPACE, Connections
from ns_dr_safety import require_drill_name

ENV_LABEL = "compose, not representative of production"
SEED = 7
COST_DOCS = 400
ARCHIVE_BLOBS = 40
QUARANTINE_RECORDS = 25
CHECKPOINT_PARTITIONS = 8
POST_BACKUP_COST_DOCS = 12
COSMOS_CONTAINERS = ["cost-ledger", "outbox", "catalog", "aggregates"]
HUB = "telemetry"
GROUP = "normalizer"
SEARCH_TERMS = ("analyst", "customer support", "engineering", "triage", "monitor")

Doc = dict[str, Any]


@dataclass
class StoreResult:
    store: str
    method: str
    source_count: int
    source_sha256: str
    source_bytes: int
    backup_seconds: float
    restore_seconds: float
    restored_count: int
    restored_sha256: str
    match: bool
    detail: str = ""


@dataclass
class DrillResult:
    run_id: str
    started_at: str
    stores: list[StoreResult] = field(default_factory=list)
    snapshot_completed_at: str = ""
    last_write_in_backup_at: str = ""
    loss_simulated_at: str = ""
    recovery_point_gap_seconds: float = 0.0
    post_backup_writes_lost: int = 0
    post_backup_writes_absent_after_restore: bool = False
    checkpoint_rewound: bool = False
    total_restore_seconds: float = 0.0

    @property
    def all_match(self) -> bool:
        return bool(self.stores) and all(s.match for s in self.stores)


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime) -> str:
    return value.isoformat(timespec="milliseconds")


def _read_ndjson(path: Path, limit: int | None = None) -> list[Doc]:
    out: list[Doc] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                out.append(json.loads(line))
                if limit is not None and len(out) >= limit:
                    break
    return out


def generate_sandbox(directory: Path) -> Path:
    """Synthetic data only: sandbox generator, seed 7, tiny profile, commercial."""
    repo_root = str(Path(__file__).resolve().parents[2])
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)  # the sandbox generator lives at the repo root
    from sandbox.config import PROFILES, GenerateConfig
    from sandbox.generate import generate

    out = directory / "sandbox"
    with contextlib.redirect_stdout(io.StringIO()):  # keep the CLI output pure JSON
        generate(GenerateConfig(seed=SEED, profile=PROFILES["tiny"], cloud="commercial"), out)
    return out


def build_cosmos_seed(sbx: Path, *, cost_limit: int = COST_DOCS) -> dict[str, list[Doc]]:
    catalog: list[Doc] = []
    for name in ("domains", "agents", "tools", "model_deployments", "owners"):
        catalog.extend(_read_ndjson(sbx / f"{name}.ndjson"))
    for doc in catalog:
        doc["customer_id"] = doc.get("customer_id", "synthco")
    ledger = _read_ndjson(sbx / "cost.ndjson", cost_limit)
    for doc in ledger:
        doc["id"] = doc["cost_id"]
    outbox = [
        {
            "id": f"obx-{d['cost_id']}",
            "customer_id": d["customer_id"],
            "sequence": i,
            "ref": d["cost_id"],
            "kind": "cost_recorded",
        }
        for i, d in enumerate(ledger)
    ]
    totals: dict[str, Decimal] = {}
    for d in ledger:
        key = f"{d.get('domain_id', 'none')}|{str(d['recorded_at'])[:13]}"
        totals[key] = totals.get(key, Decimal(0)) + Decimal(str(d["amount"]))
    aggregates = [
        {"id": key, "customer_id": "synthco", "amount": str(total)}
        for key, total in sorted(totals.items())
    ]
    return {"cost-ledger": ledger, "outbox": outbox, "catalog": catalog, "aggregates": aggregates}


def post_backup_cost_docs(base: Doc, n: int) -> list[Doc]:
    out: list[Doc] = []
    for i in range(n):
        doc = dict(base)
        doc["id"] = doc["cost_id"] = f"post-backup-{i:03d}"
        out.append(doc)
    return out


def archive_blobs(sbx: Path, n: int = ARCHIVE_BLOBS) -> list[tuple[str, bytes, dict[str, str]]]:
    """Redacted-archive-shaped blobs: ``{customer}/{domain}/{yyyy}/{mm}/{dd}/{doc}.json.gz``."""
    events = _read_ndjson(sbx / "telemetry.ndjson", n)
    blobs: list[tuple[str, bytes, dict[str, str]]] = []
    for i, ev in enumerate(events):
        payload = gzip.compress(json.dumps(ev, sort_keys=True).encode(), mtime=0)
        name = f"synthco/dom-00{i % 3}/2026/10/01/drill-doc-{i:04d}.json.gz"
        blobs.append((name, payload, {"sha256": hashlib.sha256(payload).hexdigest()}))
    return blobs


def make_quarantine_records(n: int = QUARANTINE_RECORDS) -> list[Any]:
    from neurosphere_workers.ingestion.models import QuarantineRecord
    from neurosphere_workers.ingestion.reasons import QuarantineReason

    reasons = list(QuarantineReason)
    stamp = datetime(2026, 10, 22, 9, 0, tzinfo=UTC)
    return [
        QuarantineRecord(
            doc_id=f"drill-q-{i:04d}",
            reason=reasons[i % len(reasons)],
            attempts=1,
            partition_id=str(i % 4),
            offset=str(1000 + i),
            sequence_number=i,
            enqueued_time=stamp,
            quarantined_at=stamp,
            customer_id="synthco",
            source_id="sandbox-foundry",
            event_id=f"evt-{i:04d}",
            payload={"kind": "synthetic", "n": i},
        )
        for i in range(n)
    ]


async def _timed[T](fn: Callable[[], Awaitable[T]]) -> tuple[T, float]:
    start = time.perf_counter()
    value = await fn()
    return value, time.perf_counter() - start


def _scope(domains: list[str]) -> Any:
    from neurosphere_contracts.scope.v1.identity_scope import IdentityScope

    return IdentityScope.model_validate(
        {
            "schema_version": "1.0.0",
            "cloud": "commercial",
            "customer_id": "synthco",
            "principal": {
                "principal_id": "commercial:synthco:idp:person:drill",
                "principal_pseudonym": "p-drill",
                "principal_kind": "user",
            },
            "roles": [],
            "allowed_domains": domains,
            "allowed_resources": [],
            "policy_version": "v1",
            "derived_at": "2026-10-22T00:00:00Z",
            "scope_hash": "sha256:" + hashlib.sha256(b"drill").hexdigest(),
        }
    )


async def search_fingerprint(catalog_docs: list[Doc]) -> tuple[int, str]:
    """Build the fixture index from catalog documents and hash the answers to fixed queries."""
    from neurosphere_contracts.query.v1.budget import Budget
    from neurosphere_core.search.fixture.index import FixtureSearchIndex, documents_from_catalog
    from neurosphere_core.search.protocol import SearchRequest

    docs = documents_from_catalog(catalog_docs)
    index = FixtureSearchIndex(docs)
    domains = sorted({d.domain_id for d in docs})
    scope = _scope(domains)
    answers: list[Any] = []
    for term in SEARCH_TERMS:
        request = SearchRequest(term=term, budget=Budget(timeout_ms=5000, limit=100, max_depth=0))
        result = await index.search(scope, request)
        answers.append([term, [(h.id, h.score) for h in result.hits], result.matched])
    digest = hashlib.sha256(json.dumps(answers, sort_keys=True).encode()).hexdigest()
    return len(docs), digest


async def _checkpoint_rows(store: BlobCheckpointStore) -> list[Doc]:
    rows = await store.list_checkpoints(EVENTHUBS_NAMESPACE, HUB, GROUP)
    return sorted((dict(r) for r in rows), key=lambda r: str(r["partition_id"]))


async def run_drill(
    conn: Connections, *, work_dir: Path | None = None, run_id: str | None = None
) -> DrillResult:
    run = run_id or uuid.uuid4().hex[:8]
    database = require_drill_name(f"drill-{run}")
    c_archive = require_drill_name(f"drill-{run}-archive")
    c_quarantine = require_drill_name(f"drill-{run}-quarantine")
    c_ckpt = require_drill_name(f"drill-{run}-checkpoints")
    owns_dir = work_dir is None
    root = work_dir or Path(tempfile.mkdtemp(prefix="ns-dr-"))
    root.mkdir(parents=True, exist_ok=True)
    backup_dir = root / "backup"
    result = DrillResult(run_id=run, started_at=_iso(_now()))

    sbx = generate_sandbox(root)
    seed = build_cosmos_seed(sbx)
    arch_seed = archive_blobs(sbx)
    quarantine_seed = make_quarantine_records()

    cosmos = CosmosClient(conn.cosmos_endpoint, conn.cosmos_key, enable_endpoint_discovery=False)
    blob = BlobServiceClient.from_connection_string(conn.blob_connection_string)
    opened: list[BlobCheckpointStore] = []
    try:
        # -- seed (drill namespace only) -------------------------------------------------------
        db = await stores.ensure_cosmos(cosmos, database, COSMOS_CONTAINERS)
        for name, docs in seed.items():
            await stores.upsert_docs(db, name, docs)
        for cname in (c_archive, c_quarantine, c_ckpt):
            await blob.get_container_client(cname).create_container()
        arch_client = blob.get_container_client(c_archive)
        for name, data, meta in arch_seed:
            await arch_client.upload_blob(name, data, overwrite=True, metadata=meta)
        from neurosphere_workers.quarantine import BlobQuarantineReader, BlobQuarantineSink

        q_client = blob.get_container_client(c_quarantine)
        sink = BlobQuarantineSink(q_client)  # type: ignore[arg-type]
        for rec in quarantine_seed:
            await sink.write(rec)
        ckpt_store = BlobCheckpointStore.from_connection_string(conn.blob_connection_string, c_ckpt)
        opened.append(ckpt_store)
        for part in range(CHECKPOINT_PARTITIONS):
            await ckpt_store.update_checkpoint(
                {
                    "fully_qualified_namespace": EVENTHUBS_NAMESPACE,
                    "eventhub_name": HUB,
                    "consumer_group": GROUP,
                    "partition_id": str(part),
                    "offset": str(5000 + part),
                    "sequence_number": 100 + part,
                }
            )
        # The newest write that the backup will contain.
        last_in_backup = _now()

        # -- source digests (live, before backup) ----------------------------------------------
        src_cosmos = {n: await stores.cosmos_digest(db, n) for n in COSMOS_CONTAINERS}
        src_arch = await stores.blob_digest(blob, c_archive)
        src_quar = await stores.blob_digest(blob, c_quarantine)
        src_ckpt = await stores.blob_digest(blob, c_ckpt)
        ckpt_before = await _checkpoint_rows(ckpt_store)
        catalog_docs = await stores.read_cosmos_container(db, "catalog")
        src_search = await search_fingerprint(catalog_docs)

        # -- backup ---------------------------------------------------------------------------
        if backup_dir.exists():
            shutil.rmtree(backup_dir)
        backup_secs: dict[str, float] = {}
        for name in COSMOS_CONTAINERS:
            _, backup_secs[f"cosmos:{name}"] = await _timed(
                lambda n=name: stores.backup_cosmos_container(db, n, backup_dir)
            )
        for label, cname in (
            ("archive", c_archive),
            ("quarantine", c_quarantine),
            ("checkpoints", c_ckpt),
        ):
            _, backup_secs[label] = await _timed(
                lambda lab=label, cn=cname: stores.backup_blob_container(blob, cn, lab, backup_dir)
            )
        snapshot_done = _now()
        result.snapshot_completed_at = _iso(snapshot_done)
        result.last_write_in_backup_at = _iso(last_in_backup)

        # -- writes after the backup: these are the recovery point gap -------------------------
        await asyncio.sleep(1.0)
        extra = post_backup_cost_docs(seed["cost-ledger"][0], POST_BACKUP_COST_DOCS)
        await stores.upsert_docs(db, "cost-ledger", extra)
        await ckpt_store.update_checkpoint(
            {
                "fully_qualified_namespace": EVENTHUBS_NAMESPACE,
                "eventhub_name": HUB,
                "consumer_group": GROUP,
                "partition_id": "0",
                "offset": "9999",
                "sequence_number": 9999,
            }
        )
        loss_at = _now()
        result.loss_simulated_at = _iso(loss_at)
        result.recovery_point_gap_seconds = round((loss_at - last_in_backup).total_seconds(), 3)
        result.post_backup_writes_lost = len(extra)

        # -- simulate loss of the drill namespace (drill-prefixed resources only) ---------------
        await cosmos.delete_database(require_drill_name(database))
        for cname in (c_archive, c_quarantine, c_ckpt):
            await blob.delete_container(require_drill_name(cname))

        # -- restore, timed per store ----------------------------------------------------------
        db2 = await stores.ensure_cosmos(cosmos, database, COSMOS_CONTAINERS)
        for name in COSMOS_CONTAINERS:
            _, secs = await _timed(
                lambda n=name: stores.restore_cosmos_container(db2, n, backup_dir)
            )
            got = await stores.cosmos_digest(db2, name)
            src = src_cosmos[name]
            result.stores.append(
                StoreResult(
                    store=f"cosmos:{name}",
                    method="export documents to jsonl; restore by upsert",
                    source_count=src.count,
                    source_sha256=src.sha256,
                    source_bytes=src.size_bytes,
                    backup_seconds=round(backup_secs[f"cosmos:{name}"], 3),
                    restore_seconds=round(secs, 3),
                    restored_count=got.count,
                    restored_sha256=got.sha256,
                    match=(got.count, got.sha256) == (src.count, src.sha256),
                )
            )
        ledger_now = await stores.read_cosmos_container(db2, "cost-ledger")
        result.post_backup_writes_absent_after_restore = not any(
            str(d["id"]).startswith("post-backup-") for d in ledger_now
        )

        blob_specs = (
            ("blob:archive", "archive", c_archive, src_arch, "export blobs+metadata; re-upload"),
            (
                "blob:quarantine",
                "quarantine",
                c_quarantine,
                src_quar,
                "export blobs+metadata; re-upload",
            ),
            (
                "blob:checkpoints",
                "checkpoints",
                c_ckpt,
                src_ckpt,
                "export checkpoint blobs; re-upload",
            ),
        )
        for store_name, label, cname, src, method in blob_specs:
            _, secs = await _timed(
                lambda lab=label, cn=cname: stores.restore_blob_container(blob, cn, lab, backup_dir)
            )
            got = await stores.blob_digest(blob, cname)
            detail = ""
            ok = (got.count, got.sha256) == (src.count, src.sha256)
            if label == "quarantine":
                reader = BlobQuarantineReader(blob.get_container_client(cname))  # type: ignore[arg-type]
                ids = await reader.list_doc_ids()
                first = await reader.get(ids[0]) if ids else None
                ok = ok and len(ids) == len(quarantine_seed) and first is not None
                detail = f"reader listed {len(ids)} records"
            if label == "checkpoints":
                restored_store = BlobCheckpointStore.from_connection_string(
                    conn.blob_connection_string, cname
                )
                opened.append(restored_store)
                rows = await _checkpoint_rows(restored_store)
                rewound = rows == ckpt_before
                result.checkpoint_rewound = rewound
                ok = ok and rewound
                detail = (
                    "checkpoints read through BlobCheckpointStore equal the snapshot; the "
                    "post-backup checkpoint advance is gone, so consumers re-read from the "
                    "restored offsets (dedupe makes the replay idempotent)"
                )
            result.stores.append(
                StoreResult(
                    store=store_name,
                    method=method,
                    source_count=src.count,
                    source_sha256=src.sha256,
                    source_bytes=src.size_bytes,
                    backup_seconds=round(backup_secs[label], 3),
                    restore_seconds=round(secs, 3),
                    restored_count=got.count,
                    restored_sha256=got.sha256,
                    match=ok,
                    detail=detail,
                )
            )

        async def rebuild() -> tuple[int, str]:
            restored_catalog = await stores.read_cosmos_container(db2, "catalog")
            return await search_fingerprint(restored_catalog)

        rebuilt, secs = await _timed(rebuild)
        result.stores.append(
            StoreResult(
                store="search:index",
                method=(
                    "rebuild the in-process fixture index from the restored catalog container "
                    "(no search emulator on compose); digest = hash of fixed query answers"
                ),
                source_count=src_search[0],
                source_sha256=src_search[1],
                source_bytes=0,
                backup_seconds=0.0,
                restore_seconds=round(secs, 3),
                restored_count=rebuilt[0],
                restored_sha256=rebuilt[1],
                match=rebuilt == src_search,
            )
        )
        result.total_restore_seconds = round(sum(s.restore_seconds for s in result.stores), 3)
    finally:
        # Remove only this run's drill-namespaced resources.
        try:
            await cosmos.delete_database(require_drill_name(database))
        except Exception:  # noqa: S110 - already gone is fine
            pass
        for cname in (c_archive, c_quarantine, c_ckpt):
            try:
                await blob.delete_container(require_drill_name(cname))
            except Exception:  # noqa: S110
                pass
        for store in opened:
            await store.close()
        await cosmos.close()
        await blob.close()
        if owns_dir:
            shutil.rmtree(root, ignore_errors=True)
    return result


def result_to_dict(result: DrillResult) -> Doc:
    data = asdict(result)
    data["all_match"] = result.all_match
    return data
