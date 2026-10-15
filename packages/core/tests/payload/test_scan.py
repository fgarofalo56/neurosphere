from typing import Any

from neurosphere_core.payload import find_body_fields


def test_clean_is_empty() -> None:
    assert find_body_fields({"a": [1, {"b": 2}], "model": "m"}) == []
    assert find_body_fields([]) == []
    assert find_body_fields("scalar") == []


def test_dict_key_pointers() -> None:
    payload = {"a": {"prompt": "x"}, "b": [{"llm.response": "y"}], "Prompt": "z"}
    assert find_body_fields(payload) == ["/Prompt", "/a/prompt", "/b/0/llm.response"]


def test_otlp_item_pointer() -> None:
    payload = {
        "attributes": [
            {"key": "ok", "value": {"stringValue": "1"}},
            {"key": "gen_ai.completion", "value": {"stringValue": "secret"}},
        ]
    }
    assert find_body_fields(payload) == ["/attributes/1"]


def test_pointer_escaping() -> None:
    payload = {"a/b": {"~x": {"prompt": 1}}}
    assert find_body_fields(payload) == ["/a~1b/~0x/prompt"]


def test_paths_do_not_contain_values() -> None:
    payload = {"prompt": "fake-secret-body-0000"}
    assert all("fake-secret" not in p for p in find_body_fields(payload))


def test_deep_input_does_not_overflow() -> None:
    node: Any = {"response": 1}
    for _ in range(100_000):
        node = [node]
    assert len(find_body_fields(node)) == 1
