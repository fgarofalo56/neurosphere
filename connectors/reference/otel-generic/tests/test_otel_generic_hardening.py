"""PRP-09 item 10 (#49): hardening cases for the generic OTel connector."""

from __future__ import annotations

import asyncio
import json
import math
import threading
import uuid
from datetime import UTC, datetime
from email.utils import format_datetime
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from neurosphere_connector import CredentialBroker, StaticCredentialResolver
from neurosphere_connector_otel_generic import (
    DEFAULT_CREDENTIAL_REF,
    ConnectorSpanExporter,
    OtelGenericConnector,
)
from neurosphere_connector_otel_generic.connector import (
    MAX_RETRY_AFTER_SECONDS,
    _manifest,
    _retry_after,
)
from neurosphere_connector_otel_generic.convert import (
    attribute,
    readable_spans_to_otlp,
    redact_outgoing,
)
from neurosphere_contracts.connectors.v1.connector_manifest import CredentialRef
from neurosphere_core.errors import InvalidSchemaError
from neurosphere_core.payload import BODY_FIELD_NAMES, find_body_fields
from opentelemetry.sdk.trace.export import SpanExportResult

SECRET = f"fixture-{uuid.uuid4().hex}"


def _fake_span(attrs: dict[str, Any]) -> Any:
    context = SimpleNamespace(trace_id=0x4BF92F3577B34DA6A3CE929D0E0E4736, span_id=0xF067AA0BA902B7)
    return SimpleNamespace(
        get_span_context=lambda: context,
        resource=None,
        name="chat",
        attributes=attrs,
        parent=None,
        start_time=1,
        end_time=None,
        status=SimpleNamespace(status_code=SimpleNamespace(value=0)),
    )


def test_guard_covers_bare_completion_and_messages() -> None:
    assert {"completion", "messages"} <= BODY_FIELD_NAMES
    clean, counts = redact_outgoing({"a": {"completion": "X", "messages": [{"role": "user"}]}})
    assert find_body_fields(clean) == []
    assert counts == {"completion": 1, "messages": 1}


def test_unsendable_attributes_are_omitted_and_counted() -> None:
    drops: dict[str, int] = {}
    doc = readable_spans_to_otlp(
        [
            _fake_span(
                {
                    "ok": "v",
                    "arr": [1, 2],
                    "raw": b"abc",
                    "none": None,
                    "nan": math.nan,
                    "inf": math.inf,
                }
            )
        ],
        dropped_attributes=drops,
    )
    keys = [a["key"] for a in doc["resourceSpans"][0]["scopeSpans"][0]["spans"][0]["attributes"]]
    assert keys == ["ok"]
    assert drops == {"array": 1, "bytes": 1, "null": 1, "non_finite": 2}
    json.dumps(doc, allow_nan=False)  # valid JSON: no NaN/Infinity tokens


def test_attribute_never_emits_nan_or_inf() -> None:
    assert attribute("x", math.nan) is None
    assert attribute("x", -math.inf) is None
    assert attribute("x", 0.0) == {"key": "x", "value": {"doubleValue": 0.0}}


def test_redact_outgoing_rejects_nan_documents() -> None:
    with pytest.raises(ValueError, match=r"(?i)out of range|nan"):
        redact_outgoing({"v": math.nan})


class _Scripted(httpx.AsyncBaseTransport):
    def __init__(self) -> None:
        self.bodies: list[bytes] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.bodies.append(request.content)
        return httpx.Response(202, json={"accepted": 1, "rejected": [], "ignored": []})


def _connector(transport: httpx.AsyncBaseTransport) -> OtelGenericConnector:
    resolver = StaticCredentialResolver({DEFAULT_CREDENTIAL_REF.vault_ref: f"p.{SECRET}"})
    return OtelGenericConnector(
        ingest_url="http://edge.invalid/v1/ingest",
        credentials=CredentialBroker(resolver, [DEFAULT_CREDENTIAL_REF]),
        client=httpx.AsyncClient(transport=transport),
    )


async def test_export_spans_reports_dropped_attributes_and_sends_valid_json() -> None:
    transport = _Scripted()
    connector = _connector(transport)
    summary = await connector.export_spans(
        [_fake_span({"nan": math.nan, "arr": ["a"], "n": None, "k": "v"})]
    )
    assert summary.dropped_attributes == {"non_finite": 1, "array": 1, "null": 1}
    json.loads(transport.bodies[0])
    assert b"NaN" not in transport.bodies[0]
    await connector.close()


def test_manifest_fails_on_unrecognised_vault_host() -> None:
    # The model pattern already refuses such refs; model_construct bypasses it to hit the guard.
    bad = CredentialRef.model_construct(
        name="producer_credential", vault_ref="https://evil.example.com/secrets/x"
    )
    with pytest.raises(InvalidSchemaError) as caught:
        _manifest(bad)
    assert caught.value.reason == "unrecognized_vault_host"


def test_manifest_recognises_government_vault() -> None:
    ref = CredentialRef(
        name="producer_credential",
        vault_ref="https://ns-kv.vault.usgovcloudapi.net/secrets/x",
    )
    assert list(_manifest(ref).supported_clouds) == ["government"]


def _resp(value: str) -> httpx.Response:
    return httpx.Response(429, headers={"retry-after": value})


def test_retry_after_parses_delta_seconds_and_http_date() -> None:
    now = datetime(2026, 11, 13, 12, 0, 0, tzinfo=UTC)
    assert _retry_after(_resp("7"), now=now) == 7
    when = datetime(2026, 11, 13, 12, 0, 42, tzinfo=UTC)
    assert _retry_after(_resp(format_datetime(when, usegmt=True)), now=now) == 42


def test_retry_after_clamps_and_tolerates_garbage() -> None:
    now = datetime(2026, 11, 13, 12, 0, 0, tzinfo=UTC)
    assert _retry_after(_resp("999999"), now=now) == MAX_RETRY_AFTER_SECONDS
    far = datetime(2030, 1, 1, tzinfo=UTC)
    assert (
        _retry_after(_resp(format_datetime(far, usegmt=True)), now=now) == MAX_RETRY_AFTER_SECONDS
    )
    past = datetime(2020, 1, 1, tzinfo=UTC)
    assert _retry_after(_resp(format_datetime(past, usegmt=True)), now=now) == 1
    assert _retry_after(_resp("soon"), now=now) == 1
    assert _retry_after(httpx.Response(429), now=now) == 1


class _SlowConnector:
    """Stands in for the connector: export_spans blocks until released."""

    def __init__(self) -> None:
        self.release = threading.Event()
        self.started = threading.Event()

    async def export_spans(self, spans: Any) -> None:
        self.started.set()
        await asyncio.to_thread(self.release.wait, 5)


def test_force_flush_waits_for_inflight_export_and_reports_outcome() -> None:
    slow = _SlowConnector()
    exporter = ConnectorSpanExporter(slow)  # type: ignore[arg-type]
    results: list[SpanExportResult] = []
    worker = threading.Thread(target=lambda: results.append(exporter.export([])))
    worker.start()
    assert slow.started.wait(5)
    assert exporter.force_flush(50) is False  # still pending: not flushed
    slow.release.set()
    assert exporter.force_flush(5_000) is True
    worker.join(5)
    assert results == [SpanExportResult.SUCCESS]
    assert exporter.force_flush(10) is True  # nothing pending
    exporter.shutdown()
    assert exporter.export([]) is SpanExportResult.FAILURE  # closed
