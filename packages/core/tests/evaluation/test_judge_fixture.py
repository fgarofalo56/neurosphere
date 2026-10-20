"""RecordedFixtureJudge: replay only, never fabricate; call recording for zero-call assertions."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from neurosphere_core.evaluation.judge import (
    Judge,
    JudgeRequest,
    JudgeResponse,
    MissingFixtureError,
    RecordedFixtureJudge,
    request_hash,
)
from pydantic import ValidationError


def _request(item_id: str = "it-1", **over: object) -> JudgeRequest:
    base: dict[str, object] = {
        "judge_config_id": "jc-1",
        "judge_config_version": "1",
        "rubric_id": "rb-1",
        "rubric_version": "1",
        "dimension": "groundedness",
        "item_id": item_id,
        "classification": "public",
        "payload": {"b": 2, "a": [1, 2]},
    }
    return JudgeRequest.model_validate({**base, **over})


def test_request_hash_is_stable_and_order_independent() -> None:
    a = _request(payload={"a": 1, "b": 2})
    b = _request(payload={"b": 2, "a": 1})
    assert request_hash(a) == request_hash(b)
    assert len(request_hash(a)) == 64
    assert request_hash(a) != request_hash(_request(item_id="it-2"))
    assert request_hash(a) != request_hash(_request(classification="cui"))


def test_request_hash_known_value() -> None:
    import hashlib

    canonical = (
        '{"classification":"public","dimension":"groundedness","item_id":"it-1",'
        '"judge_config_id":"jc-1","judge_config_version":"1","payload":{"a":[1,2],"b":2},'
        '"rubric_id":"rb-1","rubric_version":"1"}'
    )
    assert request_hash(_request()) == hashlib.sha256(canonical.encode()).hexdigest()


def test_payload_must_be_json_safe() -> None:
    with pytest.raises(ValidationError):
        _request(payload={"x": object()})


async def test_replays_recorded_response_and_records_calls() -> None:
    req = _request()
    judge = RecordedFixtureJudge(
        {
            request_hash(req): {
                "value": 1.0,
                "abstained": False,
                "input_tokens": 10,
                "output_tokens": 3,
            }
        }
    )
    assert isinstance(judge, Judge)
    assert judge.call_count == 0
    resp = await judge.score(req)
    assert resp.value == 1.0 and resp.input_tokens == 10
    assert judge.calls == [req]


async def test_missing_fixture_raises_and_never_fabricates() -> None:
    judge = RecordedFixtureJudge({})
    with pytest.raises(MissingFixtureError) as exc:
        await judge.score(_request())
    assert exc.value.digest == request_hash(_request())
    assert judge.call_count == 1  # the attempt is visible to a zero-call assertion


async def test_loads_from_json_file(tmp_path: Path) -> None:
    req = _request()
    doc = {
        "responses": {
            request_hash(req): {
                "value": None,
                "abstained": True,
                "input_tokens": 5,
                "output_tokens": 1,
            }
        }
    }
    path = tmp_path / "fx.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    resp = await RecordedFixtureJudge.from_file(path).score(req)
    assert resp.abstained and resp.value is None


def test_response_abstention_is_consistent() -> None:
    with pytest.raises(ValidationError):
        JudgeResponse(value=None, abstained=False, input_tokens=0, output_tokens=0)
    with pytest.raises(ValidationError):
        JudgeResponse(value=0.5, abstained=True, input_tokens=0, output_tokens=0)
    with pytest.raises(ValidationError):
        JudgeResponse(value=0.5, abstained=False, input_tokens=-1, output_tokens=0)


def test_judge_module_has_no_network_or_sdk_imports() -> None:
    import ast

    import neurosphere_core.evaluation.judge as mod

    tree = ast.parse(Path(mod.__file__).read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    assert not roots & {"httpx", "requests", "aiohttp", "openai", "azure", "socket", "urllib"}
