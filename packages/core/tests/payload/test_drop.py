import copy
import json
import random
from typing import Any

import pytest
from neurosphere_core.payload import (
    BODY_FIELD_NAMES,
    drop_body_fields,
    find_body_fields,
    is_body_field,
)

SECRET = "fake-secret-body-0000"  # noqa: S105


def _otlp() -> dict[str, Any]:
    return {
        "resourceSpans": [
            {
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "name": "chat",
                                "attributes": [
                                    {"key": "gen_ai.prompt", "value": {"stringValue": SECRET}},
                                    {"key": "gen_ai.usage.input_tokens", "value": {"intValue": 5}},
                                    {
                                        "key": "nested",
                                        "value": {
                                            "kvlistValue": {
                                                "values": [
                                                    {
                                                        "key": "LLM.Response",
                                                        "value": {"stringValue": SECRET},
                                                    },
                                                    {"key": "ok", "value": {"stringValue": "x"}},
                                                ]
                                            }
                                        },
                                    },
                                ],
                            }
                        ]
                    }
                ]
            }
        ]
    }


@pytest.mark.parametrize("name", sorted(BODY_FIELD_NAMES))
def test_closed_set_matches(name: str) -> None:
    assert is_body_field(name)
    assert is_body_field(name.upper())


@pytest.mark.parametrize("name", ["llm.prompt", "app.response", "A.B.PROMPT", "Response"])
def test_dotted_suffix_and_case(name: str) -> None:
    assert is_body_field(name)


@pytest.mark.parametrize(
    "name", ["prompt_tokens", "gen_ai.usage.prompt_tokens", "model", "responses", ""]
)
def test_non_body_names(name: str) -> None:
    assert not is_body_field(name)


def test_top_level_and_nested_dicts_and_lists() -> None:
    payload = {
        "prompt": SECRET,
        "model": "m",
        "a": {"Response": SECRET, "keep": 1, "b": [{"llm.prompt": SECRET, "k": 2}, 3]},
    }
    out, counts = drop_body_fields(payload)
    assert out == {"model": "m", "a": {"keep": 1, "b": [{"k": 2}, 3]}}
    assert counts == {"prompt": 1, "response": 1, "llm.prompt": 1}
    assert find_body_fields(out) == []


def test_otlp_attribute_lists() -> None:
    out, counts = drop_body_fields(_otlp())
    span = out["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
    keys = [a["key"] for a in span["attributes"]]
    assert keys == ["gen_ai.usage.input_tokens", "nested"]
    inner = span["attributes"][1]["value"]["kvlistValue"]["values"]
    assert inner == [{"key": "ok", "value": {"stringValue": "x"}}]
    assert counts == {"gen_ai.prompt": 1, "llm.response": 1}
    assert find_body_fields(out) == []


def test_counts_only_never_values() -> None:
    out, counts = drop_body_fields(_otlp())
    assert SECRET not in json.dumps(out)
    assert SECRET not in json.dumps(counts)
    assert all(isinstance(v, int) for v in counts.values())


def test_input_not_mutated() -> None:
    payload = _otlp()
    snapshot = copy.deepcopy(payload)
    out, _ = drop_body_fields(payload)
    assert payload == snapshot
    assert out is not payload


def test_clean_payload_and_scalar_roots() -> None:
    clean = {"a": [1, {"b": None}]}
    out, counts = drop_body_fields(clean)
    assert out == clean
    assert out is not clean
    assert counts == {}
    assert drop_body_fields("x") == ("x", {})
    assert drop_body_fields(None) == (None, {})


def test_deep_input_does_not_overflow() -> None:
    node: Any = {"prompt": SECRET}
    for _ in range(100_000):
        node = {"n": node}
    out, counts = drop_body_fields(node)
    assert counts == {"prompt": 1}
    assert find_body_fields(out) == []


_KEYS = [
    "a",
    "b",
    "model",
    "prompt",
    "Response",
    "gen_ai.completion",
    "x.prompt",
    "gen_ai.input.messages",
]


def _attr(key: str, value: Any) -> dict[str, Any]:
    return {"key": key, "value": value}


def _random_tree(rng: random.Random, depth: int) -> Any:
    roll = rng.random()
    if depth <= 0 or roll < 0.3:
        return rng.choice([None, True, 7, "text"])
    if roll < 0.55:
        return [_random_tree(rng, depth - 1) for _ in range(rng.randint(0, 4))]
    if roll < 0.8:
        return {rng.choice(_KEYS): _random_tree(rng, depth - 1) for _ in range(rng.randint(0, 4))}
    return [
        _attr(rng.choice(_KEYS), _random_tree(rng, depth - 1)) for _ in range(rng.randint(0, 4))
    ]


def test_property_drop_leaves_no_body_fields() -> None:
    # Seeded randomized property check (hypothesis is not a dependency of this repo).
    rng = random.Random(20260101)  # noqa: S311
    for _ in range(500):
        tree = _random_tree(rng, 6)
        injected = {"prompt": "p", "inner": [tree, _attr("gen_ai.prompt", tree)]}
        out, counts = drop_body_fields(injected)
        assert find_body_fields(out) == []
        assert "prompt" not in out
        assert counts["prompt"] >= 1
