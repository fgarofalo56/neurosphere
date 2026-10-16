from __future__ import annotations

import json
from typing import Any

import pytest
from neurosphere_api.ingest import otlp_mapping as om

from .conftest import TRACE, Harness, attr, span, traces_doc

SCOPE = om.Scope(cloud="commercial", customer_id="cust-synthetic", source_id="src-synthetic")
NOW = "2026-01-01T00:00:00.000000Z"
JSON = {"content-type": "application/json"}


def test_span_maps_fields() -> None:
    event = om.map_span(
        span(
            parent="1111111111111111",
            attrs={
                "gen_ai.operation.name": "chat",
                "gen_ai.system": "azure_openai",
                "gen_ai.request.model": "model-req",
                "gen_ai.response.model": "model-resp",
                "gen_ai.usage.input_tokens": 100,
                "gen_ai.usage.output_tokens": 0,
                "request_id": "req-1",
            },
        ),
        SCOPE,
        NOW,
    )
    assert event.event_id.root == f"{TRACE}:b7ad6b7169203331"
    assert event.parent_span_id is not None
    assert event.parent_span_id.root == "1111111111111111"
    assert event.outcome == "success"
    assert event.duration_ms == 250
    assert event.event_time.root == "2023-11-14T22:13:20.000000000Z"
    assert event.span_kind == "model_call"
    assert event.provider is not None
    assert event.provider.root == "azure_openai"
    assert event.model is not None
    assert event.model.root == "model-resp"
    assert event.request_id is not None
    assert event.request_id.root == "req-1"
    assert event.token_breakdown is not None
    assert event.token_breakdown.input == 100
    assert event.token_breakdown.output == 0  # measured zero stays 0
    assert event.token_breakdown.cached is None


def test_unknowns_stay_null_never_guessed() -> None:
    event = om.map_span(span(status=0, end=None), SCOPE, NOW)
    assert event.token_breakdown is None
    assert event.provider is None
    assert event.model is None
    assert event.request_id is None
    assert event.parent_span_id is None
    assert event.duration_ms is None
    assert event.outcome == "unknown"
    assert event.span_kind == "unknown"


def test_older_attribute_names_and_bad_token_values() -> None:
    event = om.map_span(
        span(attrs={"llm.usage.prompt_tokens": 7, "gen_ai.usage.output_tokens": "many"}),
        SCOPE,
        NOW,
    )
    assert event.token_breakdown is not None
    assert event.token_breakdown.input == 7
    assert event.token_breakdown.output is None


def test_error_status_and_rejections() -> None:
    assert om.map_span(span(status=2), SCOPE, NOW).outcome == "error"
    with pytest.raises(om.MappingError) as no_time:
        om.map_span(span(start=None), SCOPE, NOW)
    assert no_time.value.reason == "missing_time"
    bad = span()
    bad["spanId"] = "xyz"
    with pytest.raises(om.MappingError) as bad_id:
        om.map_span(bad, SCOPE, NOW)
    assert bad_id.value.reason == "invalid_trace_id"


def test_endpoint_partial_success_for_spans(harness: Harness) -> None:
    doc = traces_doc([span(), span(span_id="c7ad6b7169203331", start=None)])
    resp = harness.client.post(
        "/v1/ingest/otlp/traces", content=json.dumps(doc), headers={**JSON, **harness.auth}
    )
    assert resp.status_code == 202
    assert resp.json()["accepted"] == 1
    assert resp.json()["rejected"] == [{"index": 1, "reason_code": "missing_time"}]
    assert len(harness.publisher.messages) == 1


def _metric(name: str, kind: str, point: dict[str, Any], **body: Any) -> dict[str, Any]:
    return {"name": name, kind: {"dataPoints": [point], **body}}


def test_metrics_subset_and_ignored_reasons(harness: Harness) -> None:
    point = {
        "timeUnixNano": "1700000000000000000",
        "asInt": "42",
        "attributes": [attr("gen_ai.request.model", "model-x")],
    }
    delta = {"aggregationTemporality": 2}
    metrics = [
        _metric("gen_ai.usage.input_tokens", "sum", point, **delta),  # mapped
        _metric("gen_ai.usage.output_tokens", "gauge", point),  # mapped
        _metric("gen_ai.client.token.usage", "histogram", {"count": "1"}),  # unsupported type
        _metric("some.other.metric", "gauge", point),  # unmapped name
        _metric("gen_ai.usage.input_tokens", "sum", point, aggregationTemporality=1),  # cumulative
        _metric("gen_ai.usage.input_tokens", "gauge", {"timeUnixNano": "1", "asDouble": 1.5}),
    ]
    doc = {"resourceMetrics": [{"scopeMetrics": [{"metrics": metrics}]}]}
    resp = harness.client.post(
        "/v1/ingest/otlp/metrics", content=json.dumps(doc), headers={**JSON, **harness.auth}
    )
    assert resp.status_code == 202
    body = resp.json()
    assert body["accepted"] == 2
    reasons = {i["path"].rsplit("/", 1)[1]: i["reason_code"] for i in body["ignored"]}
    assert reasons == {
        "2": "unsupported_metric_type",
        "3": "unmapped_metric_name",
        "4": "unsupported_temporality",
    }
    assert body["rejected"] == [{"index": 2, "reason_code": "invalid_metric_value"}]
    tokens = [m.data["token_breakdown"] for m in harness.publisher.messages]
    assert tokens == [
        {"input": 42, "output": None, "cached": None, "reasoning": None},
        {"input": None, "output": 42, "cached": None, "reasoning": None},
    ]
