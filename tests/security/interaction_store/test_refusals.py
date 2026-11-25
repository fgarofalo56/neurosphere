"""PRP-102 item 6, acceptance criteria 1 and 2: every refused write writes nothing.

Retention off (no policy, opt-in false, no ``interaction_content`` rule) is
``content_retention_not_enabled``; text matching any ``secret_free_text`` ``not`` family (built
from fragments at runtime) is ``content_not_secret_free``; a ``redaction_state`` other than
``redacted`` or ``not_required`` (via ``model_construct`` or a plain dict) and a ``str`` or
``bytes`` body are refused. In every case nothing reaches either backend, the key wrapper's
``wrap`` is never called and the refusal is counted (in-process tally and the OTel counter).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

import pytest
from neurosphere_contracts.interactions.v1.redacted_content import RedactedContent
from neurosphere_core.cloud import CloudName
from neurosphere_core.crypto import KEY_HOST_REFUSED, EnvelopeError
from neurosphere_core.interactions import (
    InMemoryInteractionStore,
    InteractionStoreError,
    content_writes_enabled,
    validate_redacted_content,
)
from neurosphere_core.interactions.settings import local_kek_placeholder
from neurosphere_core.lifecycle.policy import UNSET, PolicyState, load_policy
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from ._harness import (
    GOVERNMENT_SUFFIX,
    SpyWrapper,
    build_corpus,
    canary,
    content_doc,
    exception_text,
    found,
    make_content,
    make_record,
    new_id,
    policy,
    refusal_points,
    secret_shaped_texts,
)

_RETENTION_OFF: dict[str, Callable[[], PolicyState]] = {
    "no_policy": lambda: UNSET,
    "invalid_policy": lambda: load_policy({"policy_version": "v1", "rules": []}),
    "opt_in_false": lambda: policy(opt_in=False),
    "no_interaction_content_rule": lambda: policy(rule=False),
}
_FAMILIES = sorted(secret_shaped_texts())


def _store(
    spy: SpyWrapper, state: PolicyState | None = None, *, kek_uri: str | None = None
) -> tuple[InMemoryInteractionStore, InMemoryMetricReader]:
    reader = InMemoryMetricReader()
    meter = MeterProvider(metric_readers=[reader]).get_meter("security-test")
    store = InMemoryInteractionStore(
        spy,
        kek_uri=kek_uri or local_kek_placeholder(CloudName.COMMERCIAL),
        policy=state if state is not None else policy(),
        meter=meter,
    )
    return store, reader


async def _assert_refused(
    store: InMemoryInteractionStore,
    reader: InMemoryMetricReader,
    spy: SpyWrapper,
    reason: str,
    record: Any,
    content: Any,
    secrets: list[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.DEBUG):
        with pytest.raises((InteractionStoreError, EnvelopeError)) as caught:
            await store.put(record, content, capture_retention_days=30)
    assert caught.value.reason == reason  # type: ignore[union-attr]
    assert str(caught.value) == reason
    assert store.content_backend.blobs == {}
    assert store.index_backend.documents == {}
    assert spy.wrap_calls == 0
    assert spy.data_keys == []
    assert store.refusals == {reason: 1}
    assert refusal_points(reader) == {reason: 1}
    leaks = (exception_text(caught.value) + caplog.text).encode()
    assert found(leaks, secrets) == []


@pytest.mark.parametrize("case", sorted(_RETENTION_OFF))
async def test_retention_off_refuses_before_any_write(
    spy: SpyWrapper, case: str, caplog: pytest.LogCaptureFixture
) -> None:
    state = _RETENTION_OFF[case]()
    assert content_writes_enabled(state) is False
    store, reader = _store(spy, state)
    corpus = build_corpus()
    iid = new_id()
    await _assert_refused(
        store,
        reader,
        spy,
        "content_retention_not_enabled",
        make_record(iid),
        make_content(iid, corpus.texts),
        [*corpus.forbidden, *corpus.texts],
        caplog,
    )


@pytest.mark.parametrize("family", _FAMILIES)
async def test_text_that_is_not_secret_free_is_refused(
    spy: SpyWrapper, family: str, caplog: pytest.LogCaptureFixture
) -> None:
    value = secret_shaped_texts()[family]
    text = "context " + canary() + " then " + value + " end"
    iid = new_id()
    # Pydantic ignores the schema's `not` patterns (ADR-0004), so the model accepts it ...
    content = make_content(iid, ["clean " + canary(), text])
    # ... and the store's JSON Schema check is what refuses it.
    with pytest.raises(InteractionStoreError) as direct:
        validate_redacted_content(content.model_dump(mode="json"))
    assert direct.value.reason == "content_not_secret_free"
    store, reader = _store(spy)
    await _assert_refused(
        store,
        reader,
        spy,
        "content_not_secret_free",
        make_record(iid),
        content,
        [value, text],
        caplog,
    )


def _constructed(iid: str, texts: tuple[str, ...], state: str) -> RedactedContent:
    return RedactedContent.model_construct(**{**content_doc(iid, texts), "redaction_state": state})


@pytest.mark.parametrize(
    ("label", "build"),
    [
        ("model_construct_redaction_failed", lambda i, t: _constructed(i, t, "redaction_failed")),
        ("model_construct_pending", lambda i, t: _constructed(i, t, "pending")),
        ("model_construct_empty", lambda i, t: _constructed(i, t, "")),
        ("model_construct_upper", lambda i, t: _constructed(i, t, "REDACTED")),
        ("dict_redaction_failed", lambda i, t: content_doc(i, t, state="redaction_failed")),
        ("dict_redacted", lambda i, t: content_doc(i, t)),
        ("str_body", lambda i, t: t[0]),
        ("bytes_body", lambda i, t: t[0].encode()),
        ("bytearray_body", lambda i, t: bytearray(t[0].encode())),
        ("none_body", lambda i, t: None),
    ],
)
async def test_non_redacted_or_raw_content_is_refused(
    spy: SpyWrapper,
    label: str,
    build: Callable[[str, tuple[str, ...]], Any],
    caplog: pytest.LogCaptureFixture,
) -> None:
    corpus = build_corpus()
    iid = new_id()
    record = make_record(iid, redaction_state="redaction_failed")
    if label == "dict_redacted":
        record = make_record(iid)
    store, reader = _store(spy)
    await _assert_refused(
        store,
        reader,
        spy,
        "content_not_secret_free",
        record,
        build(iid, corpus.texts),
        [*corpus.forbidden, *corpus.texts],
        caplog,
    )


def test_validator_refuses_every_state_but_redacted_and_not_required() -> None:
    iid = new_id()
    for state in ("redaction_failed", "pending", "", "REDACTED", "none"):
        with pytest.raises(InteractionStoreError) as caught:
            validate_redacted_content(content_doc(iid, ["hello"], state=state))
        assert caught.value.reason == "content_not_secret_free"
    for state in ("redacted", "not_required"):
        assert validate_redacted_content(content_doc(iid, ["hello"], state=state))


async def test_record_marked_redaction_failed_is_refused(
    spy: SpyWrapper, caplog: pytest.LogCaptureFixture
) -> None:
    """Valid redacted content cannot be stored under a record whose redaction failed."""
    corpus = build_corpus()
    iid = new_id()
    store, reader = _store(spy)
    await _assert_refused(
        store,
        reader,
        spy,
        "content_record_mismatch",
        make_record(iid, redaction_state="redaction_failed"),
        make_content(iid, corpus.texts),
        [*corpus.forbidden, *corpus.texts],
        caplog,
    )


async def test_vault_on_another_cloud_refuses_the_write(
    spy: SpyWrapper, caplog: pytest.LogCaptureFixture
) -> None:
    corpus = build_corpus()
    iid = new_id()
    store, reader = _store(
        spy, kek_uri="https://nsvgov" + new_id()[:8] + GOVERNMENT_SUFFIX + "/keys/ns-kek"
    )
    await _assert_refused(
        store,
        reader,
        spy,
        KEY_HOST_REFUSED,
        make_record(iid),
        make_content(iid, corpus.texts),
        [*corpus.forbidden, *corpus.texts],
        caplog,
    )
