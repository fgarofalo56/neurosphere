"""Per-store backup, restore and digest functions (PRP-21 item 5).

Stores and how each is protected:

* Cosmos documents: every document of each named container is exported to
  ``cosmos/<container>.jsonl`` (system ``_*`` fields stripped); restore upserts (never deletes).
* Blob archive and quarantine container: every blob (name, metadata, bytes) is exported to
  ``blobs/<label>.jsonl``; restore re-creates the container if missing and uploads with overwrite.
* Checkpoint store: the Event Hubs checkpoint blobs are an ordinary blob container, so they use
  the same blob export/restore; verification reads them back through ``BlobCheckpointStore``.
* Search index: no emulator exists. The index is derived from the catalog, so "restore" is a
  rebuild from the restored catalog documents into the in-process fixture index.

Digests are computed from live store contents, independent of the backup files, so a matching
digest proves the restored store equals the source at snapshot time.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from azure.cosmos import PartitionKey
from azure.cosmos.aio import CosmosClient
from azure.storage.blob.aio import BlobServiceClient

PARTITION_KEY_PATH = "/customer_id"
_CONCURRENCY = 16


@dataclass(frozen=True)
class Digest:
    count: int
    sha256: str
    size_bytes: int = 0


def _canonical(doc: dict[str, Any]) -> str:
    return json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def strip_system(doc: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in doc.items() if not k.startswith("_")}


def _digest_lines(lines: list[str]) -> Digest:
    h = hashlib.sha256()
    size = 0
    for line in sorted(lines):
        data = line.encode()
        size += len(data)
        h.update(data)
        h.update(b"\n")
    return Digest(count=len(lines), sha256=h.hexdigest(), size_bytes=size)


# -- Cosmos ------------------------------------------------------------------------------------


async def ensure_cosmos(client: CosmosClient, database: str, containers: list[str]) -> Any:
    db = await client.create_database_if_not_exists(id=database)
    for name in containers:
        await db.create_container_if_not_exists(
            id=name, partition_key=PartitionKey(path=PARTITION_KEY_PATH)
        )
    return db


async def read_cosmos_container(db: Any, container: str) -> list[dict[str, Any]]:
    docs: list[dict[str, Any]] = []
    async for item in db.get_container_client(container).query_items(query="SELECT * FROM c"):
        docs.append(strip_system(item))
    docs.sort(key=lambda d: str(d["id"]))
    return docs


async def upsert_docs(db: Any, container: str, docs: list[dict[str, Any]]) -> None:
    client = db.get_container_client(container)
    gate = asyncio.Semaphore(_CONCURRENCY)

    async def one(doc: dict[str, Any]) -> None:
        async with gate:
            await client.upsert_item(doc)

    await asyncio.gather(*(one(d) for d in docs))


async def cosmos_digest(db: Any, container: str) -> Digest:
    docs = await read_cosmos_container(db, container)
    return _digest_lines([_canonical(d) for d in docs])


async def backup_cosmos_container(db: Any, container: str, out_dir: Path) -> Digest:
    docs = await read_cosmos_container(db, container)
    target = out_dir / "cosmos"
    target.mkdir(parents=True, exist_ok=True)
    lines = [_canonical(d) for d in docs]
    (target / f"{container}.jsonl").write_text("".join(f"{x}\n" for x in lines), encoding="utf-8")
    return _digest_lines(lines)


async def restore_cosmos_container(db: Any, container: str, backup_dir: Path) -> int:
    path = backup_dir / "cosmos" / f"{container}.jsonl"
    docs = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x]
    await upsert_docs(db, container, docs)
    return len(docs)


# -- Blob containers (archive, quarantine, checkpoints) ----------------------------------------


async def read_blobs(service: BlobServiceClient, container: str) -> list[dict[str, Any]]:
    client = service.get_container_client(container)
    out: list[dict[str, Any]] = []
    async for item in client.list_blobs(include=["metadata"]):
        stream = await client.download_blob(item.name)
        data = await stream.readall()
        out.append(
            {
                "name": item.name,
                "metadata": dict(item.metadata or {}),
                "sha256": hashlib.sha256(data).hexdigest(),
                "bytes": len(data),
                "content_b64": base64.b64encode(data).decode(),
            }
        )
    out.sort(key=lambda b: str(b["name"]))
    return out


def _blob_lines(blobs: list[dict[str, Any]]) -> list[str]:
    return [
        _canonical({"name": b["name"], "metadata": b["metadata"], "sha256": b["sha256"]})
        for b in blobs
    ]


async def blob_digest(service: BlobServiceClient, container: str) -> Digest:
    blobs = await read_blobs(service, container)
    base = _digest_lines(_blob_lines(blobs))
    return Digest(base.count, base.sha256, sum(int(b["bytes"]) for b in blobs))


async def backup_blob_container(
    service: BlobServiceClient, container: str, label: str, out_dir: Path
) -> Digest:
    blobs = await read_blobs(service, container)
    target = out_dir / "blobs"
    target.mkdir(parents=True, exist_ok=True)
    (target / f"{label}.jsonl").write_text(
        "".join(f"{_canonical(b)}\n" for b in blobs), encoding="utf-8"
    )
    base = _digest_lines(_blob_lines(blobs))
    return Digest(base.count, base.sha256, sum(int(b["bytes"]) for b in blobs))


async def restore_blob_container(
    service: BlobServiceClient, container: str, label: str, backup_dir: Path
) -> int:
    client = service.get_container_client(container)
    if not await client.exists():
        await client.create_container()
    path = backup_dir / "blobs" / f"{label}.jsonl"
    blobs = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x]
    for blob in blobs:
        data = base64.b64decode(blob["content_b64"])
        if hashlib.sha256(data).hexdigest() != blob["sha256"]:
            raise ValueError(f"backup corrupt: hash mismatch for {blob['name']!r}")
        await client.upload_blob(
            blob["name"], data, overwrite=True, metadata=dict(blob["metadata"])
        )
    return len(blobs)
