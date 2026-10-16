"""Shared harness for the ingestion integration suite (compose emulators, everything in-process).

The api edge runs through ``create_app`` + ``configure_ingest_from_settings`` behind an httpx ASGI
transport; the normalizer runs as a real ``IngestionConsumer`` driven for a bounded time. Every
run uses unique names (customer, Cosmos database, blob containers, checkpoint container) so runs
never see each other's state. Secrets are generated here; only sha256 hashes reach disk.
"""

from __future__ import annotations

import asyncio
import gzip
import importlib.util
import json
import secrets
import sys
import time
import uuid
from collections import Counter
from collections.abc import AsyncIterator, Callable, Iterable
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx
import pytest
from azure.eventhub import EventData
from azure.storage.blob.aio import ContainerClient
from neurosphere_api.app import create_app
from neurosphere_api.ingest import IngestSettings, hash_secret
from neurosphere_api.ingest.bootstrap import configure_ingest_from_settings
from neurosphere_core.clients import (
    ClientLifetime,
    create_checkpoint_store,
    create_cosmos_client,
    create_eventhub_consumer,
    create_eventhub_producer,
)
from neurosphere_core.cloud import Settings
from neurosphere_core.payload import (
    CLOUDEVENT_TYPE_COST,
    CLOUDEVENT_TYPE_TELEMETRY,
    REQUEST_ID_EXTENSION,
    is_body_field,
)
from neurosphere_workers.archive.settings import ArchiveSettings
from neurosphere_workers.ingestion.consumer import IngestionConsumer
from neurosphere_workers.ingestion.models import BatchResult, parse_timestamp
from neurosphere_workers.ingestion.pipeline import PipelineDeps
from neurosphere_workers.ingestion.settings import IngestionSettings
from neurosphere_workers.ingestion.wiring import LedgerSettings, build_pipeline_deps
from neurosphere_workers.quarantine import (
    BlobQuarantineReader,
    QuarantineSettings,
    create_quarantine_container,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
HUB = "telemetry"
GROUP = "normalizer"

# Documented placeholder for the Event Hubs emulator (same literal as the PRP-05 roundtrip test;
# the emulator does not validate it). Azurite is addressed with the SDK's development shorthand,
# so no storage key appears in this repository.
EVENTHUBS_CONNECTION = (
    "Endpoint=sb://localhost;SharedAccessKeyName=RootManageSharedAccessKey;"
    "SharedAccessKey=SAS_KEY_VALUE;UseDevelopmentEmulator=true;"
)
AZURITE_CONNECTION = "UseDevelopmentStorage=true;"

Doc = dict[str, Any]


def azurite_connection_string() -> str:
    """The full emulator connection string, assembled at runtime.

    The vendored blob client inside the Event Hubs checkpoint store does not understand the
    ``UseDevelopmentStorage`` shorthand, so the factories need an explicit string. The Azurite
    development account name and key come from the installed azure-storage-blob SDK (which
    resolves the shorthand itself), so no key literal exists in this repository. The value stays
    in process memory: it is never written to disk or printed.
    """
    probe = ContainerClient.from_connection_string(AZURITE_CONNECTION, "probe")
    credential = probe.credential
    name, key = credential.account_name, credential.account_key  # type: ignore[union-attr]
    endpoint = probe.primary_endpoint.rsplit("/", 1)[0]
    return (
        "DefaultEndpointsProtocol=http;"
        + f"AccountName={name};"
        + (f"AccountKey={key};BlobEndpoint={endpoint};")
    )


def emulator_env() -> dict[str, str]:
    import base64

    return {
        "NS_ENV": "local",
        "NS_COSMOS_ENDPOINT": "http://localhost:8081",
        "NS_COSMOS_KEY": base64.b64encode(b"emulator-ignores-this").decode(),
        "NS_EVENTHUBS_CONNECTION_STRING": EVENTHUBS_CONNECTION,
        "NS_BLOB_CONNECTION_STRING": azurite_connection_string(),
    }


# -- producers and the edge --------------------------------------------------------------------


@dataclass
class Producer:
    producer_id: str
    customer_id: str
    cloud: str
    sources: dict[str, str]
    secret: str = field(default_factory=lambda: secrets.token_urlsafe(24))  # generated per run

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.producer_id}.{self.secret}"}

    def registration(self) -> Doc:
        return {
            "producer_id": self.producer_id,
            "secret_sha256": hash_secret(self.secret),  # hash only
            "customer_id": self.customer_id,
            "cloud": self.cloud,
            "sources": self.sources,
        }


def write_producers_file(directory: Path, producers: Iterable[Producer]) -> Path:
    path = directory / f"producers-{uuid.uuid4().hex[:6]}.json"
    path.write_text(json.dumps({"producers": [p.registration() for p in producers]}), "utf-8")
    return path


@asynccontextmanager
async def edge_client(
    settings: Settings, producers: list[Producer], directory: Path, *, via_main: bool = False
) -> AsyncIterator[httpx.AsyncClient]:
    """The real ``create_app`` + bootstrap, served through an in-process ASGI transport.

    ``via_main=True`` builds the app with the production factory ``neurosphere_api.main.create``
    driven purely by ``NS_INGEST_*`` environment variables (the opt-in path).
    """
    producers_file = write_producers_file(directory, producers)
    if via_main:
        from neurosphere_api.main import create

        patch = pytest.MonkeyPatch()
        patch.setenv("NS_INGEST_PRODUCERS_FILE", str(producers_file))
        patch.setenv("NS_INGEST_RATE_LIMIT_RPS", "100000")
        patch.setenv("NS_INGEST_RATE_LIMIT_BURST", "100000")
        try:
            app = create()
        finally:
            patch.undo()
        assert app.state.ingest_service is not None
    else:
        app = create_app(settings)
        configured = configure_ingest_from_settings(
            app,
            settings,
            IngestSettings(
                producers_file=producers_file, rate_limit_rps=100_000, rate_limit_burst=100_000
            ),
        )
        assert configured is True
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://edge.invalid"
        ) as client:
            yield client
    finally:
        await app.state.ingest_lifetime.aclose()


@dataclass
class PushResult:
    sent: int = 0
    accepted: int = 0
    rejected_indexes: list[int] = field(default_factory=list)  # global index into the input
    dropped_fields: Counter[str] = field(default_factory=Counter)
    statuses: Counter[int] = field(default_factory=Counter)

    @property
    def accepted_indexes(self) -> list[int]:
        rejected = set(self.rejected_indexes)
        return [i for i in range(self.sent) if i not in rejected]


def cloudevent(kind: str, data: Doc, *, request_id: str | None = None) -> Doc:
    event: Doc = {
        "specversion": "1.0",
        "id": str(data.get("event_id") or data.get("cost_id") or uuid.uuid4().hex),
        "source": "urn:neurosphere:integration-test",
        "type": CLOUDEVENT_TYPE_TELEMETRY if kind == "telemetry" else CLOUDEVENT_TYPE_COST,
        "data": data,
    }
    if request_id is not None:
        event[REQUEST_ID_EXTENSION] = request_id
    return event


async def post_retrying(
    client: httpx.AsyncClient,
    path: str,
    headers: dict[str, str],
    content: bytes,
    statuses: Counter[int],
    *,
    attempts: int = 4,
) -> httpx.Response:
    """POST, retrying the edge's documented retryable 503 (a dropped emulator AMQP link).

    Ingest is idempotent end to end (deterministic ids, dedupe), so a retry is safe.
    """
    for attempt in range(attempts):
        response = await client.post(path, headers=headers, content=content)
        statuses[response.status_code] += 1
        if response.status_code != 503 or attempt == attempts - 1:
            return response
        await asyncio.sleep(1.0 + attempt)
    raise AssertionError("unreachable")


async def push_cloudevents(
    client: httpx.AsyncClient, producer: Producer, events: list[Doc], *, batch: int = 25
) -> PushResult:
    result = PushResult()
    for start in range(0, len(events), batch):
        chunk = events[start : start + batch]
        response = await post_retrying(
            client,
            "/v1/ingest/events",
            {**producer.headers, "content-type": "application/cloudevents-batch+json"},
            json.dumps(chunk).encode(),
            result.statuses,
        )
        assert response.status_code == 202, response.text
        body = response.json()
        result.sent += len(chunk)
        result.accepted += body["accepted"]
        result.rejected_indexes += [start + r["index"] for r in body["rejected"]]
        result.dropped_fields.update(body["dropped_fields"])
    return result


async def push_otlp_traces(client: httpx.AsyncClient, producer: Producer, doc: Doc) -> Doc:
    response = await post_retrying(
        client,
        "/v1/ingest/otlp/traces",
        {**producer.headers, "content-type": "application/json"},
        json.dumps(doc).encode(),
        Counter(),
    )
    assert response.status_code == 202, response.text
    return response.json()


def otlp_attr(key: str, value: Any) -> Doc:
    if isinstance(value, int):
        return {"key": key, "value": {"intValue": str(value)}}
    return {"key": key, "value": {"stringValue": value}}


def otlp_model_call_spans(count: int, *, request_prefix: str, canary: str) -> tuple[Doc, list[Doc]]:
    """An OTLP/JSON trace document of ``count`` model_call spans, each carrying a prompt canary."""
    trace = uuid.uuid4().hex
    base_ns = int(time.time() * 1e9)
    spans: list[Doc] = []
    for i in range(count):
        spans.append(
            {
                "traceId": trace,
                "spanId": f"{i + 1:016x}",
                "parentSpanId": "",
                "name": "chat synthetic",
                "status": {"code": 1},
                "startTimeUnixNano": str(base_ns + i * 1_000_000),
                "endTimeUnixNano": str(base_ns + i * 1_000_000 + 250_000_000),
                "attributes": [
                    otlp_attr("gen_ai.operation.name", "chat"),
                    otlp_attr("gen_ai.system", "azure_openai"),
                    otlp_attr("gen_ai.request.model", "synthetic-model"),
                    otlp_attr("gen_ai.usage.input_tokens", 100 + i),
                    otlp_attr("gen_ai.usage.output_tokens", 20),
                    otlp_attr("request_id", f"{request_prefix}-{i}"),
                    otlp_attr("gen_ai.prompt", canary),
                    otlp_attr("gen_ai.completion", canary),
                ],
            }
        )
    doc = {
        "resourceSpans": [
            {
                "resource": {"attributes": []},
                "scopeSpans": [{"scope": {"name": "it"}, "spans": spans}],
            }
        ]
    }
    return doc, spans


# -- direct hub publishing (a holder of hub credentials bypassing the edge) --------------------


async def publish_raw(messages: list[tuple[bytes, str]]) -> None:
    """Publish ``(body, partition_key)`` pairs straight to the hub."""
    async with ClientLifetime() as lifetime:
        producer = create_eventhub_producer(
            Settings(env="local"), lifetime=lifetime, eventhub_name=HUB
        )
        for body, key in messages:
            batch = await producer.create_batch(partition_key=key)
            batch.add(EventData(body))
            await producer.send_batch(batch)


async def read_hub(
    match: Callable[[bytes], bool], *, quiet_seconds: float = 6.0, max_seconds: float = 120.0
) -> list[bytes]:
    """Every hub message (consumer group ``$default``, from the beginning) accepted by ``match``."""
    found: list[bytes] = []
    last_event = time.monotonic()

    async with ClientLifetime() as lifetime:
        client = create_eventhub_consumer(
            Settings(env="local"), lifetime=lifetime, eventhub_name=HUB, consumer_group="$default"
        )

        async def on_event(_ctx: Any, event: Any) -> None:
            nonlocal last_event
            if event is None:
                return
            body = b"".join(event.body)
            last_event = time.monotonic()
            if match(body):
                found.append(body)

        task = asyncio.create_task(client.receive(on_event=on_event, starting_position="-1"))
        started = time.monotonic()
        try:
            while time.monotonic() - started < max_seconds:
                await asyncio.sleep(1.0)
                if found and time.monotonic() - last_event >= quiet_seconds:
                    break
        finally:
            await client.close()
            with suppress(asyncio.CancelledError, Exception):
                await asyncio.wait_for(task, timeout=30)
    return found


# -- the normalizer under test -----------------------------------------------------------------


class CountingConsumer(IngestionConsumer):
    """The real consumer, additionally tallying every ``BatchResult`` it produced."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.accepted = 0
        self.duplicates = 0
        self.late = 0
        self.quarantined: Counter[str] = Counter()

    @property
    def processed(self) -> int:
        return self.accepted + self.duplicates + sum(self.quarantined.values())

    async def on_event_batch(self, partition_context: Any, events: Any) -> BatchResult | None:
        result = await super().on_event_batch(partition_context, events)
        if result is not None:
            self.accepted += result.accepted
            self.duplicates += result.duplicates
            self.late += result.late
            for reason, count in result.quarantined.items():
                self.quarantined[reason.value] += count
        return result


@dataclass
class Pipeline:
    """Stores, sinks and a consumer driver for one run. All names are unique per run."""

    settings: Settings
    run: str
    lifetime: ClientLifetime
    ingestion: IngestionSettings
    ledger: LedgerSettings
    archive: ArchiveSettings
    quarantine: QuarantineSettings
    deps: PipelineDeps
    database: Any
    cosmos: Any
    archive_container: ContainerClient
    quarantine_container: ContainerClient

    @staticmethod
    def names(run: str) -> dict[str, str]:
        return {
            "NS_INGESTION_COSMOS_DATABASE": f"it_{run}",
            "NS_INGESTION_CHECKPOINT_CONTAINER": f"ns-ckpt-{run}",
            "NS_ARCHIVE_CONTAINER": f"ns-arch-{run}",
            "NS_QUARANTINE_CONTAINER": f"ns-quar-{run}",
        }

    @classmethod
    @asynccontextmanager
    async def open(cls, settings: Settings, run: str | None = None) -> AsyncIterator[Pipeline]:
        run = run or uuid.uuid4().hex[:8]
        lifetime = ClientLifetime()
        ingestion = IngestionSettings(
            cosmos_database=f"it_{run}",
            checkpoint_container=f"ns-ckpt-{run}",
            max_wait_seconds=1.0,
            backoff_base_seconds=0.05,
            backoff_max_seconds=0.5,
        )
        archive = ArchiveSettings(container=f"ns-arch-{run}")
        quarantine = QuarantineSettings(container=f"ns-quar-{run}")
        ledger = LedgerSettings()
        pipe: Pipeline | None = None
        try:
            deps = await build_pipeline_deps(
                settings,
                lifetime=lifetime,
                ingestion=ingestion,
                ledger=ledger,
                archive=archive,
                quarantine=quarantine,
            )
            cosmos = create_cosmos_client(settings, lifetime=lifetime)
            archive_container = lifetime.register(
                ContainerClient.from_connection_string(AZURITE_CONNECTION, archive.container)
            )
            pipe = cls(
                settings=settings,
                run=run,
                lifetime=lifetime,
                ingestion=ingestion,
                ledger=ledger,
                archive=archive,
                quarantine=quarantine,
                deps=deps,
                database=cosmos.get_database_client(ingestion.cosmos_database),
                cosmos=cosmos,
                archive_container=archive_container,
                quarantine_container=create_quarantine_container(
                    settings, lifetime=lifetime, quarantine=quarantine
                ),
            )
            yield pipe
        finally:
            with suppress(Exception):
                if pipe is not None:
                    await pipe.cosmos.delete_database(ingestion.cosmos_database)
                    for container in (pipe.archive_container, pipe.quarantine_container):
                        await container.delete_container()
            with suppress(Exception):
                async with ContainerClient.from_connection_string(
                    AZURITE_CONNECTION, ingestion.checkpoint_container
                ) as ckpt:
                    await ckpt.delete_container()
            await lifetime.aclose()

    # -- driving the consumer ------------------------------------------------------------------
    async def consume(
        self, *, expect_processed: int, max_seconds: float = 240.0
    ) -> CountingConsumer:
        """Run the real consumer until it has handled ``expect_processed`` messages (bounded)."""
        store = create_checkpoint_store(
            self.settings, lifetime=self.lifetime, container=self.ingestion.checkpoint_container
        )
        client = create_eventhub_consumer(
            self.settings,
            lifetime=self.lifetime,
            eventhub_name=self.ingestion.eventhub_name,
            consumer_group=self.ingestion.consumer_group,
            checkpoint_store=store,
        )
        consumer = CountingConsumer(client, self.deps, self.ingestion)
        task = asyncio.create_task(consumer.run(handle_signals=False))
        deadline = time.monotonic() + max_seconds
        try:
            while consumer.processed < expect_processed:
                if task.done():
                    task.result()
                    raise AssertionError("consumer stopped before the expected messages")
                if time.monotonic() > deadline:
                    raise AssertionError(
                        f"consumer timed out: processed {consumer.processed}/{expect_processed} "
                        f"(accepted={consumer.accepted} dup={consumer.duplicates} "
                        f"quarantined={dict(consumer.quarantined)})"
                    )
                await asyncio.sleep(0.5)
            await asyncio.sleep(1.0)  # let the last batch checkpoint
        finally:
            consumer.request_shutdown()
            exit_code = await asyncio.wait_for(task, timeout=90)
        assert exit_code == 0
        return consumer

    # -- reading what was written ----------------------------------------------------------------
    async def cosmos_docs(self, container: str, customer_id: str | None = None) -> list[Doc]:
        proxy = self.database.get_container_client(container)
        query = "SELECT * FROM c"
        params: list[Doc] = []
        kwargs: Doc = {}
        if customer_id is not None:
            query += " WHERE c.customer_id = @c"
            params = [{"name": "@c", "value": customer_id}]
            kwargs = {"partition_key": customer_id}
        return [d async for d in proxy.query_items(query=query, parameters=params, **kwargs)]

    async def all_cosmos_docs(self) -> dict[str, list[Doc]]:
        names = [
            self.ingestion.markers_container,
            self.ingestion.watermarks_container,
            self.ledger.ledger_container,
            self.ledger.outbox_container,
            self.ledger.checkpoint_container,
        ]
        return {name: await self.cosmos_docs(name) for name in names}

    async def blobs(
        self, container: ContainerClient, prefix: str | None = None
    ) -> dict[str, bytes]:
        out: dict[str, bytes] = {}
        async for item in container.list_blobs(name_starts_with=prefix):
            stream = await container.download_blob(item.name)
            out[item.name] = await stream.readall()
        return out

    async def archive_records(self, customer_id: str) -> dict[str, Doc]:
        raw = await self.blobs(self.archive_container, f"{customer_id}/")
        return {
            name: json.loads(gzip.decompress(data))
            for name, data in raw.items()
            if name.endswith(".json.gz")
        }

    async def quarantine_records(self) -> list[Doc]:
        reader = BlobQuarantineReader(self.quarantine_container)  # type: ignore[arg-type]
        out: list[Doc] = []
        for doc_id in await reader.list_doc_ids():
            record = await reader.get(doc_id)
            assert record is not None
            out.append(json.loads(record.model_dump_json()))
        return out


# -- no-body scan ------------------------------------------------------------------------------


def body_key_paths(value: Any, path: str = "") -> list[str]:
    """Paths of every prompt/response-style key anywhere in a JSON-like value."""
    found: list[str] = []
    stack: list[tuple[Any, str]] = [(value, path)]
    while stack:
        node, here = stack.pop()
        if isinstance(node, dict):
            for key, child in node.items():
                child_path = f"{here}/{key}"
                if isinstance(key, str) and is_body_field(key):
                    found.append(child_path)
                stack.append((child, child_path))
            if "key" in node and "value" in node and isinstance(node["key"], str):
                if is_body_field(node["key"]):
                    found.append(f"{here}[{node['key']}]")
        elif isinstance(node, list):
            stack.extend((child, f"{here}[{i}]") for i, child in enumerate(node))
    return found


def assert_no_bodies(
    label: str, documents: Iterable[Any], raw: Iterable[bytes], canary: str
) -> int:
    """No prompt/response key in any parsed document and no canary text in any raw bytes.

    Returns how many items were scanned so a caller can assert the scan was not vacuous.
    """
    scanned = 0
    for doc in documents:
        scanned += 1
        assert not body_key_paths(doc), f"{label}: body-style key present"
        assert canary not in json.dumps(doc), f"{label}: canary text present"
    for blob in raw:
        scanned += 1
        assert canary.encode() not in blob, f"{label}: canary bytes present"
    return scanned


# -- oracle ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Arrival:
    """One message as it reaches the hub, in send order."""

    source_id: str
    event_id: str
    event_time: datetime


def expected_outcome(
    arrivals: Iterable[Arrival], *, lateness_seconds: float = 300.0
) -> tuple[int, int, int]:
    """(accepted, duplicates, late) by the C6/C7 rules, independent of the pipeline code.

    Per source: a repeated event_id is a duplicate; otherwise the event is late when its time is
    more than ``lateness_seconds`` older than the newest event time accepted so far.
    """
    seen: dict[str, set[str]] = {}
    newest: dict[str, datetime] = {}
    accepted = duplicates = late = 0
    for item in arrivals:
        ids = seen.setdefault(item.source_id, set())
        if item.event_id in ids:
            duplicates += 1
            continue
        ids.add(item.event_id)
        top = newest.get(item.source_id)
        if top is not None and (top - item.event_time).total_seconds() > lateness_seconds:
            late += 1
        if top is None or item.event_time > top:
            newest[item.source_id] = item.event_time
        accepted += 1
    return accepted, duplicates, late


def telemetry_time(doc: Doc) -> datetime:
    return parse_timestamp(doc["event_time"])


def cost_time(doc: Doc) -> datetime:
    return parse_timestamp(doc.get("usage_end") or doc.get("usage_start") or doc["recorded_at"])


def load_replay_cli() -> ModuleType:
    """Import ``scripts/replay/replay.py`` (a script, not a package)."""
    path = REPO_ROOT / "scripts" / "replay" / "replay.py"
    spec = importlib.util.spec_from_file_location("replay_cli_it", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["replay_cli_it"] = module
    spec.loader.exec_module(module)
    return module


def now_utc_z() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def unique_customer(prefix: str = "it") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"
