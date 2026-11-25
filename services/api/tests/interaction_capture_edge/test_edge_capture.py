"""PRP-103 item 3: the ingest-edge capture branch (acceptance criteria 2-6 via IngestService).

Fake (in-memory) publisher, in-memory interaction and policy stores, the real matcher and
pipeline, ``LocalFileKeyWrapper`` under ``tmp_path`` and the real audit repository (its seal runs
the metadata-only content guard). Canaries and credential-shaped values are built per test.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from neurosphere_api.ingest import capture as edge_module
from neurosphere_api.ingest import otlp_mapping as om
from neurosphere_api.ingest.capture import (
    DEFAULT_MAX_ITEMS_PER_REQUEST,
    ENV_MAX_ITEMS_PER_REQUEST,
    capture_audit_draft,
    capture_target_for,
    edge_correlation_id,
    max_items_per_request_from_env,
)
from neurosphere_contracts.telemetry.v1.telemetry_event import TelemetryEvent
from neurosphere_core.audit.content_guard import FORBIDDEN_KEYS, assert_metadata_only
from neurosphere_core.classification import RedactionFailed
from neurosphere_core.interactions import (
    CaptureAuditEvent,
    CaptureMatcher,
    parse_capture_policy,
)
from neurosphere_core.interactions import capture as core_capture
from neurosphere_core.payload import HubMessage, find_body_fields

from . import edge_helpers as h
from .edge_helpers import (
    BATCH,
    CHAIN,
    CUSTOMER,
    DOMAIN,
    OTHER_DOMAIN,
    OTHER_SOURCE,
    POLICY_ID,
    POLICY_VERSION,
    SOURCE,
    STRUCTURED,
    TELEMETRY_TYPE,
    Rig,
    canary,
    card_number,
    ce,
    github_token,
    rig,
    span,
    telemetry_data,
    traces_doc,
)

CORRELATION = "req-7f3a9c21-edge"


@pytest.fixture(autouse=True)
def no_captured_value_in_logs(caplog: pytest.LogCaptureFixture) -> Iterator[None]:
    """No generated value reaches any log record, on any path, in any logger."""
    h.ISSUED.clear()
    caplog.set_level(logging.DEBUG)
    yield
    logged = [caplog.text]
    for record in caplog.records:
        logged.append(record.getMessage())
        logged.append(repr(record.args))
        logged.append(repr(record.__dict__))
    joined = "\n".join(logged)
    for value in h.ISSUED:
        assert value not in joined


def _sensitive_prompt() -> tuple[str, list[str]]:
    mark = canary()
    token = github_token()
    card = card_number()
    return f"{mark} use {token} and pay with {card} please", [token, card]


async def _send_events(r: Rig, items: list[dict[str, Any]], *, batch: bool = True) -> Any:
    body = items if batch else items[0]
    return await r.service.ingest_events(
        r.producer,
        json.dumps(body).encode(),
        BATCH if batch else STRUCTURED,
        correlation_id=CORRELATION,
    )


def _published(r: Rig) -> list[HubMessage]:
    return list(r.publisher.messages)


def _assert_body_free(r: Rig, *values: str) -> None:
    for message in _published(r):
        raw = message.to_bytes()
        assert find_body_fields(json.loads(raw)) == []
        assert find_body_fields(message.data) == []
        text = raw.decode()
        for value in (*h.ISSUED, *values):
            assert value not in text


def _index_docs(r: Rig) -> list[dict[str, Any]]:
    assert r.store is not None
    return list(r.store.index_backend.documents.values())


async def _audit_records(r: Rig) -> list[dict[str, Any]]:
    assert r.audit is not None
    records = await r.audit.read_range(CHAIN)
    return [rec.model_dump(mode="json") for rec in records]


# --- criterion 2: an approved policy captures exactly one interaction ---------------------------


async def test_approved_policy_captures_one_interaction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    r = await rig(tmp_path, monkeypatch)
    prompt, secrets_used = _sensitive_prompt()
    mark = canary()
    data = telemetry_data("evt-capture-1", domain_id=DOMAIN, prompt=prompt, response=f"ok {mark}")

    result = await _send_events(r, [ce(TELEMETRY_TYPE, data)], batch=False)

    assert result.accepted == 1
    assert result.rejected == []
    assert result.dropped_fields == {"prompt": 1, "response": 1}
    (message,) = _published(r)
    ref = message.data["payload_ref"]
    assert ref["redaction_state"] == "redacted"
    assert ref["capture_policy_id"] == POLICY_ID
    assert ref["capture_policy_version"] == POLICY_VERSION
    assert ref["pointer"] == f"interaction:{ref['interaction_id']}"
    assert {"payment_card"} <= set(ref["detected_categories"])
    assert isinstance(ref["content_parts"], list)
    assert all(not k.endswith(("prompt", "response")) for k in ref)
    _assert_body_free(r)

    docs = _index_docs(r)
    assert len(docs) == 1
    assert docs[0]["interaction_id"] == ref["interaction_id"]
    assert docs[0]["correlation_id"] == edge_correlation_id(CORRELATION)
    assert docs[0]["source_id"] == SOURCE
    assert docs[0]["domain_id"] == DOMAIN

    # Criterion 3: credentials and cards are only stored as typed placeholders.
    assert r.store is not None
    content = await r.store.read_content(CUSTOMER, DOMAIN, ref["interaction_id"])
    stored = content.model_dump_json()
    for value in secrets_used:
        assert value not in stored
        assert value[:12] not in stored
    assert "[[ns-redacted:" in stored
    assert "payment_card" in stored

    # Criterion 5: one interaction.capture record on the domain chain, ids and counts only.
    records = await _audit_records(r)
    assert [rec["operation"] for rec in records] == ["interaction.capture"]
    record = records[0]
    assert record["correlation_id"] == edge_correlation_id(CORRELATION)
    assert record["subject"]["snapshot_ref"] == ref["pointer"]
    assert record["outcome"]["result"] == "succeeded"
    assert_metadata_only(record)
    dumped = json.dumps(record)
    for value in h.ISSUED:
        assert value not in dumped

    assert r.capture is not None
    snap = r.capture.stats.snapshot()
    assert snap["captured"] == 1
    assert snap["capture_skipped_no_policy"] == 0
    assert snap["capture_failed_total"] == 0
    assert snap["capture_shed"] == 0


async def test_otlp_span_with_domain_is_captured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The OTLP mapping (PRP-100's file) does not stamp ``domain_id`` today; a mapping that
    does is simulated here so the traces path is exercised end to end."""
    original = om.map_span

    def with_domain(*args: Any, **kwargs: Any) -> TelemetryEvent:
        event = original(*args, **kwargs)
        return TelemetryEvent.model_validate({**event.model_dump(mode="json"), "domain_id": DOMAIN})

    monkeypatch.setattr(om, "map_span", with_domain)
    r = await rig(tmp_path, monkeypatch)
    prompt, _ = _sensitive_prompt()
    doc = traces_doc(
        [
            span("b7ad6b7169203331", {"gen_ai.prompt": prompt, "gen_ai.request.model": "m-x"}),
            span("b7ad6b7169203332", {"gen_ai.request.model": "m-x"}),
        ]
    )

    result = await r.service.ingest_otlp_traces(
        r.producer, json.dumps(doc).encode(), correlation_id=CORRELATION
    )

    assert result.accepted == 2
    assert result.dropped_fields == {"gen_ai.prompt": 1}
    first, second = _published(r)
    assert first.data["payload_ref"]["redaction_state"] == "redacted"
    assert first.data["payload_ref"]["capture_policy_version"] == POLICY_VERSION
    assert second.data["payload_ref"] is None
    assert len(_index_docs(r)) == 1
    _assert_body_free(r)


async def test_otlp_span_without_domain_is_not_captured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    r = await rig(tmp_path, monkeypatch)
    doc = traces_doc([span("b7ad6b7169203331", {"gen_ai.prompt": canary()})])

    result = await r.service.ingest_otlp_traces(r.producer, json.dumps(doc).encode())

    assert result.accepted == 1
    (message,) = _published(r)
    assert message.data["payload_ref"] is None
    assert _index_docs(r) == []
    assert r.capture is not None
    assert r.capture.stats.snapshot()["skipped_reasons"] == {"domain_missing": 1}
    assert r.capture.stats.capture_skipped_no_policy == 1
    _assert_body_free(r)


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"source_id": OTHER_SOURCE, "domain_id": DOMAIN}, "source_mismatch"),
        ({"domain_id": OTHER_DOMAIN}, "domain_mismatch"),
        ({"domain_id": None}, "domain_missing"),
        ({}, "domain_missing"),
    ],
)
async def test_other_source_other_or_null_domain_is_not_captured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, overrides: dict[str, Any], reason: str
) -> None:
    r = await rig(tmp_path, monkeypatch)
    data = telemetry_data("evt-skip", prompt=canary(), **overrides)

    result = await _send_events(r, [ce(TELEMETRY_TYPE, data)])

    assert result.accepted == 1
    (message,) = _published(r)
    assert message.data["payload_ref"] is None
    assert _index_docs(r) == []
    assert await _audit_records(r) == []
    assert r.capture is not None
    snap = r.capture.stats.snapshot()
    assert snap["capture_skipped_no_policy"] == 1
    assert snap["skipped_reasons"] == {reason: 1}
    assert snap["captured"] == 0
    _assert_body_free(r)


async def test_cost_events_are_never_captured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    r = await rig(tmp_path, monkeypatch)
    cost = {**h.cost_data("cost-1"), "prompt": canary()}
    result = await _send_events(r, [ce(h.COST_TYPE, cost)])
    # The leftover member is rejected by the cost contract after the drop, as today.
    assert result.dropped_fields == {"prompt": 1}
    assert _index_docs(r) == []
    assert r.capture is not None
    assert r.capture.stats.snapshot()["capture_skipped_no_policy"] == 0
    _assert_body_free(r)


# --- criterion 4: failures keep no content, telemetry is still accepted --------------------------


async def test_injected_redaction_failure_is_redaction_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def failing(*_args: Any, **_kwargs: Any) -> RedactionFailed:
        return RedactionFailed(reason="budget_exhausted")

    monkeypatch.setattr(core_capture, "redact", failing)
    r = await rig(tmp_path, monkeypatch)
    prompt, _ = _sensitive_prompt()
    data = telemetry_data("evt-fail", domain_id=DOMAIN, prompt=prompt)

    result = await _send_events(r, [ce(TELEMETRY_TYPE, data)])

    assert result.accepted == 1
    (message,) = _published(r)
    ref = message.data["payload_ref"]
    assert ref["redaction_state"] == "redaction_failed"
    assert r.store is not None
    assert r.store.content_backend.blobs == {}
    (doc,) = _index_docs(r)
    assert doc["content_ref"] is None
    assert doc["redaction_state"] == "redaction_failed"
    assert r.capture is not None
    assert r.capture.stats.snapshot()["capture_failed"] == {"redaction_failed": 1}
    records = await _audit_records(r)
    assert [rec["operation"] for rec in records] == ["interaction.capture_dropped"]
    assert records[0]["outcome"]["detail"] == "reason=redaction_failed"
    assert records[0]["correlation_id"] == edge_correlation_id(CORRELATION)
    _assert_body_free(r)


async def test_audit_write_failure_keeps_no_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    r = await rig(tmp_path, monkeypatch)
    assert r.audit is not None
    r.audit.fail = True
    prompt, _ = _sensitive_prompt()

    result = await _send_events(
        r, [ce(TELEMETRY_TYPE, telemetry_data("evt-a", domain_id=DOMAIN, prompt=prompt))]
    )

    assert result.accepted == 1
    (message,) = _published(r)
    assert message.data["payload_ref"]["redaction_state"] == "redaction_failed"
    assert r.store is not None
    assert r.store.content_backend.blobs == {}
    assert r.capture is not None
    snap = r.capture.stats.snapshot()
    assert snap["capture_failed"] == {"audit_failed": 1}
    assert snap["audit_write_failed"] == 2  # the capture record and the drop record
    assert snap["captured"] == 0
    _assert_body_free(r)


async def test_unexpected_pipeline_error_never_fails_telemetry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    r = await rig(tmp_path, monkeypatch)
    assert r.capture is not None

    async def explode(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("injected " + canary())

    monkeypatch.setattr(r.capture.pipeline, "capture", explode)
    data = telemetry_data("evt-x", domain_id=DOMAIN, prompt=canary())

    result = await _send_events(r, [ce(TELEMETRY_TYPE, data)])

    assert result.accepted == 1
    (message,) = _published(r)
    assert message.data["payload_ref"] is None
    assert r.capture.stats.snapshot()["capture_failed"] == {"edge_error": 1}
    _assert_body_free(r)


# --- criterion 6: shedding ------------------------------------------------------------------------


async def test_rate_shed_gives_no_payload_ref_and_still_publishes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    policy = h.policy_doc(sampling={"rate": 1.0, "max_per_minute": 1})
    r = await rig(tmp_path, monkeypatch, policies=[policy])
    items = [
        ce(TELEMETRY_TYPE, telemetry_data(f"evt-{i}", domain_id=DOMAIN, prompt=canary()), f"ce-{i}")
        for i in range(2)
    ]

    result = await _send_events(r, items)

    assert result.accepted == 2
    refs = [m.data["payload_ref"] for m in _published(r)]
    assert [ref is not None for ref in refs] == [True, False]
    assert r.capture is not None
    snap = r.capture.stats.snapshot()
    assert snap["captured"] == 1
    assert snap["capture_shed"] == 1
    assert snap["shed_reasons"] == {"rate": 1}
    _assert_body_free(r)


async def test_queue_shed_gives_no_payload_ref_and_still_publishes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    r = await rig(
        tmp_path, monkeypatch, pipeline_kwargs={"queue_capacity": 1, "shed_at_percent": 100}
    )
    items = [
        ce(TELEMETRY_TYPE, telemetry_data(f"evt-{i}", domain_id=DOMAIN, prompt=canary()), f"ce-{i}")
        for i in range(3)
    ]

    result = await _send_events(r, items)

    assert result.accepted == 3
    refs = [m.data["payload_ref"] for m in _published(r)]
    assert sum(ref is not None for ref in refs) >= 1
    assert r.capture is not None
    snap = r.capture.stats.snapshot()
    assert snap["captured"] + snap["capture_shed"] == 3
    assert snap["capture_shed"] >= 1
    assert snap["in_flight"] == 0
    assert len(_index_docs(r)) == snap["captured"]
    _assert_body_free(r)


async def test_items_past_the_per_request_cap_are_counted_not_captured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    r = await rig(tmp_path, monkeypatch, max_items_per_request=1)
    items = [
        ce(TELEMETRY_TYPE, telemetry_data(f"evt-{i}", domain_id=DOMAIN, prompt=canary()), f"ce-{i}")
        for i in range(3)
    ]

    result = await _send_events(r, items)

    assert result.accepted == 3
    refs = [m.data["payload_ref"] for m in _published(r)]
    assert [ref is not None for ref in refs] == [True, False, False]
    assert r.capture is not None
    snap = r.capture.stats.snapshot()
    assert snap["captured"] == 1
    assert snap["capture_skipped_item_cap"] == 2
    _assert_body_free(r)


# --- adapter units --------------------------------------------------------------------------------


def _audit_event(operation: Any, reason: str | None) -> CaptureAuditEvent:
    return CaptureAuditEvent(
        operation=operation,
        customer_id=CUSTOMER,
        domain_id=DOMAIN,
        source_id=SOURCE,
        event_id="evt-1",
        correlation_id=edge_correlation_id(str(uuid.uuid4())),
        interaction_id=str(uuid.uuid4()),
        capture_policy_id=POLICY_ID,
        capture_policy_version=POLICY_VERSION,
        detector_set_version="detectors-1.0",
        redaction_state="redacted" if reason is None else "redaction_failed",
        reason=reason,
        part_count=2,
        finding_count=3,
        detected_category_count=2,
    )


@pytest.mark.parametrize(
    ("operation", "reason"),
    [("interaction.capture", None), ("interaction.capture_dropped", "key_wrap_failed")],
)
def test_audit_draft_is_metadata_only(operation: str, reason: str | None) -> None:
    entry = _audit_event(operation, reason)
    draft = capture_audit_draft(entry, cloud="commercial")
    document = draft.model_dump(mode="json")
    assert_metadata_only(document)
    assert document["operation"] == operation
    assert document["correlation_id"] == entry.correlation_id
    assert document["subject"]["snapshot_ref"] == f"interaction:{entry.interaction_id}"
    assert document["subject"]["target"]["entity_type"] == "interaction"
    stack: list[Any] = [document]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            assert not {str(k).lower() for k in node} & FORBIDDEN_KEYS
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)


def test_correlation_id_is_audit_safe() -> None:
    raw = str(uuid.uuid4())
    value = edge_correlation_id(raw)
    assert value == "corr-" + raw.replace("-", "")
    assert edge_correlation_id(None).startswith("ingest-")
    assert edge_correlation_id("bad value!").startswith("ingest-")


def test_max_items_setting() -> None:
    assert max_items_per_request_from_env({}) == DEFAULT_MAX_ITEMS_PER_REQUEST == 100
    assert max_items_per_request_from_env({ENV_MAX_ITEMS_PER_REQUEST: "7"}) == 7
    for bad in ("-1", "many"):
        with pytest.raises(ValueError, match=ENV_MAX_ITEMS_PER_REQUEST):
            max_items_per_request_from_env({ENV_MAX_ITEMS_PER_REQUEST: bad})


def test_capture_target_carries_the_policy_limits() -> None:
    doc = h.policy_doc(kept_categories=["payment_card"], parts=["prompt"])
    matcher = CaptureMatcher(
        [parse_capture_policy(doc)], setting_enabled=True, retention=h.retention()
    )
    decision = matcher.match(SOURCE, DOMAIN, "evt-1")
    assert decision is not None
    target = capture_target_for(decision, source_id=SOURCE)
    assert target.policy_id == POLICY_ID
    assert target.policy_version == POLICY_VERSION
    assert target.domain_id == DOMAIN
    assert target.source_id == SOURCE
    assert target.parts == frozenset({"prompt"})
    assert target.kept_categories == frozenset({"payment_card"})
    assert target.max_per_minute == 600
    assert target.retention_days == 30


def test_module_exports_no_logger() -> None:
    """The adapter never logs: nothing there could leak a captured value."""
    assert not any(isinstance(v, logging.Logger) for v in vars(edge_module).values())
