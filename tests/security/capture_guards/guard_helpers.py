"""Shared rig for the PRP-103 item 6 guard negative suite (synthetic data only).

One scenario drives a real ``IngestService`` with the real ``EdgeCapture`` adapter, matcher,
capture pipeline, in-memory interaction store (``LocalFileKeyWrapper`` under ``tmp_path``) and
the real audit repository (its seal runs the metadata-only content guard). It is run twice:
capture ON (an approved active policy for the source and domain) and capture OFF (the same
adapter attached, the stored setting off).

Every canary and credential-shaped value is assembled at runtime from fragments and fresh
randomness: gitleaks and ``.githooks`` fingerprint literals. Helpers are copied from
``services/api/tests/interaction_capture_edge/edge_helpers.py`` and
``services/workers/tests/{ingestion,quarantine}/support.py`` rather than imported (separate
test packages shadow each other in one pytest session).
"""

from __future__ import annotations

import base64
import functools
import hashlib
import json
import secrets
import string
from collections.abc import AsyncIterator, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final

import pytest
from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError
from jsonschema import Draft202012Validator
from neurosphere_api.ingest import (
    IngestSettings,
    InMemoryPublisher,
    ProducerRegistration,
    StaticProducerRegistry,
    hash_secret,
)
from neurosphere_api.ingest.auth import RegisteredCredentialAuthenticator
from neurosphere_api.ingest.capture import EdgeCapture, domain_audit_writer
from neurosphere_api.ingest.limits import TokenBucketLimiter
from neurosphere_api.ingest.service import IngestService
from neurosphere_contracts.audit.v1.audit_record import AuditRecord
from neurosphere_core.audit import AuditDraft, AuditRepository, InMemoryAuditStore
from neurosphere_core.audit.chains import domain_audit_chain_id
from neurosphere_core.audit.content_guard import assert_metadata_only
from neurosphere_core.classification import DEFAULT_SET_VERSION
from neurosphere_core.crypto import KeyWrapper, LocalFileKeyWrapper, WrappedKey
from neurosphere_core.interactions import (
    CaptureMatcher,
    CapturePipeline,
    InMemoryCapturePolicyStore,
    InMemoryInteractionStore,
    parse_capture_policy,
)
from neurosphere_core.lifecycle.policy import PolicyState, load_policy
from neurosphere_core.payload import HubMessage
from neurosphere_workers.ingestion.fakes import (
    FakeArchiveSink,
    FakeLedgerSink,
    FakeMarkerStore,
    FakeQuarantineSink,
    FakeWatermarkStore,
)
from neurosphere_workers.ingestion.models import BatchResult, RawMessage
from neurosphere_workers.ingestion.pipeline import PipelineDeps, process_batch
from neurosphere_workers.ingestion.settings import IngestionSettings
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

REPO_ROOT: Final = Path(__file__).resolve().parents[3]
SCHEMA_ROOT: Final = REPO_ROOT / "packages" / "contracts" / "schemas"
TELEMETRY_SCHEMA_ID: Final = (
    "https://neurosphere.invalid/schemas/telemetry/v1/telemetry-event.schema.json"
)

CUSTOMER: Final = "cust-guards"
SOURCE: Final = "src-guards"
PRODUCER: Final = "prod-guards"
DOMAIN: Final = f"commercial:{CUSTOMER}:neurosphere:domain:support"
CHAIN: Final = domain_audit_chain_id(CUSTOMER, DOMAIN)
TRACE: Final = "0af7651916cd43dd8448eb211c80319c"
KEK_URI: Final = "https://guards-kv.vault.azure.net/keys/ns-content-kek"
POLICY_ID: Final = "guards-capture"
POLICY_VERSION: Final = 2
FIXED_NOW: Final = datetime(2026, 11, 25, 12, 0, tzinfo=UTC)
STRUCTURED: Final = "application/cloudevents+json"
BATCH: Final = "application/cloudevents-batch+json"
TELEMETRY_TYPE: Final = "com.neurosphere.telemetry.v1"
CORRELATION: Final = "req-5b1e7c03-guards"
CAPTURED_EVENT: Final = "evt-guard-captured"
WRAP_FAILED_EVENT: Final = "evt-guard-wrapfail"
CAPTURE_MODES: Final = ("capture_on", "capture_off")

_ALNUM: Final = string.ascii_letters + string.digits


# --- generated values -----------------------------------------------------------------------------


@dataclass
class Issued:
    """Every canary and credential-shaped value one scenario generated (the leak checks)."""

    values: list[str] = field(default_factory=list)
    credentials: list[str] = field(default_factory=list)

    def canary(self) -> str:
        letters = "".join(secrets.choice(string.ascii_lowercase) for _ in range(16))
        return self._keep("NSCANARY-" + letters)

    def credential(self) -> str:
        """A GitHub-token-shaped value (the PRP-101 detectors redact it), built from fragments."""
        body = list("".join(secrets.choice(_ALNUM) for _ in range(36)))
        body[0], body[1], body[2] = "Q", "q", "7"
        value = self._keep("gh" + "p_" + "".join(body))
        self.credentials.append(value)
        return value

    def _keep(self, value: str) -> str:
        self.values.append(value)
        return value

    def probes(self) -> list[str]:
        """Every value plus a prefix of each credential (criterion 3: no hash or prefix).

        The prefix is the first ``CREDENTIAL_PREFIX_CHARS`` characters: the fixed 7-character
        token head plus 5 random alphanumerics (62**5, about 9e8 combinations). Ids, hashes and
        timestamps in the outputs never contain an underscore followed by this mixed-case run,
        so a hit cannot be a chance collision; shorter prefixes would match the fixed head alone.
        """
        return [*self.values, *(value[:CREDENTIAL_PREFIX_CHARS] for value in self.credentials)]


CREDENTIAL_PREFIX_CHARS: Final = 12


def _encoded_forms(value: str) -> list[str]:
    """The value, its sha256 hex, and its standard and URL-safe base64 (padded and not)."""
    raw = value.encode()
    forms = [value, hashlib.sha256(raw).hexdigest()]
    for encoded in (base64.b64encode(raw), base64.urlsafe_b64encode(raw)):
        text = encoded.decode("ascii")
        forms.extend([text, text.rstrip("=")])
    return forms


def leaked(text: str, values: Iterable[str]) -> list[str]:
    """The generated values that appear in ``text`` as-is, hashed or base64-encoded."""
    found: list[str] = []
    for value in values:
        if any(form in text for form in _encoded_forms(value)):
            found.append(value)
    return found


def assert_no_leak(text: str, values: Iterable[str], where: str) -> None:
    hits = leaked(text, values)
    # The count only: a failing run should not echo the generated values either.
    assert hits == [], f"{len(hits)} generated value(s) reached {where}"


# --- edge rig -------------------------------------------------------------------------------------


def retention(*, opt_in: bool = True) -> PolicyState:
    return load_policy(
        {
            "policy_version": "v1",
            "rules": [
                {
                    "data_class": "telemetry_event",
                    "min_retention_days": 0,
                    "max_retention_days": 30,
                },
                {
                    "data_class": "interaction_content",
                    "min_retention_days": 0,
                    "max_retention_days": 90,
                },
            ],
            "retain_prompt_response_bodies": opt_in,
        }
    )


def policy_doc() -> dict[str, Any]:
    return {
        "schema_version": "1.2.0",
        "capture_policy_id": POLICY_ID,
        "version": POLICY_VERSION,
        "previous_version": POLICY_VERSION - 1,
        "display_name": "Guard suite capture",
        "cloud": "commercial",
        "customer_id": CUSTOMER,
        "domain_id": DOMAIN,
        "source_ids": [SOURCE],
        "parts": ["prompt", "response"],
        "detector_set_version": DEFAULT_SET_VERSION,
        "customer_dictionary_ids": [],
        "redaction_mode": "redact_all_detections",
        "kept_categories": [],
        "sampling": {"rate": 1.0, "max_per_minute": 600},
        "max_part_chars": 8192,
        "retention_class": "interaction_default",
        "retention_days": 30,
        "state": "active",
        "approved_intent_id": "4f2a9c61-0d3e-4b57-8a19-6e7c2b1d0f34",
        "approved_audit_id": "b81c3e02-5a6f-4d97-9e2b-03f4a7c6d518",
        "effective_from": "2026-11-21T08:00:00Z",
    }


class ToggleWrapper:
    """A real local key wrapper that can be told to fail (the injected key-wrap failure)."""

    def __init__(self, inner: KeyWrapper) -> None:
        self._inner = inner
        self.fail = False

    @property
    def key_id(self) -> str:
        return self._inner.key_id

    async def wrap(self, data_key: bytes) -> WrappedKey:
        if self.fail:
            raise RuntimeError("injected key wrap failure")
        return await self._inner.wrap(data_key)

    async def unwrap(self, wrapped: WrappedKey) -> bytes:
        return await self._inner.unwrap(wrapped)


class RecordingAudit(AuditRepository):
    """The real repository (seal runs the content guard) that also keeps every draft."""

    def __init__(self) -> None:
        super().__init__(InMemoryAuditStore(), clock=lambda: FIXED_NOW)
        self.drafts: list[tuple[str, AuditDraft]] = []

    async def append(self, chain_id: str, draft: AuditDraft) -> Any:
        self.drafts.append((chain_id, draft))
        return await super().append(chain_id, draft)


def producer() -> ProducerRegistration:
    return ProducerRegistration(
        producer_id=PRODUCER,
        secret_sha256=hash_secret(secrets.token_urlsafe(24)),
        customer_id=CUSTOMER,
        cloud="commercial",
        sources={SOURCE: "application"},
    )


def ingest_service(
    publisher: InMemoryPublisher, registration: ProducerRegistration
) -> IngestService:
    return IngestService(
        settings=IngestSettings(),
        edge_cloud="commercial",
        authenticator=RegisteredCredentialAuthenticator(StaticProducerRegistry([registration])),
        publisher=publisher,
        limiter=TokenBucketLimiter(1000.0, 1000),
        now=lambda: FIXED_NOW,
    )


async def edge_capture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, capture_on: bool
) -> tuple[EdgeCapture, InMemoryInteractionStore, RecordingAudit, ToggleWrapper]:
    """An approved active policy is stored either way; OFF is the stored setting switched off."""
    monkeypatch.setenv("NS_ENV", "local")
    wrapper = ToggleWrapper(LocalFileKeyWrapper(tmp_path / "guards-kek.bin"))
    store = InMemoryInteractionStore(wrapper, kek_uri=KEK_URI, policy=retention())
    policy_store = InMemoryCapturePolicyStore()
    await policy_store.create(parse_capture_policy(policy_doc()))
    matcher = await CaptureMatcher.from_store(
        policy_store, setting_enabled=capture_on, retention=retention()
    )
    audit = RecordingAudit()
    capture = EdgeCapture(
        matcher, CapturePipeline(store), domain_audit_writer(audit, cloud="commercial")
    )
    return capture, store, audit, wrapper


def telemetry_data(event_id: str, **extra: Any) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "event_id": event_id,
        "event_time": "2026-11-25T11:59:00Z",
        "cloud": "commercial",
        "customer_id": CUSTOMER,
        "source_id": SOURCE,
        "request_id": "req-guards",
        **extra,
    }


def ce(type_: str, data: Any, ce_id: str) -> dict[str, Any]:
    return {
        "specversion": "1.0",
        "id": ce_id,
        "source": "synthetic/guards",
        "type": type_,
        "datacontenttype": "application/json",
        "data": data,
    }


def attr(key: str, value: Any) -> dict[str, Any]:
    if isinstance(value, int) and not isinstance(value, bool):
        return {"key": key, "value": {"intValue": str(value)}}
    return {"key": key, "value": {"stringValue": value}}


def span(span_id: str, attrs: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "traceId": TRACE,
        "spanId": span_id,
        "parentSpanId": "",
        "name": "chat synthetic",
        "status": {"code": 1},
        "startTimeUnixNano": "1700000000000000000",
        "endTimeUnixNano": "1700000000250000000",
        "attributes": [attr(k, v) for k, v in attrs.items()],
    }


def traces_doc(spans: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "resourceSpans": [
            {
                "resource": {"attributes": [attr("neurosphere.source_id", SOURCE)]},
                "scopeSpans": [{"scope": {"name": "synthetic"}, "spans": spans}],
            }
        ]
    }


def metrics_doc(body: str) -> dict[str, Any]:
    point = {
        "asInt": "42",
        "timeUnixNano": "1700000000000000000",
        "attributes": [attr("gen_ai.prompt", body)],
    }
    metric = {
        "name": "gen_ai.usage.input_tokens",
        "sum": {"aggregationTemporality": 2, "dataPoints": [point]},
    }
    return {
        "resourceMetrics": [
            {
                "resource": {"attributes": [attr("neurosphere.source_id", SOURCE)]},
                "scopeMetrics": [{"metrics": [metric]}],
            }
        ]
    }


def body_item(issued: Issued, event_id: str, credential: str) -> dict[str, Any]:
    """A CloudEvents telemetry item with canaries in every body shape the edge knows."""
    data = telemetry_data(
        event_id,
        domain_id=DOMAIN,
        prompt=f"{issued.canary()} please use {credential} for the call",
        response=f"done {issued.canary()}",
        **{
            "gen_ai.input.messages": [
                {"role": "user", "content": f"{issued.canary()} again {credential}"}
            ]
        },
    )
    return ce(TELEMETRY_TYPE, data, f"ce-{event_id}")


@dataclass
class Scenario:
    capture_on: bool
    issued: Issued
    credential: str
    service: IngestService
    publisher: InMemoryPublisher
    capture: EdgeCapture
    store: InMemoryInteractionStore
    audit: RecordingAudit

    @property
    def messages(self) -> list[HubMessage]:
        return list(self.publisher.messages)

    @property
    def published(self) -> list[bytes]:
        return [m.to_bytes() for m in self.publisher.messages]

    def message_for(self, event_id: str) -> HubMessage:
        (found,) = [m for m in self.publisher.messages if m.event_id == event_id]
        return found

    async def audit_records(self) -> list[AuditRecord]:
        return await self.audit.read_range(CHAIN)


async def run_scenario(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, capture_on: bool
) -> Scenario:
    """Three requests: a captured item, an item whose key wrap fails, and an OTLP span."""
    issued = Issued()
    credential = issued.credential()
    publisher = InMemoryPublisher()
    registration = producer()
    service = ingest_service(publisher, registration)
    capture, store, audit, wrapper = await edge_capture(
        tmp_path, monkeypatch, capture_on=capture_on
    )
    service.attach_capture(capture)

    first = json.dumps(body_item(issued, CAPTURED_EVENT, credential)).encode()
    result = await service.ingest_events(
        registration, first, STRUCTURED, correlation_id=CORRELATION
    )
    assert result.accepted == 1

    wrapper.fail = True
    second = json.dumps([body_item(issued, WRAP_FAILED_EVENT, credential)]).encode()
    result = await service.ingest_events(registration, second, BATCH, correlation_id=CORRELATION)
    assert result.accepted == 1
    wrapper.fail = False

    # This span is never captured, by design: the edge stamps no ``domain_id`` on OTLP spans and
    # a capture policy needs both the registered source and the payload domain (GD-46), so it
    # is skipped as ``domain_missing``. It still carries a body, so every guard checks it.
    spans = [span("c7ad6b7169203331", {"gen_ai.prompt": f"{issued.canary()} {credential}"})]
    traces = json.dumps(traces_doc(spans)).encode()
    result = await service.ingest_otlp_traces(registration, traces, correlation_id=CORRELATION)
    assert result.accepted == 1

    return Scenario(capture_on, issued, credential, service, publisher, capture, store, audit)


# --- contract -------------------------------------------------------------------------------------


@functools.cache
def _schema_registry() -> Registry:
    resources: list[tuple[str, Resource[Any]]] = []
    for path in sorted(SCHEMA_ROOT.glob("*/v*/*.schema.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        resources.append((doc["$id"], Resource.from_contents(doc, DRAFT202012)))
    return Registry().with_resources(resources)


def telemetry_schema_errors(doc: Any) -> list[str]:
    validator = Draft202012Validator({"$ref": TELEMETRY_SCHEMA_ID}, registry=_schema_registry())
    return [error.message for error in validator.iter_errors(doc)]


# --- worker ---------------------------------------------------------------------------------------

T0: Final = datetime(2026, 11, 25, 12, 30, tzinfo=UTC)


@dataclass
class WorkerSinks:
    quarantine: FakeQuarantineSink = field(default_factory=FakeQuarantineSink)
    archive: FakeArchiveSink = field(default_factory=FakeArchiveSink)
    ledger: FakeLedgerSink = field(default_factory=FakeLedgerSink)
    markers: FakeMarkerStore = field(default_factory=FakeMarkerStore)
    watermarks: FakeWatermarkStore = field(default_factory=FakeWatermarkStore)

    def deps(self) -> PipelineDeps:
        async def no_sleep(_seconds: float) -> None:
            return None

        return PipelineDeps(
            quarantine=self.quarantine,
            archive=self.archive,
            ledger=self.ledger,
            markers=self.markers,
            watermarks=self.watermarks,
            cloud="commercial",
            sleep=no_sleep,
            rng=lambda: 0.5,
            clock=lambda: T0,
        )


def raw_message(body: bytes, offset: int) -> RawMessage:
    return RawMessage(
        body=body,
        partition_id="0",
        offset=str(offset),
        sequence_number=offset,
        enqueued_time=T0 + timedelta(seconds=offset),
    )


async def run_worker(bodies: list[bytes]) -> tuple[BatchResult, WorkerSinks]:
    sinks = WorkerSinks()
    raws = [raw_message(body, offset) for offset, body in enumerate(bodies)]
    result = await process_batch(raws, sinks.deps(), IngestionSettings())
    return result, sinks


def with_body(message_bytes: bytes, issued: Issued, credential: str) -> bytes:
    """A published message with a body put back in (what a broken producer would send)."""
    doc = json.loads(message_bytes)
    doc["data"]["prompt"] = f"{issued.canary()} smuggled {credential}"
    doc["data"]["gen_ai.output.messages"] = [{"role": "assistant", "content": issued.canary()}]
    return json.dumps(doc).encode()


# --- quarantine blob container --------------------------------------------------------------------


@dataclass
class _Item:
    name: str
    metadata: Mapping[str, str] | None


class _Download:
    def __init__(self, data: bytes) -> None:
        self._data = data

    async def readall(self) -> bytes:
        return self._data


class FakeBlobContainer:
    """In-memory ``BlobContainer`` (first write wins, like the real one with overwrite=False)."""

    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}
        self.metadata: dict[str, dict[str, str]] = {}

    async def upload_blob(
        self,
        name: str,
        data: bytes,
        *,
        overwrite: bool = False,
        metadata: Mapping[str, str] | None = None,
    ) -> Any:
        if name in self.blobs and not overwrite:
            raise ResourceExistsError("exists")
        self.blobs[name] = bytes(data)
        self.metadata[name] = dict(metadata or {})
        return None

    async def download_blob(self, blob: str) -> _Download:
        if blob not in self.blobs:
            raise ResourceNotFoundError("missing")
        return _Download(self.blobs[blob])

    async def list_blobs(
        self, name_starts_with: str | None = None, include: list[str] | None = None
    ) -> AsyncIterator[_Item]:
        del include
        for name in sorted(self.blobs):
            if name_starts_with is None or name.startswith(name_starts_with):
                yield _Item(name, self.metadata.get(name))


def assert_audit_draft_metadata_only(draft: AuditDraft) -> None:
    document = draft.model_dump(mode="json")
    assert_metadata_only(document)
