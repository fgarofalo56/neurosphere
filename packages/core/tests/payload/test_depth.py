from typing import Any

from neurosphere_core.payload import (
    DEFAULT_MAX_BODY_BYTES,
    DEFAULT_MAX_DEPTH,
    exceeds_depth,
    json_depth,
    raw_json_exceeds_depth,
)


def _nest(levels: int) -> Any:
    node: Any = []
    for _ in range(levels - 1):
        node = [node]
    return node


def test_constants() -> None:
    assert DEFAULT_MAX_DEPTH == 32
    assert DEFAULT_MAX_BODY_BYTES == 1_048_576


def test_json_depth_values() -> None:
    assert json_depth(1) == 0
    assert json_depth([]) == 1
    assert json_depth({}) == 1
    assert json_depth([[]]) == 2
    assert json_depth({"a": [1, {"b": 2}]}) == 3


def test_exceeds_depth_boundary() -> None:
    assert not exceeds_depth(_nest(5), 5)
    assert exceeds_depth(_nest(6), 5)


def test_100k_levels_no_recursion_error() -> None:
    deep = _nest(100_000)
    assert json_depth(deep) == 100_000
    assert exceeds_depth(deep, DEFAULT_MAX_DEPTH)


def test_raw_scan_basic() -> None:
    assert not raw_json_exceeds_depth(b'{"a":[1,2,{"b":3}]}', 3)
    assert raw_json_exceeds_depth(b'{"a":[1,2,{"b":3}]}', 2)


def test_raw_scan_ignores_brackets_in_strings() -> None:
    raw = b'{"a":"[[[[[[[[[[{{{{{{{{"}'
    assert not raw_json_exceeds_depth(raw, 1)


def test_raw_scan_escaped_quotes() -> None:
    # The \" does not end the string, so the following brackets are still string content.
    raw = b'{"a":"x\\"[[[[[[[["}'
    assert not raw_json_exceeds_depth(raw, 1)
    # Escaped backslash before the closing quote: string ends, brackets after it count.
    raw2 = b'["x\\\\",[[[[]]]]]'
    assert raw_json_exceeds_depth(raw2, 3)


def test_raw_scan_100k_deep_and_empty() -> None:
    raw = b"[" * 100_000 + b"]" * 100_000
    assert raw_json_exceeds_depth(raw, DEFAULT_MAX_DEPTH)
    assert not raw_json_exceeds_depth(b"", 1)
    assert not raw_json_exceeds_depth(b"[]" * 100_000, 1)
