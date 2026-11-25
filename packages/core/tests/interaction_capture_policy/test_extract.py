"""PRP-103 item 2: body extraction (Clarification 6 mapping, caps, purity, no values leaked)."""

from __future__ import annotations

import copy
import json
from typing import Any

import pytest
from neurosphere_core.interactions import (
    RAW_PART_CHARS,
    CaptureEnvelopeError,
    ExtractedBody,
    extract_body_parts,
)
from neurosphere_core.payload.guard import drop_body_fields

from .pipeline_helpers import canary


def _attr(key: str, value: dict[str, Any]) -> dict[str, Any]:
    return {"key": key, "value": value}


def _text(body: ExtractedBody | None, part: str) -> str:
    assert body is not None
    matches = [p.text for p in body.parts if p.part == part]
    assert len(matches) == 1
    return matches[0]


def _span(*attrs: dict[str, Any]) -> dict[str, Any]:
    return {
        "traceId": "4bf92f3577b34da6a3ce929d0e0e4736",
        "spanId": "00f067aa0ba902b7",
        "name": "chat",
        "attributes": [_attr("gen_ai.usage.prompt_tokens", {"intValue": "12"}), *attrs],
    }


def test_no_body_returns_none() -> None:
    assert extract_body_parts(_span()) is None
    assert extract_body_parts({"data": {"prompt_tokens": 3, "model": "m"}}) is None
    assert extract_body_parts("prompt") is None
    assert extract_body_parts(None) is None
    assert extract_body_parts({"prompt": ""}) is None
    assert extract_body_parts({"prompt": None}) is None


def test_otlp_span_parts_mapped_per_clarification_6() -> None:
    ask, sys_text, answer = canary(), canary(), canary()
    span = _span(
        _attr("gen_ai.prompt", {"stringValue": ask}),
        _attr("gen_ai.system_instructions", {"stringValue": sys_text}),
        _attr(
            "gen_ai.output.messages",
            {
                "arrayValue": {
                    "values": [
                        {
                            "kvlistValue": {
                                "values": [
                                    _attr("role", {"stringValue": "assistant"}),
                                    _attr("content", {"stringValue": answer}),
                                ]
                            }
                        }
                    ]
                }
            },
        ),
    )
    body = extract_body_parts(span)
    assert body is not None
    assert [p.part for p in body.parts] == ["prompt", "response", "system_instructions"]
    assert _text(body, "prompt") == ask
    assert _text(body, "system_instructions") == sys_text
    assert json.loads(_text(body, "response")) == [{"content": answer, "role": "assistant"}]
    assert body.field_count == 3


def test_suffix_rule_and_bare_names() -> None:
    a, b, c, d = canary(), canary(), canary(), canary()
    body = extract_body_parts(
        {"data": {"llm.prompt": a, "app.response": b, "completion": c, "messages": [d]}}
    )
    assert body is not None
    prompt = _text(body, "prompt")
    response = _text(body, "response")
    assert a in prompt and d in prompt
    assert b in response and c in response


def test_cloudevent_message_list_is_deterministic() -> None:
    who = canary()
    first = {"data": {"messages": [{"role": "user", "content": who, "name": "n"}]}}
    second = {"data": {"messages": [{"name": "n", "content": who, "role": "user"}]}}
    a = extract_body_parts(first)
    b = extract_body_parts(second)
    assert _text(a, "prompt") == _text(b, "prompt")
    assert _text(a, "prompt") == json.dumps(
        [{"content": who, "name": "n", "role": "user"}], separators=(",", ":")
    )


def test_same_kind_fields_join_in_pointer_order() -> None:
    a, b = canary(), canary()
    body = extract_body_parts({"a": {"prompt": a}, "b": {"gen_ai.prompt": b}})
    assert _text(body, "prompt") == a + "\n" + b


def test_input_is_not_mutated_and_matches_what_the_guard_drops() -> None:
    item = {
        "data": {"prompt": canary(), "keep": 1},
        "attrs": [_attr("gen_ai.completion", {"stringValue": canary()})],
    }
    before = copy.deepcopy(item)
    body = extract_body_parts(item)
    assert item == before
    _, dropped = drop_body_fields(item)
    assert body is not None
    assert body.field_count == sum(dropped.values())


def test_body_value_is_not_searched_again() -> None:
    inner = canary()
    body = extract_body_parts({"prompt": {"messages": [inner]}})
    assert body is not None
    assert body.field_count == 1
    assert [p.part for p in body.parts] == ["prompt"]


def test_deep_input_is_walked_iteratively() -> None:
    value = canary()
    node: dict[str, Any] = {"prompt": value}
    for _ in range(2000):
        node = {"n": node}
    assert _text(extract_body_parts(node), "prompt") == value


def test_stored_caps_are_not_applied_before_detection() -> None:
    # Extraction keeps the whole part (up to the raw bound): the policy and envelope caps run
    # on REDACTED text in the pipeline, so a value straddling a cap is still detected whole.
    text = ("word " * 10_000).strip()
    body = extract_body_parts({"prompt": text})
    assert body is not None
    assert body.parts[0].text == text
    assert not body.parts[0].truncated


def test_raw_bound_marks_truncated() -> None:
    text = "y" * (RAW_PART_CHARS + 10)
    body = extract_body_parts({"prompt": text})
    assert body is not None
    assert body.parts[0].char_count == RAW_PART_CHARS
    assert body.parts[0].truncated
    small = extract_body_parts({"prompt": "abc def"}, raw_part_chars=3)
    assert small is not None and small.parts[0].text == "abc" and small.parts[0].truncated


def test_too_deep_value_is_skipped_not_raised() -> None:
    deep: list[object] = []
    node = deep
    for _ in range(5000):
        child: list[object] = []
        node.append(child)
        node = child
    body = extract_body_parts({"prompt": deep, "response": "fine"})
    assert body is not None
    assert [p.part for p in body.parts] == ["response"]
    assert body.skipped == 1


def test_to_envelope_errors_carry_no_value() -> None:
    value = canary()
    body = extract_body_parts({"prompt": value})
    assert body is not None
    with pytest.raises(CaptureEnvelopeError) as raised:
        body.to_envelope(
            cloud="commercial",
            source_id="otel-gateway",
            event_id="evt-1",
            trace_id="not-a-trace-id",
            occurred_at="2026-11-20T10:15:00Z",
        )
    assert str(raised.value) == "content_envelope_invalid"
    assert raised.value.__context__ is None and raised.value.__cause__ is None
    assert value not in repr(raised.value)


def test_control_characters_and_surrogates_are_replaced() -> None:
    raw = "a" + chr(0) + "b" + chr(0x1B) + "c" + chr(0xD800) + "d" + chr(9) + "e"
    text = _text(extract_body_parts({"prompt": raw}), "prompt")
    assert text == "a b c" + chr(0xFFFD) + "d" + chr(9) + "e"


def test_values_never_appear_in_repr() -> None:
    value = canary()
    body = extract_body_parts({"prompt": value, "response": value})
    assert body is not None
    assert value not in repr(body)
    assert all(value not in repr(p) for p in body.parts)


def test_envelope_round_trip() -> None:
    ask, answer = canary(), canary()
    body = extract_body_parts({"prompt": ask, "response": answer})
    assert body is not None
    envelope = body.to_envelope(
        cloud="commercial",
        source_id="otel-gateway",
        event_id="evt-1",
        trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
        occurred_at="2026-11-20T10:15:00Z",
    )
    assert [p.part.root for p in envelope.parts] == ["prompt", "response"]
    again = ExtractedBody.from_envelope(envelope)
    assert [(p.part, p.text) for p in again.parts] == [("prompt", ask), ("response", answer)]
