from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from neurosphere_api.ingest import otlp_mapping as om
from referencing import Registry, Resource

from .conftest import Harness, span, traces_doc

SCOPE = om.Scope(cloud="commercial", customer_id="cust-synthetic", source_id="src-synthetic")
NOW = "2026-01-01T00:00:00.000000Z"
JSON = {"content-type": "application/json"}
SCHEMA_DIR = Path(__file__).resolve().parents[4] / "packages/contracts/schemas"
TOOL = {"gen_ai.operation.name": "execute_tool"}


def _res(**attrs: str) -> dict[str, Any]:
    return {"attributes": [{"key": k, "value": {"stringValue": v}} for k, v in attrs.items()]}


def _map(attrs: dict[str, Any], resource: Any = None, parent: str = "") -> tuple[Any, Counter[str]]:
    drops: Counter[str] = Counter()
    mapped = om.map_span(span(attrs, parent=parent), SCOPE, NOW, resource=resource, drops=drops)
    return mapped, drops


def _service(event: Any) -> str | None:
    return event.service.external_service_id.root if event.service else None


def test_tool_call_span_gets_tool_identity() -> None:
    event, drops = _map({**TOOL, "gen_ai.tool.name": "search_docs"})
    assert event.span_kind == "tool_call"
    assert event.tool is not None
    assert event.tool.tool_name.root == "search_docs"
    assert event.tool.external_tool_id is not None
    assert event.tool.external_tool_id.root == "search_docs"
    assert event.tool.canonical_tool_id is None
    assert not drops
    assert event.schema_version == "1.1.0"


def test_tool_absent_or_wrong_kind() -> None:
    assert _map(TOOL)[0].tool is None
    event, drops = _map({"gen_ai.operation.name": "chat", "gen_ai.tool.name": "search_docs"})
    assert event.tool is None
    assert not drops
    plain = _map({"gen_ai.operation.name": "chat"})[0]
    assert plain.schema_version == "1.0.0"  # no identity -> unchanged


@pytest.mark.parametrize(
    ("value", "reason"),
    [
        ("has space", "invalid"),
        ("what?", "invalid"),
        ("a#b", "invalid"),
        ("me@host", "invalid"),
        ("https://h/x", "invalid"),
        ("x" * 129, "too_long"),
    ],
)
def test_bad_tool_name_dropped_and_counted(value: str, reason: str) -> None:
    event, drops = _map({**TOOL, "gen_ai.tool.name": value})
    assert event.tool is None
    assert dict(drops) == {f"gen_ai.tool.name:{reason}": 1}


def test_service_precedence_and_namespace() -> None:
    res = _res(**{"service.name": "res-svc", "service.namespace": "rns"})
    full = {
        "server.service.name": "called",
        "server.service.namespace": "ns",
        "service.peer.name": "peer",
        "peer.service": "legacy",
    }
    assert _service(_map(full, res)[0]) == "ns/called"
    del full["server.service.name"]
    assert _service(_map({**full, "service.peer.namespace": "pn"}, res)[0]) == "pn/peer"
    assert _service(_map({"peer.service": "legacy"}, res)[0]) == "legacy"
    assert _service(_map({}, res)[0]) == "rns/res-svc"
    assert _service(_map({"server.service.namespace": "ns"}, res)[0]) == "rns/res-svc"


def test_unknown_service_is_absent() -> None:
    for name in ("unknown_service", "unknown_service:python"):
        event, drops = _map({}, _res(**{"service.name": name}))
        assert event.service is None
        assert not drops


def test_invalid_service_counted_then_next_source_tried() -> None:
    event, drops = _map(
        {"server.service.name": "bad name", "peer.service": "legacy"},
        _res(**{"service.name": "res"}),
    )
    assert _service(event) == "legacy"
    assert dict(drops) == {"server.service.name:invalid": 1}
    event, drops = _map({"peer.service": "x" * 257})
    assert event.service is None
    assert dict(drops) == {"peer.service:too_long": 1}


def test_mcp_server_ref() -> None:
    mcp = {"mcp.method.name": "tools/call"}
    assert _map({**mcp, "server.address": "mcp.example.test"})[0].mcp_server_ref == (
        "mcp.example.test"
    )
    assert _map({**mcp, "server.address": "10.0.0.5"})[0].mcp_server_ref == "10.0.0.5"
    event, drops = _map({"server.address": "mcp.example.test"})
    assert event.mcp_server_ref is None
    assert not drops
    assert _map(mcp)[0].mcp_server_ref is None  # stdio: no address


@pytest.mark.parametrize(
    "value",
    ["https://h/x?token=1", "user@host", "host:8080", "host name", " host", "h/x", "a" * 254],
)
def test_bad_server_address_dropped_and_counted(value: str) -> None:
    event, drops = _map({"mcp.method.name": "tools/call", "server.address": value})
    assert event.mcp_server_ref is None
    assert dict(drops) == {"server.address:invalid": 1}


def test_default_call_unchanged() -> None:
    event = om.map_span(span({**TOOL, "gen_ai.tool.name": "t"}), SCOPE, NOW)
    assert event.tool is not None


def test_route_counts_drops_and_still_accepts(harness: Harness) -> None:
    spans = [
        span({**TOOL, "gen_ai.tool.name": "bad tool"}, span_id="b7ad6b7169203331"),
        span(
            {"mcp.method.name": "tools/call", "server.address": "h:1"}, span_id="b7ad6b7169203332"
        ),
        span({"peer.service": "x" * 300}, span_id="b7ad6b7169203333"),
        span({**TOOL, "gen_ai.tool.name": "ok_tool"}, span_id="b7ad6b7169203334"),
    ]
    resp = harness.client.post(
        "/v1/ingest/otlp/traces",
        content=json.dumps(traces_doc(spans, {"service.name": "svc"})),
        headers={**JSON, **harness.auth},
    )
    assert resp.status_code == 202
    body = resp.json()
    assert body["accepted"] == 4
    assert body["rejected"] == []
    assert body["dropped_fields"] == {
        "gen_ai.tool.name:invalid": 1,
        "server.address:invalid": 1,
        "peer.service:too_long": 1,
    }
    assert "bad tool" not in resp.text
    data = [m.data for m in harness.publisher.messages]
    assert data[3]["tool"]["tool_name"] == "ok_tool"
    assert data[2]["service"] == {"external_service_id": "svc", "canonical_service_id": None}


def test_content_attributes_never_reach_event_or_hub(harness: Harness) -> None:
    secret_values = {
        "gen_ai.input.messages": "SECRET-MESSAGES",
        "gen_ai.tool.call.arguments": "SECRET-ARGS",
        "gen_ai.tool.call.result": "SECRET-RESULT",
        "gen_ai.tool.call.id": "SECRET-CALL-ID",
        "gen_ai.tool.description": "SECRET-DESCRIPTION",
    }
    attrs = {**TOOL, "gen_ai.tool.name": "search_docs", **secret_values}
    event, _ = _map(attrs)
    assert "SECRET" not in event.model_dump_json()
    resp = harness.client.post(
        "/v1/ingest/otlp/traces",
        content=json.dumps(traces_doc([span(attrs)])),
        headers={**JSON, **harness.auth},
    )
    assert resp.json()["accepted"] == 1
    assert "SECRET" not in json.dumps(
        [m.model_dump(mode="json") for m in harness.publisher.messages]
    )


def _validator() -> Draft202012Validator:
    registry = Registry()
    for path in SCHEMA_DIR.rglob("*.schema.json"):
        doc = json.loads(path.read_text(encoding="utf-8"))
        registry = registry.with_resource(
            doc.get("$id", path.as_uri()), Resource.from_contents(doc)
        )
        registry = registry.with_resource(path.as_uri(), Resource.from_contents(doc))
    schema = json.loads(
        (SCHEMA_DIR / "telemetry/v1/telemetry-event.schema.json").read_text(encoding="utf-8")
    )
    return Draft202012Validator(schema, registry=registry)


def test_serialized_event_validates_against_json_schema() -> None:
    event, _ = _map(
        {
            **TOOL,
            "gen_ai.tool.name": "search_docs",
            "mcp.method.name": "tools/call",
            "server.address": "mcp.example.test",
            "server.service.name": "docs",
            "server.service.namespace": "team",
        },
        _res(**{"service.name": "agent"}),
        parent="1111111111111111",  # the schema requires a parent on tool_call spans
    )
    payload = json.loads(event.model_dump_json())
    assert payload["tool"]["tool_name"] == "search_docs"
    _validator().validate(payload)
    _validator().validate(json.loads(_map({})[0].model_dump_json()))
