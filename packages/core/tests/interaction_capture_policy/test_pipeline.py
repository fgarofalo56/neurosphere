"""PRP-103 item 2: the capture pipeline (acceptance criteria 3-6 at unit level).

In-memory store, ``LocalFileKeyWrapper`` under ``tmp_path``; canaries and credential-shaped
values are generated per test.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from neurosphere_core.audit.content_guard import FORBIDDEN_KEYS
from neurosphere_core.classification import DEFAULT_SET_VERSION, DetectorSet, Match
from neurosphere_core.classification import RedactionFailed as RedactionFailedResult
from neurosphere_core.crypto import WrappedKey
from neurosphere_core.interactions import (
    CapturePipeline,
    CaptureRateLimiter,
    ExtractedBody,
    ExtractedPart,
    InMemoryInteractionStore,
    extract_body_parts,
)
from neurosphere_core.interactions import capture as capture_module
from neurosphere_core.payload.guard import find_body_fields

from . import pipeline_helpers
from .pipeline_helpers import (
    CUSTOMER,
    DOMAIN,
    AuditRecorder,
    FakeClock,
    aboom,
    aws_key_id,
    canary,
    card_number,
    event,
    github_token,
    grouped,
    iban,
    make_store,
    payload_ref_errors,
    storage_account_key,
    target,
)


@pytest.fixture(autouse=True)
def no_captured_value_in_logs(caplog: pytest.LogCaptureFixture) -> Iterator[None]:
    """Every value a test generates is checked against every log record, on every path."""
    pipeline_helpers.ISSUED.clear()
    caplog.set_level(logging.DEBUG)
    yield
    logged = [caplog.text]
    for record in caplog.records:
        logged.append(record.getMessage())
        logged.append(repr(record.args))
        logged.append(repr(getattr(record, "__dict__", {})))
    joined = "\n".join(logged)
    for value in pipeline_helpers.ISSUED:
        assert value not in joined


def _body(prompt: str, response: str | None = None) -> ExtractedBody:
    item: dict[str, Any] = {"data": {"prompt": prompt}}
    if response is not None:
        item["data"]["response"] = response
    body = extract_body_parts(item)
    assert body is not None
    return body


def _leak_forms(value: str) -> list[str]:
    digest = hashlib.sha256(value.encode()).digest()
    return [
        value,
        value[:12],
        value[-12:],
        digest.hex(),
        base64.b64encode(digest).decode(),
        base64.b64encode(value.encode()).decode(),
    ]


async def _plaintext(store: InMemoryInteractionStore, interaction_id: str) -> str:
    content = await store.read_content(CUSTOMER, DOMAIN, interaction_id)
    return content.model_dump_json()


async def _part_texts(store: InMemoryInteractionStore, interaction_id: str) -> str:
    # Stored part texts only: short value fragments can occur by chance in ids or timestamps.
    content = await store.read_content(CUSTOMER, DOMAIN, interaction_id)
    return "\n".join(part.text.root for part in content.parts)


def _assert_failed_index_only(
    store: InMemoryInteractionStore, ref: Any, audit: AuditRecorder, reason: str, pipe: Any
) -> None:
    assert ref is not None
    assert ref.redaction_state == "redaction_failed"
    assert ref.pointer == f"interaction:{ref.interaction_id.root}"
    assert store.content_backend.blobs == {}
    docs = list(store.index_backend.documents.values())
    assert len(docs) == 1
    assert docs[0]["redaction_state"] == "redaction_failed"
    assert docs[0]["content_ref"] is None
    assert docs[0]["interaction_id"] == ref.interaction_id.root
    assert pipe.stats.capture_failed[reason] == 1
    assert pipe.stats.captured == 0
    assert [e.operation for e in audit.events][-1] == "interaction.capture_dropped"
    assert audit.events[-1].reason == reason
    _assert_body_free(ref)


def _assert_body_free(ref: Any) -> None:
    doc = ref.model_dump(mode="json")
    assert find_body_fields(doc) == []
    assert find_body_fields({"payload_ref": doc}) == []
    assert isinstance(doc["content_parts"], list)
    assert payload_ref_errors(doc) == []


# --- criterion 3: what is stored -----------------------------------------------------------------


async def test_credentials_are_stored_only_as_placeholders(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = make_store(tmp_path, monkeypatch)
    pipe = CapturePipeline(store)
    audit = AuditRecorder()
    mark = canary()
    secrets_used = [github_token(), aws_key_id(), storage_account_key()]
    prompt = f"{mark} use {secrets_used[0]} and {secrets_used[1]} please"
    response = f"ok {mark} conn {secrets_used[2]} done"
    evt = event()

    ref = await pipe.capture(_body(prompt, response), target(), evt, audit=audit)

    assert ref is not None
    assert ref.redaction_state == "redacted"
    assert ref.capture_policy_id is not None and ref.capture_policy_id.root == "support-capture"
    assert ref.capture_policy_version == 3
    assert ref.detector_set_version is not None
    assert ref.detector_set_version.root == DEFAULT_SET_VERSION
    categories = {c.root for c in ref.detected_categories or []}
    assert {"vendor_api_key", "cloud_access_key", "connection_string"} <= categories
    assert [p.part.root for p in ref.content_parts or []] == ["prompt", "response"]
    _assert_body_free(ref)

    interaction_id = ref.interaction_id.root  # type: ignore[union-attr]
    text = await _plaintext(store, interaction_id)
    assert mark in text  # the capture really kept the non-sensitive text
    assert "[[ns-redacted:vendor_api_key]]" in text
    assert "[[ns-redacted:cloud_access_key]]" in text
    assert "[[ns-redacted:connection_string]]" in text
    raw = b"".join(store.content_backend.blobs.values())
    index = repr(store.index_backend.documents)
    for secret in secrets_used:
        for form in _leak_forms(secret):
            assert form not in text
            assert form.encode() not in raw
            assert form not in index
            assert form not in repr(ref)

    assert pipe.stats.captured == 1
    assert len(audit.events) == 1
    entry = audit.events[0]
    assert entry.operation == "interaction.capture"
    assert entry.correlation_id == evt.correlation_id
    assert entry.interaction_id == interaction_id
    assert entry.finding_count >= 3
    details = entry.details()
    assert not {k.lower() for k in details} & FORBIDDEN_KEYS
    assert all(mark not in str(v) for v in details.values())
    assert mark not in repr(entry)


async def test_payment_card_redacted_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = make_store(tmp_path, monkeypatch)
    pipe = CapturePipeline(store)
    card = card_number()
    ref = await pipe.capture(_body(f"card {card} thanks"), target(), event(), audit=AuditRecorder())
    assert ref is not None and ref.interaction_id is not None
    text = await _plaintext(store, ref.interaction_id.root)
    assert card not in text
    assert "[[ns-redacted:payment_card]]" in text


async def test_payment_card_kept_when_policy_keeps_it_but_credentials_never(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = make_store(tmp_path, monkeypatch)
    pipe = CapturePipeline(store)
    card, token = card_number(), github_token()
    policy = target(kept_categories=frozenset({"payment_card", "vendor_api_key"}))
    ref = await pipe.capture(
        _body(f"card {card} key {token}"), policy, event(), audit=AuditRecorder()
    )
    assert ref is not None and ref.interaction_id is not None
    text = await _plaintext(store, ref.interaction_id.root)
    assert card in text
    assert token not in text
    assert "[[ns-redacted:vendor_api_key]]" in text
    assert {c.root for c in ref.detected_categories or []} >= {"payment_card", "vendor_api_key"}


async def test_nothing_detected_is_not_required(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = make_store(tmp_path, monkeypatch)
    pipe = CapturePipeline(store)
    mark = canary()
    ref = await pipe.capture(_body(f"hello {mark}"), target(), event(), audit=AuditRecorder())
    assert ref is not None and ref.interaction_id is not None
    assert ref.redaction_state == "not_required"
    assert ref.detected_categories == []
    assert mark in await _plaintext(store, ref.interaction_id.root)
    _assert_body_free(ref)


async def test_parts_outside_the_policy_are_not_captured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = make_store(tmp_path, monkeypatch)
    pipe = CapturePipeline(store)
    ask, answer = canary(), canary()
    ref = await pipe.capture(
        _body(ask, answer), target(parts=frozenset({"response"})), event(), audit=AuditRecorder()
    )
    assert ref is not None and ref.interaction_id is not None
    assert [p.part.root for p in ref.content_parts or []] == ["response"]
    text = await _plaintext(store, ref.interaction_id.root)
    assert answer in text and ask not in text
    none_allowed = target(parts=frozenset({"tool_input"}))
    assert await pipe.capture(_body(ask), none_allowed, event(), audit=AuditRecorder()) is None


async def test_policy_part_cap_truncates_stored_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = make_store(tmp_path, monkeypatch)
    pipe = CapturePipeline(store)
    words = " ".join(canary() for _ in range(10))
    ref = await pipe.capture(
        _body(words), target(max_part_chars=120), event(), audit=AuditRecorder()
    )
    assert ref is not None and ref.content_parts
    part = ref.content_parts[0]
    assert part.truncated is True
    assert part.char_count <= 120


@pytest.mark.parametrize("make_value", [card_number, iban], ids=["spaced_card", "grouped_iban"])
async def test_value_straddling_the_part_cap_is_redacted_whole(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_value: Any
) -> None:
    # Review repro: the cap falls inside a spaced value. Detection must see the whole value.
    store = make_store(tmp_path, monkeypatch)
    pipe = CapturePipeline(store)
    value = make_value()
    prefix = "word " * 20
    prompt = prefix + grouped(value) + " tail"
    ref = await pipe.capture(
        _body(prompt), target(max_part_chars=len(prefix) + 9), event(), audit=AuditRecorder()
    )
    assert ref is not None and ref.interaction_id is not None
    assert ref.redaction_state == "redacted"
    text = await _part_texts(store, ref.interaction_id.root)
    assert "word word" in text
    for group in grouped(value).split(" "):
        assert group not in text
    assert "[[ns-redacted" not in text  # the cut fell inside it: dropped whole, never split
    assert ref.content_parts and ref.content_parts[0].truncated is True
    _assert_body_free(ref)


async def test_cut_raw_part_never_stores_its_tail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A producer (or the raw bound) cut a card after two groups: no detector recognises the
    # fragment, so the guarded tail must not be stored.
    store = make_store(tmp_path, monkeypatch)
    pipe = CapturePipeline(store)
    groups = grouped(card_number()).split(" ")
    text = "word " * 200 + groups[0] + " " + groups[1]
    body = ExtractedBody((ExtractedPart("prompt", text, truncated=True),))
    ref = await pipe.capture(body, target(max_part_chars=32768), event(), audit=AuditRecorder())
    assert ref is not None and ref.interaction_id is not None
    stored = await _part_texts(store, ref.interaction_id.root)
    assert groups[0] not in stored and groups[1] not in stored
    assert "word word" in stored
    assert ref.content_parts and ref.content_parts[0].truncated is True


async def test_hard_cut_without_whitespace_keeps_placeholders_whole(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = make_store(tmp_path, monkeypatch)
    pipe = CapturePipeline(store)
    han = chr(0x6C49)
    card = card_number()
    prompt = han * 94 + "," + card + "," + han * 50
    ref = await pipe.capture(
        _body(prompt), target(max_part_chars=100), event(), audit=AuditRecorder()
    )
    assert ref is not None and ref.interaction_id is not None and ref.content_parts
    content = await store.read_content(CUSTOMER, DOMAIN, ref.interaction_id.root)
    stored = content.parts[0].text.root
    assert stored == han * 94 + ","
    assert card not in stored
    assert ref.content_parts[0].char_count == 95


async def test_per_interaction_budget_applies_to_redacted_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = make_store(tmp_path, monkeypatch)
    pipe = CapturePipeline(store, max_content_chars=150)
    prompt = " ".join(["p" * 9] * 10)  # 99 chars
    response = " ".join(["r" * 9] * 10)
    ref = await pipe.capture(_body(prompt, response), target(), event(), audit=AuditRecorder())
    assert ref is not None and ref.content_parts
    sizes = [(p.part.root, p.char_count, p.truncated) for p in ref.content_parts]
    assert sizes[0] == ("prompt", 99, False)
    assert sizes[1][0] == "response" and sizes[1][2] is True
    assert sum(size for _, size, _ in sizes) <= 150


async def test_cancelled_during_audit_keeps_no_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = make_store(tmp_path, monkeypatch)
    pipe = CapturePipeline(store)
    entered = asyncio.Event()

    async def hanging_audit(_entry: Any) -> None:
        entered.set()
        await asyncio.Event().wait()

    task = asyncio.create_task(
        pipe.capture(_body(canary()), target(), event(), audit=hanging_audit)
    )
    await entered.wait()
    assert len(store.content_backend.blobs) == 1  # stored, audit not yet written
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert store.content_backend.blobs == {}
    assert store.index_backend.documents == {}
    assert pipe.in_flight == 0
    assert pipe.stats.captured == 0


async def test_bad_detector_set_factory_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = make_store(tmp_path, monkeypatch)
    pipe = CapturePipeline(store, detector_set_for=lambda _t: object())  # type: ignore[arg-type,return-value]
    audit = AuditRecorder()
    ref = await pipe.capture(_body(canary()), target(), event(), audit=audit)
    _assert_failed_index_only(store, ref, audit, "detection_failed", pipe)


async def test_mismatched_event_scope_is_not_captured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = make_store(tmp_path, monkeypatch)
    pipe = CapturePipeline(store)
    other = event(domain_id="commercial:acme:neurosphere:domain:sales")
    assert await pipe.capture(_body(canary()), target(), other, audit=AuditRecorder()) is None
    assert pipe.stats.capture_skipped_no_policy == 1
    assert store.index_backend.documents == {}


# --- criterion 4: failures keep nothing ----------------------------------------------------------


class _ExplodingDetector:
    detector_id = "exploding"
    version = "1.0.0"
    kinds = frozenset({"other"})
    always_redact = False

    def find(self, text: str) -> tuple[Match, ...]:
        raise RuntimeError("injected detector failure")


async def test_detection_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = make_store(tmp_path, monkeypatch)
    broken = DetectorSet(
        set_id="broken", version=DEFAULT_SET_VERSION, detectors=(_ExplodingDetector(),)
    )
    pipe = CapturePipeline(store, detector_set_for=lambda _t: broken)
    audit = AuditRecorder()
    ref = await pipe.capture(_body(github_token()), target(), event(), audit=audit)
    _assert_failed_index_only(store, ref, audit, "detection_failed", pipe)
    _assert_body_free(ref)


async def test_redaction_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = make_store(tmp_path, monkeypatch)
    monkeypatch.setattr(
        capture_module, "redact", lambda *_a, **_k: RedactionFailedResult(reason="budget_exhausted")
    )
    pipe = CapturePipeline(store)
    audit = AuditRecorder()
    ref = await pipe.capture(_body(canary()), target(), event(), audit=audit)
    _assert_failed_index_only(store, ref, audit, "redaction_failed", pipe)


async def test_detector_set_version_mismatch_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = make_store(tmp_path, monkeypatch)
    pipe = CapturePipeline(store)
    audit = AuditRecorder()
    ref = await pipe.capture(
        _body(canary()), target(detector_set_version="ns-detectors-9.9.9"), event(), audit=audit
    )
    _assert_failed_index_only(store, ref, audit, "detector_set_mismatch", pipe)


class _FailingWrapper:
    key_id = "local:failing"

    async def wrap(self, data_key: bytes) -> WrappedKey:
        raise RuntimeError("injected key wrap failure")

    async def unwrap(self, wrapped: WrappedKey) -> bytes:
        raise RuntimeError("injected key unwrap failure")


async def test_key_wrap_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = make_store(tmp_path, monkeypatch, wrapper=_FailingWrapper())
    pipe = CapturePipeline(store)
    audit = AuditRecorder()
    ref = await pipe.capture(_body(canary()), target(), event(), audit=audit)
    _assert_failed_index_only(store, ref, audit, "key_wrap_failed", pipe)


async def test_blob_storage_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = make_store(tmp_path, monkeypatch)
    monkeypatch.setattr(store.content_backend, "put", aboom)
    pipe = CapturePipeline(store)
    audit = AuditRecorder()
    ref = await pipe.capture(_body(canary()), target(), event(), audit=audit)
    _assert_failed_index_only(store, ref, audit, "storage_failed", pipe)


async def test_index_storage_failure_removes_the_blob(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = make_store(tmp_path, monkeypatch)
    real_create = store.index_backend.create
    calls: list[str] = []

    async def create_once_failing(record: Any) -> None:
        calls.append(record.redaction_state)
        if record.redaction_state != "redaction_failed":
            raise RuntimeError("injected index failure")
        await real_create(record)

    monkeypatch.setattr(store.index_backend, "create", create_once_failing)
    pipe = CapturePipeline(store)
    audit = AuditRecorder()
    ref = await pipe.capture(_body(canary()), target(), event(), audit=audit)
    _assert_failed_index_only(store, ref, audit, "storage_failed", pipe)
    assert calls[-1] == "redaction_failed"


async def test_retention_not_enabled_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = make_store(tmp_path, monkeypatch, opt_in=False)
    pipe = CapturePipeline(store)
    audit = AuditRecorder()
    ref = await pipe.capture(_body(canary()), target(), event(), audit=audit)
    _assert_failed_index_only(store, ref, audit, "retention_not_enabled", pipe)


# --- criterion 5: audit ---------------------------------------------------------------------------


async def test_audit_write_failure_keeps_no_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = make_store(tmp_path, monkeypatch)
    pipe = CapturePipeline(store)
    audit = AuditRecorder(fail_on=frozenset({"interaction.capture"}))
    evt = event()
    ref = await pipe.capture(_body(canary()), target(), evt, audit=audit)
    _assert_failed_index_only(store, ref, audit, "audit_failed", pipe)
    assert pipe.stats.audit_write_failed == 1
    assert audit.events[-1].correlation_id == evt.correlation_id


async def test_audit_failure_with_failing_delete_still_removes_blob(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = make_store(tmp_path, monkeypatch)
    monkeypatch.setattr(store, "delete", aboom)
    pipe = CapturePipeline(store)
    audit = AuditRecorder(fail_on=frozenset({"interaction.capture"}))
    ref = await pipe.capture(_body(canary()), target(), event(), audit=audit)
    _assert_failed_index_only(store, ref, audit, "audit_failed", pipe)
    assert pipe.stats.cleanup_failed == 1


async def test_dropped_audit_failure_is_counted_not_raised(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = make_store(tmp_path, monkeypatch, wrapper=_FailingWrapper())
    pipe = CapturePipeline(store)
    audit = AuditRecorder(fail_on=frozenset({"interaction.capture_dropped"}))
    ref = await pipe.capture(_body(canary()), target(), event(), audit=audit)
    assert ref is not None and ref.redaction_state == "redaction_failed"
    assert pipe.stats.audit_write_failed == 1


async def test_drop_audit_carries_ids_and_counts_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = make_store(tmp_path, monkeypatch, wrapper=_FailingWrapper())
    pipe = CapturePipeline(store)
    audit = AuditRecorder()
    mark = canary()
    evt = event()
    await pipe.capture(_body(mark), target(), evt, audit=audit)
    (entry,) = audit.events
    assert entry.operation == "interaction.capture_dropped"
    assert entry.correlation_id == evt.correlation_id
    assert entry.redaction_state == "redaction_failed"
    assert mark not in repr(entry)
    assert not {k.lower() for k in entry.details()} & FORBIDDEN_KEYS
    snapshot = repr(pipe.stats.snapshot())
    assert mark not in snapshot


# --- criterion 6: load protection -----------------------------------------------------------------


async def test_shed_when_in_flight_reaches_queue_percent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = make_store(tmp_path, monkeypatch)
    pipe = CapturePipeline(store, queue_capacity=4, shed_at_percent=50)
    assert pipe.shed_threshold == 2
    gate = asyncio.Event()
    entered = asyncio.Semaphore(0)

    async def slow_audit(_entry: Any) -> None:
        entered.release()
        await gate.wait()

    tasks = [
        asyncio.create_task(pipe.capture(_body(canary()), target(), event(), audit=slow_audit))
        for _ in range(2)
    ]
    await entered.acquire()
    await entered.acquire()
    assert pipe.in_flight == 2

    shed = await pipe.capture(_body(canary()), target(), event(), audit=slow_audit)
    assert shed is None
    assert pipe.stats.capture_shed == 1
    assert pipe.stats.shed_reasons["queue"] == 1

    gate.set()
    refs = await asyncio.gather(*tasks)
    assert all(r is not None and r.redaction_state == "not_required" for r in refs)
    assert pipe.in_flight == 0
    assert len(store.content_backend.blobs) == 2


async def test_shed_when_max_per_minute_exceeded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = make_store(tmp_path, monkeypatch)
    clock = FakeClock()
    pipe = CapturePipeline(store, rate_limiter=CaptureRateLimiter(clock=clock))
    limited = target(max_per_minute=2)
    results = [
        await pipe.capture(_body(canary()), limited, event(), audit=AuditRecorder())
        for _ in range(3)
    ]
    assert [r is None for r in results] == [False, False, True]
    assert pipe.stats.capture_shed == 1
    assert pipe.stats.shed_reasons["rate"] == 1
    assert len(store.content_backend.blobs) == 2

    clock.now += 30.0  # half a minute refills one token
    assert await pipe.capture(_body(canary()), limited, event(), audit=AuditRecorder())
    other = target(policy_id="other-capture", max_per_minute=2)
    assert await pipe.capture(_body(canary()), other, event(), audit=AuditRecorder())


async def test_injected_rate_limiter_is_used(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Never:
        def try_acquire(self, policy_id: str, max_per_minute: int) -> bool:
            return False

    store = make_store(tmp_path, monkeypatch)
    pipe = CapturePipeline(store, rate_limiter=Never())
    assert await pipe.capture(_body(canary()), target(), event(), audit=AuditRecorder()) is None
    assert pipe.stats.capture_shed == 1
    assert store.index_backend.documents == {}


def test_pipeline_rejects_bad_capacity(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = make_store(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="queue_capacity"):
        CapturePipeline(store, queue_capacity=0)
    with pytest.raises(ValueError, match="shed_at_percent"):
        CapturePipeline(store, shed_at_percent=0)
