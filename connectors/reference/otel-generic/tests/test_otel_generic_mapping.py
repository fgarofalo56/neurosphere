"""Unit tests for the generic OTel push connector. No network: the PRP-07 ingest edge runs
in-process behind an ASGI transport with an in-memory publisher, so the payloads the connector
produces are checked by the edge's own parsing, auth and mapping code.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

import httpx
import pytest
from neurosphere_api.app import create_app
from neurosphere_api.ingest import (
    IngestSettings,
    InMemoryPublisher,
    ProducerRegistration,
    StaticProducerRegistry,
    build_service,
    configure_ingest,
    hash_secret,
)
from neurosphere_connector import CredentialBroker, StaticCredentialResolver
from neurosphere_connector.testing import ConnectorContractSuite
from neurosphere_connector_otel_generic import (
    DEFAULT_CREDENTIAL_REF,
    OTLP_SPEC_URL,
    SPEC_OBSERVED_DATE,
    ConnectorSpanExporter,
    OtelGenericConnector,
    telemetry_event_to_cloudevent,
)
from neurosphere_contracts.telemetry.v1.telemetry_event import TelemetryEvent
from neurosphere_core.cloud import Settings
from neurosphere_core.errors import (
    DependencyTransientError,
    InvalidSchemaError,
    RateLimitedError,
    UnauthorizedError,
)
from neurosphere_core.payload import find_body_fields
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

PRODUCER_ID = "otel-prod"
# Generated per run so no secret-shaped literal sits in the repo.
SECRET = f"fixture-{uuid.uuid4().hex}"
TRACE = "4bf92f3577b34da6a3ce929d0e0e4736"
ROOT, CHILD = "00f067aa0ba902b7", "53995c3f42cd8ad8"
START = 1_790_000_000_000_000_000

Doc = dict[str, Any]


def _attr(key: str, value: Any) -> Doc:
    kind = (
        "boolValue"
        if isinstance(value, bool)
        else "intValue"
        if isinstance(value, int)
        else "stringValue"
    )
    return {"key": key, "value": {kind: value}}


def _span(span_id: str, parent: str | None, attrs: list[Doc], *, end: bool = True) -> Doc:
    span: Doc = {
        "traceId": TRACE,
        "spanId": span_id,
        "name": "chat",
        "startTimeUnixNano": str(START),
        "attributes": attrs,
    }
    if parent:
        span["parentSpanId"] = parent
    if end:
        span["endTimeUnixNano"] = str(START + 250_000_000)
    return span


def _traces(*spans: Doc) -> Doc:
    return {
        "resourceSpans": [
            {
                "resource": {"attributes": []},
                "scopeSpans": [{"scope": {"name": "t"}, "spans": spans}],
            }
        ]
    }


def _root(value: Any) -> str | None:
    """The string inside a contract RootModel id, or None when the field is null."""
    return None if value is None else str(value.root)


class RecordingTransport(httpx.AsyncBaseTransport):
    """Wraps another transport and records every request (headers and body)."""

    def __init__(self, inner: httpx.AsyncBaseTransport) -> None:
        self.inner = inner
        self.requests: list[httpx.Request] = []
        self.bodies: list[bytes] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        self.bodies.append(request.content)
        return await self.inner.handle_async_request(request)


class Edge:
    def __init__(self, publisher: InMemoryPublisher, transport: RecordingTransport) -> None:
        self.publisher = publisher
        self.transport = transport

    @property
    def events(self) -> list[TelemetryEvent]:
        return [TelemetryEvent.model_validate(m.data) for m in self.publisher.messages]


@pytest.fixture
def edge() -> Edge:
    settings = Settings(env="local")
    publisher = InMemoryPublisher()
    registration = ProducerRegistration(
        producer_id=PRODUCER_ID,
        secret_sha256=hash_secret(SECRET),
        customer_id="synthco",
        cloud="commercial",
        sources={"otel-src": "application"},
    )
    service = build_service(
        settings,
        IngestSettings(rate_limit_rps=100_000, rate_limit_burst=100_000),
        publisher,
        registry=StaticProducerRegistry([registration]),
    )
    app = create_app(settings)
    configure_ingest(app, service)
    return Edge(publisher, RecordingTransport(httpx.ASGITransport(app=app)))


def make_connector(
    transport: httpx.AsyncBaseTransport, **kwargs: Any
) -> tuple[OtelGenericConnector, StaticCredentialResolver, CredentialBroker]:
    resolver = StaticCredentialResolver(
        {DEFAULT_CREDENTIAL_REF.vault_ref: f"{PRODUCER_ID}.{SECRET}"}
    )
    broker = CredentialBroker(resolver, [DEFAULT_CREDENTIAL_REF])

    async def no_sleep(_: float) -> None:
        return None

    connector = OtelGenericConnector(
        ingest_url="http://edge.invalid/v1/ingest",
        credentials=broker,
        client=httpx.AsyncClient(transport=transport),
        sleep=no_sleep,
        **kwargs,
    )
    return connector, resolver, broker


# -- mapping through the edge ---------------------------------------------------------------


async def test_trace_span_and_parent_ids_are_preserved(edge: Edge) -> None:
    connector, _, _ = make_connector(edge.transport)
    summary = await connector.push_traces(
        _traces(
            _span(ROOT, None, [_attr("gen_ai.operation.name", "invoke_agent")]),
            _span(CHILD, ROOT, [_attr("gen_ai.operation.name", "chat")]),
        )
    )
    assert summary.accepted == 2
    by_span = {_root(e.span_id): e for e in edge.events}
    assert _root(by_span[ROOT].trace_id) == TRACE
    assert by_span[ROOT].parent_span_id is None
    assert _root(by_span[CHILD].parent_span_id) == ROOT
    await connector.close()


async def test_missing_optional_fields_stay_null_never_zero(edge: Edge) -> None:
    connector, _, _ = make_connector(edge.transport)
    await connector.push_traces(_traces(_span(ROOT, None, [], end=False)))
    (event,) = edge.events
    assert event.token_breakdown is None
    assert event.duration_ms is None
    assert event.model is None
    assert event.provider is None
    assert event.outcome == "unknown"
    await connector.close()


async def test_prompt_and_response_attributes_are_dropped_before_send(edge: Edge) -> None:
    connector, _, _ = make_connector(edge.transport)
    secret_prompt = "PROMPT-CANARY-do-not-send"  # noqa: S105
    summary = await connector.push_traces(
        _traces(
            _span(
                ROOT,
                None,
                [
                    _attr("gen_ai.prompt", secret_prompt),
                    _attr("gen_ai.completion", "COMPLETION-CANARY"),
                    _attr("app.response", "RESPONSE-CANARY"),
                    _attr("gen_ai.usage.input_tokens", 12),
                ],
            )
        )
    )
    sent = edge.transport.bodies[-1]
    assert b"CANARY" not in sent
    assert find_body_fields(json.loads(sent)) == []
    assert summary.dropped_fields["gen_ai.prompt"] == 1
    (event,) = edge.events
    assert event.token_breakdown is not None
    assert event.token_breakdown.input == 12
    assert event.token_breakdown.output is None  # unknown, not 0
    await connector.close()


async def test_cloudevents_with_nulls_are_accepted_and_bodies_dropped(edge: Edge) -> None:
    connector, _, _ = make_connector(edge.transport)
    data: Doc = {
        "schema_version": "1.0.0",
        "event_id": "evt-1",
        "event_time": "2026-10-01T00:00:00.000Z",
        "cloud": "commercial",
        "customer_id": "synthco",
        "source_id": "otel-src",
        "span_kind": "model_call",
        "model": None,
        "prompt": "CE-PROMPT-CANARY",
    }
    summary = await connector.push_events([telemetry_event_to_cloudevent(data)])
    assert summary.accepted == 1
    assert b"CE-PROMPT-CANARY" not in edge.transport.bodies[-1]
    (event,) = edge.events
    assert event.model is None
    assert event.token_breakdown is None
    await connector.close()


async def test_invalid_cloudevent_is_rejected_locally_without_a_request(edge: Edge) -> None:
    connector, _, _ = make_connector(edge.transport)
    with pytest.raises(ValueError, match="not a valid CloudEvent"):
        await connector.push_events([{"specversion": "0.3", "id": "x"}])
    assert edge.transport.requests == []
    await connector.close()


async def test_sdk_readable_spans_flow_through_the_edge(edge: Edge) -> None:
    memory = InMemorySpanExporter()
    provider = TracerProvider(resource=Resource.create({"service.name": "demo"}))
    provider.add_span_processor(SimpleSpanProcessor(memory))
    tracer = provider.get_tracer("t")
    with tracer.start_as_current_span("invoke_agent") as parent:
        parent.set_attribute("gen_ai.operation.name", "invoke_agent")
        with tracer.start_as_current_span("chat") as child:
            child.set_attribute("gen_ai.request.model", "synthetic-model")
            child.set_attribute("gen_ai.prompt", "SDK-PROMPT-CANARY")
    spans = memory.get_finished_spans()

    connector, _, _ = make_connector(edge.transport, source_id="otel-src")
    summary = await connector.export_spans(spans)
    assert summary.accepted == 2
    assert b"SDK-PROMPT-CANARY" not in edge.transport.bodies[-1]
    sdk_ids = {format(s.context.span_id, "016x") for s in spans if s.context is not None}
    assert {_root(e.span_id) for e in edge.events} == sdk_ids
    child_event = next(e for e in edge.events if e.model is not None)
    assert child_event.model is not None
    assert child_event.model.root == "synthetic-model"
    assert child_event.parent_span_id is not None
    await connector.close()


async def test_span_exporter_adapter_returns_success(edge: Edge) -> None:
    connector, _, _ = make_connector(edge.transport)
    exporter = ConnectorSpanExporter(connector)
    memory = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(memory))
    with provider.get_tracer("t").start_as_current_span("chat"):
        pass
    # export() blocks its caller; run it off the test's event loop thread.
    import asyncio

    from opentelemetry.sdk.trace.export import SpanExportResult

    result = await asyncio.to_thread(exporter.export, memory.get_finished_spans())
    exporter.shutdown()
    assert result is SpanExportResult.SUCCESS
    assert len(edge.publisher.messages) == 1
    await connector.close()


# -- batching, retries and health ------------------------------------------------------------


async def test_batches_are_bounded_by_item_count(edge: Edge) -> None:
    connector, _, _ = make_connector(edge.transport, max_batch_items=2)
    spans = [_span(f"{i:016x}", None, []) for i in range(1, 6)]
    summary = await connector.push_traces(_traces(*spans))
    assert summary.requests == 3
    assert summary.accepted == 5
    await connector.close()


async def test_batches_are_bounded_by_size(edge: Edge) -> None:
    connector, _, _ = make_connector(edge.transport, max_batch_bytes=1200)
    spans = [_span(f"{i:016x}", None, []) for i in range(1, 9)]
    summary = await connector.push_traces(_traces(*spans))
    assert summary.requests > 1
    assert all(len(b) <= 1200 for b in edge.transport.bodies)
    assert summary.accepted == 8
    await connector.close()


class Scripted(httpx.AsyncBaseTransport):
    def __init__(self, *responses: httpx.Response | Exception) -> None:
        self.responses = list(responses)
        self.calls = 0
        self.auth: list[str] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        self.auth.append(request.headers.get("authorization", ""))
        item = self.responses[min(self.calls, len(self.responses)) - 1]
        if isinstance(item, Exception):
            raise item
        return item


def _accepted() -> httpx.Response:
    return httpx.Response(202, json={"accepted": 1, "rejected": [], "ignored": []})


async def test_429_maps_to_rate_limited_after_bounded_retries() -> None:
    transport = Scripted(httpx.Response(429, headers={"retry-after": "7"}))
    connector, _, _ = make_connector(transport, max_attempts=3)
    with pytest.raises(RateLimitedError) as caught:
        await connector.push_traces(_traces(_span(ROOT, None, [])))
    assert caught.value.retry_after_seconds == 7
    assert transport.calls == 3
    health = await connector.health()
    assert health.state.value == "rate_limited"
    assert health.rate_limit.retry_after_seconds == 7
    await connector.close()


async def test_transient_failures_retry_then_succeed() -> None:
    transport = Scripted(httpx.Response(503), httpx.ConnectError("boom"), _accepted())
    connector, _, _ = make_connector(transport, max_attempts=4)
    summary = await connector.push_traces(_traces(_span(ROOT, None, [])))
    assert summary.accepted == 1
    assert transport.calls == 3
    assert (await connector.health()).state.value == "healthy"
    await connector.close()


async def test_persistent_503_raises_dependency_transient() -> None:
    transport = Scripted(httpx.Response(503))
    connector, _, _ = make_connector(transport, max_attempts=2)
    with pytest.raises(DependencyTransientError):
        await connector.push_traces(_traces(_span(ROOT, None, [])))
    assert transport.calls == 2
    await connector.close()


async def test_401_is_not_retried_and_credential_is_re_resolved() -> None:
    transport = Scripted(httpx.Response(401), _accepted())
    connector, resolver, _ = make_connector(transport, max_attempts=3)
    with pytest.raises(UnauthorizedError):
        await connector.push_traces(_traces(_span(ROOT, None, [])))
    assert transport.calls == 1
    resolver.rotate(DEFAULT_CREDENTIAL_REF, f"{PRODUCER_ID}.rotated-secret-value")
    await connector.push_traces(_traces(_span(ROOT, None, [])))
    assert transport.calls == 2
    assert transport.auth[0].endswith(SECRET)
    assert transport.auth[1].endswith("rotated-secret-value")
    await connector.close()


async def test_other_4xx_is_invalid_schema_and_not_retried() -> None:
    transport = Scripted(httpx.Response(422, json={"detail": "x"}))
    connector, _, _ = make_connector(transport, max_attempts=3)
    with pytest.raises(InvalidSchemaError):
        await connector.push_traces(_traces(_span(ROOT, None, [])))
    assert transport.calls == 1
    await connector.close()


async def test_rotated_credential_is_used_on_the_next_request(edge: Edge) -> None:
    connector, resolver, broker = make_connector(edge.transport)
    await connector.push_traces(_traces(_span(ROOT, None, [])))
    resolver.rotate(DEFAULT_CREDENTIAL_REF, f"{PRODUCER_ID}.not-the-registered-secret")
    with pytest.raises(UnauthorizedError):
        await connector.push_traces(_traces(_span(CHILD, None, [])))
    assert "not-the-registered-secret" in edge.transport.requests[-1].headers["authorization"]
    assert broker.names == ("producer_credential",)
    await connector.close()


# -- secrets and logs ------------------------------------------------------------------------


async def test_credential_never_appears_in_logs_errors_or_reports(
    edge: Edge, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    connector, resolver, _ = make_connector(edge.transport)
    await connector.push_traces(_traces(_span(ROOT, None, [])))
    resolver.rotate(DEFAULT_CREDENTIAL_REF, f"{PRODUCER_ID}.wrong-secret-canary")
    with pytest.raises(UnauthorizedError) as caught:
        await connector.push_traces(_traces(_span(CHILD, None, [])))
    health = (await connector.health()).model_dump_json()
    text = "\n".join(
        [
            caplog.text,
            health,
            repr(caught.value),
            str(caught.value),
            repr(await connector.credential("producer_credential")),
        ]
    )
    assert SECRET not in text
    assert "wrong-secret-canary" not in text
    assert connector.manifest.model_dump_json().count(SECRET) == 0
    await connector.close()


# -- manifest -------------------------------------------------------------------------------


def test_manifest_is_advisory_and_cites_the_otlp_spec() -> None:
    connector, _, _ = make_connector(Scripted(_accepted()))
    manifest = connector.manifest
    assert manifest.advisory is True
    assert manifest.write_support.supported is False
    assert (
        manifest.documentation_url == OTLP_SPEC_URL == "https://opentelemetry.io/docs/specs/otlp/"
    )
    assert "telemetry_ingest" in manifest.capabilities
    assert manifest.freshness.typical_delay_ms is None  # unknown, not 0
    assert manifest.rate_limits is None
    assert SPEC_OBSERVED_DATE == "2026-10-17"


class TestOtelGenericContract(ConnectorContractSuite):
    @pytest.fixture
    def connector(self) -> Any:
        connector, _, _ = make_connector(Scripted(_accepted()))
        return connector
