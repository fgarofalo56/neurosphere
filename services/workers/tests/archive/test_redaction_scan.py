"""No prompt/response at any depth, no raw person identifiers, in anything archived."""

from __future__ import annotations

import json
from typing import Any

import pytest
from neurosphere_core.errors import ForbiddenError, InvalidSchemaError
from neurosphere_core.payload import find_body_fields
from neurosphere_workers.archive import (
    PSEUDONYM_PREFIX,
    ArchiveSettings,
    pseudonymize,
    redact_record,
    resolve_pseudonym_key,
)
from neurosphere_workers.archive.settings import LOCAL_DEV_PSEUDONYM_KEY

from .support import T0, Doc, FakeContainer, make_event, make_sink, read_blob

KEY = b"unit-test-key-not-a-secret"
RAW_EMAIL = "alice.synthetic@example.test"
RAW_UID = "user-synthetic-0042"


def _crafted() -> dict[str, Any]:
    return {
        "a": {"b": [{"c": {"prompt": "secret text", "keep": 1}}]},
        "User_ID": RAW_UID,
        "nested": {"deep": [{"enduser.id": RAW_UID, "x": {"Email": RAW_EMAIL}}]},
        "attributes": [
            {"key": "user.email", "value": {"stringValue": RAW_EMAIL}},
            {"key": "gen_ai.prompt", "value": {"stringValue": "secret text"}},
            {"key": "http.method", "value": {"stringValue": "GET"}},
        ],
        "upn": None,
        "response": "secret reply",
    }


def _all_text(obj: Any) -> str:
    return json.dumps(obj)


def test_crafted_record_is_clean_at_every_depth() -> None:
    out = redact_record(_crafted(), KEY)
    text = _all_text(out)
    assert find_body_fields(out) == []
    for secret in ("secret text", "secret reply", RAW_EMAIL, RAW_UID):
        assert secret not in text
    assert out["User_ID"].startswith(PSEUDONYM_PREFIX)
    assert out["nested"]["deep"][0]["x"]["Email"].startswith(PSEUDONYM_PREFIX)
    assert out["upn"] is None  # null stays null
    assert out["a"]["b"][0]["c"] == {"keep": 1}
    email_item = out["attributes"][0]
    assert email_item["value"]["stringValue"].startswith(PSEUDONYM_PREFIX)
    assert out["attributes"][-1]["value"] == {"stringValue": "GET"}
    assert len(out["attributes"]) == 2  # the body item was dropped


def test_pseudonym_is_stable_keyed_and_input_not_mutated() -> None:
    src = _crafted()
    before = json.dumps(src, sort_keys=True)
    a = pseudonymize(src, KEY)
    b = pseudonymize(src, KEY)
    c = pseudonymize(src, b"another-key")
    assert json.dumps(src, sort_keys=True) == before
    assert a == b
    assert a["User_ID"] != c["User_ID"]
    # The same person gets the same pseudonym whether plain or OTLP-wrapped.
    assert a["nested"]["deep"][0]["x"]["Email"] == a["attributes"][0]["value"]["stringValue"]


def test_unrelated_keys_are_untouched() -> None:
    doc = {"user_count": 3, "emailed": True, "nested": [{"model": "m"}]}
    assert pseudonymize(doc, KEY) == doc


async def test_real_events_archive_clean(
    template: Doc, container: FakeContainer, sandbox_telemetry: list[Doc]
) -> None:
    sink = make_sink(container)
    for i, doc in enumerate(sandbox_telemetry[:5]):
        event = await make_event(doc, f"evt-scan-{i}", T0)
        await sink.write(event)
    assert container.blobs
    for data in container.blobs.values():
        record = read_blob(data)
        assert find_body_fields(record) == []
        text = _all_text(record).lower()
        assert '"prompt"' not in text
        assert '"response"' not in text
        assert RAW_EMAIL not in text


def test_leftover_body_fields_are_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    from neurosphere_workers.archive import serialize

    monkeypatch.setattr(serialize, "drop_body_fields", lambda p: (p, {}))
    with pytest.raises(ForbiddenError):
        serialize.redact_record({"prompt": "x"}, KEY)


def test_key_required_outside_local() -> None:
    settings = ArchiveSettings()
    assert resolve_pseudonym_key(settings, env="local") is LOCAL_DEV_PSEUDONYM_KEY
    with pytest.raises(InvalidSchemaError):
        resolve_pseudonym_key(settings, env="prod")
    configured = ArchiveSettings(pseudonym_key="k" * 16)  # type: ignore[arg-type]
    assert resolve_pseudonym_key(configured, env="prod").get_secret_value() == "k" * 16
    assert "k" * 16 not in repr(configured)
