"""Builders for the archive tests: an in-memory blob container and real normalized events.

Self-contained on purpose (the ingestion test helpers are not importable from here).
"""

from __future__ import annotations

import copy
import functools
import gzip
import json
import sys
import tempfile
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from azure.core.exceptions import HttpResponseError, ResourceExistsError
from neurosphere_core.payload import HubMessage, HubMessageKind
from neurosphere_workers.archive import BlobArchiveSink
from neurosphere_workers.archive.settings import LOCAL_DEV_PSEUDONYM_KEY
from neurosphere_workers.ingestion.fakes import (
    FakeArchiveSink,
    FakeLedgerSink,
    FakeMarkerStore,
    FakeQuarantineSink,
    FakeWatermarkStore,
)
from neurosphere_workers.ingestion.models import NormalizedEvent, RawMessage
from neurosphere_workers.ingestion.pipeline import PipelineDeps, process_batch
from neurosphere_workers.ingestion.settings import IngestionSettings

Doc = dict[str, Any]

T0 = datetime(2026, 10, 1, 12, 0, 0, tzinfo=UTC)
RECEIVED_AT = "2026-10-01T12:30:00.000Z"

_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.append(str(_REPO_ROOT))


@functools.cache
def sandbox_docs() -> list[Doc]:
    """Telemetry docs from the PRP-03 generator: tiny profile, no injected defects."""
    from sandbox.config import PROFILES, BadEventRates, GenerateConfig
    from sandbox.generate import generate

    rates = BadEventRates(duplicate=0.0, out_of_order=0.0, malformed=0.0, missing_optional=0.0)
    cfg = GenerateConfig(seed=7, profile=PROFILES["tiny"], cloud="commercial", rates=rates)
    with tempfile.TemporaryDirectory() as tmp:
        generate(cfg, Path(tmp))
        lines = (Path(tmp) / "telemetry.ndjson").read_text(encoding="utf-8").splitlines()
        return [json.loads(line) for line in lines if line]


def rich_telemetry() -> Doc:
    return copy.deepcopy(max(sandbox_docs(), key=len))


def ts(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def telemetry_at(template: Doc, event_id: str, moment: datetime) -> Doc:
    doc = copy.deepcopy(template)
    doc["event_id"] = event_id
    doc["event_time"] = ts(moment)
    return doc


def raw_event(doc: Doc, offset: int) -> RawMessage:
    message = HubMessage(
        kind=HubMessageKind.TELEMETRY,
        event_id=doc["event_id"],
        cloud=doc["cloud"],
        customer_id=doc["customer_id"],
        source_id=doc["source_id"],
        producer_id="producer-1",
        received_at=RECEIVED_AT,
        request_id=doc.get("request_id"),
        observation_kind="gateway",
        data=doc,
    )
    return RawMessage(
        body=message.to_bytes(),
        partition_id="0",
        offset=str(offset),
        sequence_number=offset,
        enqueued_time=T0 + timedelta(seconds=offset),
    )


def settings() -> IngestionSettings:
    return IngestionSettings()


def deps_for(archive: Any, cloud: str = "commercial") -> PipelineDeps:
    async def no_sleep(_seconds: float) -> None:
        return None

    return PipelineDeps(
        quarantine=FakeQuarantineSink(),
        archive=archive,
        ledger=FakeLedgerSink(),
        markers=FakeMarkerStore(),
        watermarks=FakeWatermarkStore(),
        cloud=cloud,
        sleep=no_sleep,
        rng=lambda: 0.5,
        clock=lambda: T0,
    )


@dataclass
class _Item:
    name: str
    metadata: dict[str, str] | None


@dataclass
class FakeContainer:
    """Implements ``BlobContainer`` with the SDK's observable semantics."""

    blobs: dict[str, bytes] = field(default_factory=dict)
    metas: dict[str, dict[str, str]] = field(default_factory=dict)
    upload_calls: int = 0
    fail_status: int | None = None

    async def upload_blob(
        self,
        name: str,
        data: bytes,
        *,
        overwrite: bool = False,
        metadata: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> None:
        self.upload_calls += 1
        if self.fail_status is not None:
            err = HttpResponseError("boom")
            err.status_code = self.fail_status
            raise err
        if name in self.blobs and not overwrite:
            raise ResourceExistsError("exists")
        self.blobs[name] = data
        self.metas[name] = dict(metadata or {})

    async def _iter(self, prefix: str | None) -> AsyncIterator[_Item]:
        for name in sorted(self.blobs):
            if prefix is None or name.startswith(prefix):
                yield _Item(name, self.metas.get(name))

    def list_blobs(
        self,
        name_starts_with: str | None = None,
        *,
        include: list[str] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[_Item]:
        return self._iter(name_starts_with)


def make_sink(
    container: FakeContainer,
    cloud: str = "commercial",
    clock: Callable[[], datetime] | None = None,
) -> BlobArchiveSink:
    if clock is None:
        return BlobArchiveSink(container, cloud=cloud, pseudonym_key=LOCAL_DEV_PSEUDONYM_KEY)
    return BlobArchiveSink(
        container, cloud=cloud, pseudonym_key=LOCAL_DEV_PSEUDONYM_KEY, clock=clock
    )


async def make_event(
    template: Doc,
    event_id: str,
    moment: datetime,
    cloud: str = "commercial",
    domain_id: str | None = "dom-a",
) -> NormalizedEvent:
    """Run a synthetic doc through the real normalizer and return the accepted event."""
    doc = telemetry_at(template, event_id, moment)
    doc["cloud"] = cloud
    doc["domain_id"] = domain_id
    capture = FakeArchiveSink()
    await process_batch([raw_event(doc, 0)], deps_for(capture, cloud), settings())
    (event,) = capture.effects.values()
    return event


def read_blob(data: bytes) -> dict[str, Any]:
    return json.loads(gzip.decompress(data))
