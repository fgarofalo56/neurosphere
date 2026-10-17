"""Sandbox traces pushed through the generic OTel connector to the real ingest edge (PRP-09 item 3).

Path under test: sandbox generator -> ``OtelGenericConnector`` (CloudEvents and OTLP, bodies
dropped, vault-referenced producer credential) -> the PRP-07 edge running in-process behind an
ASGI transport -> the Event Hubs emulator -> read back as ``HubMessage`` / ``TelemetryEvent``.

G12 delta (recorded, not hidden): the Event Hubs emulator has no Entra, so the producer identity
here is the edge's registered producer credential (hash-compared bearer token), not an Entra
principal. This test therefore cannot show Entra producer identity or the managed-identity path
to a real namespace; those stay with the live gate (G12), reported OPEN until an approved run.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from neurosphere_connector import CredentialBroker, StaticCredentialResolver
from neurosphere_connector_otel_generic import (
    DEFAULT_CREDENTIAL_REF,
    OtelGenericConnector,
    telemetry_event_to_cloudevent,
)
from neurosphere_contracts.telemetry.v1.telemetry_event import TelemetryEvent
from neurosphere_core.cloud import Settings
from neurosphere_core.payload import HubMessage
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pydantic import ValidationError

from integration.ingestion.support import REPO_ROOT, Producer, edge_client, read_hub

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="module")]

SOURCE = "sandbox-gateway"
CUSTOMER = "synthco"  # the sandbox generator's customer


def _sandbox_events(out: Path) -> list[dict[str, Any]]:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "sandbox.generate",
            "--seed",
            "9",
            "--profile",
            "tiny",
            "--traces-per-agent-day",
            "1",
            "--missing-optional-rate",
            "0.2",
            "--cloud",
            "commercial",
            "--out",
            str(out),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    events: list[dict[str, Any]] = []
    for line in (out / "telemetry.ndjson").read_text(encoding="utf-8").splitlines():
        try:
            doc = json.loads(line)
            TelemetryEvent.model_validate(doc)
        except (ValueError, ValidationError):
            continue  # malformed lines are injected on purpose; only valid ones are sent
        events.append(doc)
    return events


async def test_sandbox_traces_land_as_telemetry_events(tmp_path: Path) -> None:
    events = _sandbox_events(tmp_path / "sandbox")
    by_id = {e["event_id"]: e for e in events}  # duplicates share an id and dedupe at the edge
    assert len(by_id) > 100
    assert any("parent_span_id" in e for e in events)
    assert any("token_breakdown" not in e for e in events)  # missing optional fields exist

    producer = Producer(
        producer_id="it-otel-generic",
        customer_id=CUSTOMER,
        cloud="commercial",
        sources={SOURCE: "gateway"},
    )
    resolver = StaticCredentialResolver(
        {DEFAULT_CREDENTIAL_REF.vault_ref: f"{producer.producer_id}.{producer.secret}"}
    )
    broker = CredentialBroker(resolver, [DEFAULT_CREDENTIAL_REF])

    async with edge_client(Settings(), [producer], tmp_path) as client:
        connector = OtelGenericConnector(
            ingest_url="http://edge.invalid/v1/ingest",
            credentials=broker,
            client=client,
            source_id=SOURCE,
            max_attempts=4,
            backoff_seconds=1.0,
        )
        summary = await connector.push_events([telemetry_event_to_cloudevent(e) for e in events])
        assert summary.rejected == 0
        assert summary.accepted == len(events)
        assert summary.requests > 1  # bounded batches

        memory = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(memory))
        tracer = provider.get_tracer("it")
        with tracer.start_as_current_span("invoke_agent"):
            with tracer.start_as_current_span("chat") as chat:
                chat.set_attribute("gen_ai.request.model", "synthetic-model")
                chat.set_attribute("gen_ai.prompt", "INTEGRATION-PROMPT-CANARY")
        spans = memory.get_finished_spans()
        otlp = await connector.export_spans(spans)
        assert otlp.accepted == 2
        assert otlp.dropped_fields.get("gen_ai.prompt") == 1
        await connector.close()

    context = spans[0].get_span_context()
    assert context is not None
    sdk_trace = format(context.trace_id, "032x")

    def mine(raw: bytes) -> bool:
        return producer.producer_id.encode() in raw

    messages = [HubMessage.from_bytes(raw) for raw in await read_hub(mine)]
    landed = {m.event_id: TelemetryEvent.model_validate(m.data) for m in messages}

    # Every sandbox event landed, with ids and nulls preserved and nothing defaulted to 0.
    for event_id, source in by_id.items():
        got = landed[event_id]
        assert got.trace_id is not None and got.trace_id.root == source["trace_id"]
        assert got.span_id is not None and got.span_id.root == source["span_id"]
        expected_parent = source.get("parent_span_id")
        assert (got.parent_span_id.root if got.parent_span_id else None) == expected_parent
        if "token_breakdown" not in source:
            assert got.token_breakdown is None
        if "duration_ms" not in source:
            assert got.duration_ms is None

    sdk_events = [e for e in landed.values() if e.trace_id and e.trace_id.root == sdk_trace]
    assert len(sdk_events) == 2
    assert all(m.producer_id == producer.producer_id for m in messages)
    assert b"INTEGRATION-PROMPT-CANARY" not in b"".join(m.to_bytes() for m in messages)
