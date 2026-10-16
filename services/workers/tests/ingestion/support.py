"""Builders shared by the ingestion tests (synthetic data only)."""

from __future__ import annotations

import copy
import functools
import json
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from neurosphere_core.payload import HubMessage, HubMessageKind
from neurosphere_workers.ingestion.fakes import (
    FakeArchiveSink,
    FakeLedgerSink,
    FakeMarkerStore,
    FakeQuarantineSink,
    FakeWatermarkStore,
)
from neurosphere_workers.ingestion.models import RawMessage
from neurosphere_workers.ingestion.pipeline import PipelineDeps
from neurosphere_workers.ingestion.settings import IngestionSettings

Doc = dict[str, Any]

# The PRP-03 sandbox generator lives at the repo root, which pytest only puts on sys.path when it
# collects the sandbox tests themselves. This module loads before any test module here.
_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.append(str(_REPO_ROOT))


@functools.cache
def sandbox_bundle() -> tuple[list[Doc], list[Doc]]:
    """(telemetry docs, cost docs) from the PRP-03 generator: tiny profile, no injected defects."""
    from sandbox.config import PROFILES, BadEventRates, GenerateConfig
    from sandbox.generate import generate

    rates = BadEventRates(duplicate=0.0, out_of_order=0.0, malformed=0.0, missing_optional=0.0)
    cfg = GenerateConfig(seed=7, profile=PROFILES["tiny"], cloud="commercial", rates=rates)
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        generate(cfg, out)

        def read(name: str) -> list[Doc]:
            lines = (out / name).read_text(encoding="utf-8").splitlines()
            return [json.loads(line) for line in lines if line]

        return read("telemetry.ndjson"), read("cost.ndjson")


def rich_telemetry() -> Doc:
    """The generated telemetry doc with the most optional fields present."""
    return copy.deepcopy(max(sandbox_bundle()[0], key=len))


def rich_cost() -> Doc:
    return copy.deepcopy(max(sandbox_bundle()[1], key=len))


T0 = datetime(2026, 10, 1, 12, 0, 0, tzinfo=UTC)
RECEIVED_AT = "2026-10-01T12:30:00.000Z"


def ts(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def telemetry_at(template: Doc, event_id: str, moment: datetime) -> Doc:
    doc = copy.deepcopy(template)
    doc["event_id"] = event_id
    doc["event_time"] = ts(moment)
    return doc


def hub_message(doc: Doc, kind: str = "telemetry", **overrides: Any) -> HubMessage:
    event_id = doc["event_id"] if kind == "telemetry" else doc["cost_id"]
    fields: Doc = {
        "kind": HubMessageKind(kind),
        "event_id": event_id,
        "cloud": doc["cloud"],
        "customer_id": doc["customer_id"],
        "source_id": doc["source_id"],
        "producer_id": "producer-1",
        "received_at": RECEIVED_AT,
        "request_id": doc.get("request_id"),
        "observation_kind": "gateway",
        "data": doc,
    }
    fields.update(overrides)
    return HubMessage(**fields)


def raw_from_bytes(body: bytes, offset: int, partition_id: str = "0") -> RawMessage:
    return RawMessage(
        body=body,
        partition_id=partition_id,
        offset=str(offset),
        sequence_number=offset,
        enqueued_time=T0 + timedelta(seconds=offset),
    )


def raw_event(doc: Doc, offset: int, kind: str = "telemetry", **overrides: Any) -> RawMessage:
    return raw_from_bytes(hub_message(doc, kind, **overrides).to_bytes(), offset)


def raw_json(obj: Any, offset: int) -> RawMessage:
    return raw_from_bytes(json.dumps(obj).encode(), offset)


async def no_sleep(_seconds: float) -> None:
    return None


@dataclass
class Harness:
    quarantine: FakeQuarantineSink = field(default_factory=FakeQuarantineSink)
    archive: FakeArchiveSink = field(default_factory=FakeArchiveSink)
    ledger: FakeLedgerSink = field(default_factory=FakeLedgerSink)
    markers: FakeMarkerStore = field(default_factory=FakeMarkerStore)
    watermarks: FakeWatermarkStore = field(default_factory=FakeWatermarkStore)
    cloud: str = "commercial"
    sleeps: list[float] = field(default_factory=list)

    def deps(self) -> PipelineDeps:
        async def record_sleep(seconds: float) -> None:
            self.sleeps.append(seconds)

        return PipelineDeps(
            quarantine=self.quarantine,
            archive=self.archive,
            ledger=self.ledger,
            markers=self.markers,
            watermarks=self.watermarks,
            cloud=self.cloud,
            sleep=record_sleep,
            rng=lambda: 0.5,
            clock=lambda: T0,
        )


def settings(**kwargs: Any) -> IngestionSettings:
    return IngestionSettings(**kwargs)
