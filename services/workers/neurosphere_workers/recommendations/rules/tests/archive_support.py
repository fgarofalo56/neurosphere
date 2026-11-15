"""In-memory archive container (``BlobReadable``) and a sandbox-to-archive converter for tests."""

from __future__ import annotations

import gzip
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

SUFFIX = ".json.gz"


class FakeContainer:
    """Implements the slice of the aio ``ContainerClient`` the archive reader uses."""

    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}
        self.downloads: list[str] = []

    def put(self, name: str, doc: Any) -> None:
        self.blobs[name] = gzip.compress(json.dumps(doc).encode("utf-8"))

    def put_raw(self, name: str, raw: bytes) -> None:
        self.blobs[name] = raw

    async def list_blobs(
        self, name_starts_with: str | None = None, **_kw: Any
    ) -> AsyncIterator[Any]:
        for name in sorted(self.blobs):
            if name_starts_with is None or name.startswith(name_starts_with):
                yield SimpleNamespace(name=name)

    async def download_blob(self, blob: str, **_kw: Any) -> Any:
        self.downloads.append(blob)
        data = self.blobs[blob]

        async def readall() -> bytes:
            return data

        return SimpleNamespace(readall=readall)


def _day_segments(timestamp: str) -> str:
    stamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00")).astimezone(UTC)
    return f"{stamp:%Y/%m/%d}"


def archive_name(doc: dict[str, Any], doc_id: str) -> str:
    stamp = doc.get("event_time") or doc.get("usage_start") or doc["recorded_at"]
    domain = doc.get("domain_id") or "_none"
    return f"{doc['customer_id']}/{domain}/{_day_segments(str(stamp))}/{doc_id}{SUFFIX}"


def put_contract(container: FakeContainer, kind: str, doc: dict[str, Any], doc_id: str) -> str:
    name = archive_name(doc, doc_id)
    container.put(
        name, {"message": {"kind": kind, "customer_id": doc["customer_id"]}, "contract": doc}
    )
    return name


def archive_from_sandbox(directory: Path, container: FakeContainer) -> None:
    """Write every parseable sandbox telemetry and cost line as an archive blob."""
    for kind, filename in (("telemetry", "telemetry.ndjson"), ("cost", "cost.ndjson")):
        path = directory / filename
        if not path.exists():
            continue
        for index, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
            try:
                doc = json.loads(line)
            except ValueError:
                continue
            if not isinstance(doc, dict) or "customer_id" not in doc:
                continue
            put_contract(container, kind, doc, f"{kind}-{index:08d}")


def agent_docs(directory: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in (directory / "agents.ndjson").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def owner_map(directory: Path) -> dict[str, str]:
    owners: dict[str, tuple[int, str]] = {}
    for line in (directory / "relations.ndjson").read_text(encoding="utf-8").splitlines():
        doc = json.loads(line)
        if doc.get("relation_type") != "owned_by":
            continue
        rank = (0 if doc.get("status") == "asserted" else 1, doc["target_id"])
        if doc["source_id"] not in owners or rank < owners[doc["source_id"]]:
            owners[doc["source_id"]] = rank
    return {k: v[1] for k, v in owners.items()}
