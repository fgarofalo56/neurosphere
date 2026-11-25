"""PRP-102 item 4: encrypted interaction content plus a metadata-only index."""

from __future__ import annotations

import hashlib
import inspect
import json
import logging
from typing import Any

import pytest
from neurosphere_contracts.interactions.v1.interaction_record import InteractionRecord
from neurosphere_contracts.interactions.v1.redacted_content import RedactedContent
from neurosphere_core.cloud import CloudName, Settings
from neurosphere_core.crypto import CONTENT_INTEGRITY_FAILED, Envelope, EnvelopeError
from neurosphere_core.interactions import (
    BlobInteractionContent,
    InMemoryInteractionStore,
    InteractionStore,
    InteractionStoreError,
    content_blob_name,
    parse_content_blob_name,
    validate_redacted_content,
)
from neurosphere_core.interactions.store import EncryptedInteractionStore

from ._support import (
    CUSTOMER,
    DOMAIN,
    GOV_KEK_URI,
    KEK_URI,
    OTHER_DOMAIN,
    FakeKeyWrapper,
    at,
    canary,
    content_doc,
    make_content,
    make_record,
    new_id,
    policy,
    secret_shaped_texts,
)


def _assert_nothing_written(store: InMemoryInteractionStore) -> None:
    assert store.index_backend.documents == {}
    assert store.content_backend.blobs == {}


def _only_doc(store: InMemoryInteractionStore) -> dict[str, Any]:
    (doc,) = store.index_backend.documents.values()
    return doc


async def test_put_then_read_round_trips(store: InMemoryInteractionStore) -> None:
    iid = new_id()
    content = make_content(iid, "prompt text", "response text")
    stored = await store.put(make_record(iid), content, capture_retention_days=30)
    assert await store.read_content(CUSTOMER, DOMAIN, iid) == content
    assert await store.get_metadata(CUSTOMER, DOMAIN, iid) == stored
    assert isinstance(store, InteractionStore)


async def test_blob_is_an_envelope_with_no_canary(store: InMemoryInteractionStore) -> None:
    secrets = [canary() for _ in range(3)]
    iid = new_id()
    await store.put(
        make_record(iid),
        make_content(iid, f"say {secrets[0]}", f"reply {secrets[1]}", secrets[2]),
        capture_retention_days=30,
    )
    (blob,) = store.content_backend.blobs.values()
    assert blob.startswith(b"NSEV")
    Envelope.from_bytes(blob)  # strict parse: a versioned envelope and nothing else
    index_text = json.dumps(list(store.index_backend.documents.values()))
    for value in secrets:
        for encoded in (value.encode("utf-8"), value.encode("utf-16-le")):
            assert encoded not in blob
        assert value not in index_text


async def test_index_document_is_metadata_only_interaction_record(
    store: InMemoryInteractionStore,
) -> None:
    iid = new_id()
    await store.put(make_record(iid), make_content(iid), capture_retention_days=30)
    doc = _only_doc(store)
    assert doc["id"] == iid
    body = {k: v for k, v in doc.items() if k != "id"}
    record = InteractionRecord.model_validate(body)
    assert set(body) <= set(InteractionRecord.model_fields)
    assert '"text":' not in json.dumps(body)
    ref = record.content_ref
    assert ref is not None
    (name, blob) = next(iter(store.content_backend.blobs.items()))
    assert ref.pointer == name == content_blob_name(CUSTOMER, DOMAIN, at(doc["captured_at"]), iid)
    assert ref.kek_uri == KEK_URI
    assert ref.algorithm == "aes_256_gcm"
    assert ref.ciphertext_sha256 == hashlib.sha256(blob).hexdigest()
    assert ref.byte_length == len(blob)


async def test_envelope_copied_to_another_interaction_fails_integrity(
    store: InMemoryInteractionStore,
) -> None:
    first, second = new_id(), new_id()
    await store.put(make_record(first), make_content(first), capture_retention_days=30)
    await store.put(make_record(second), make_content(second), capture_retention_days=30)
    first_ref = (await store.get_metadata(CUSTOMER, DOMAIN, first)).content_ref  # type: ignore[union-attr]
    second_doc = store.index_backend.documents[(CUSTOMER, DOMAIN, second)]
    assert first_ref is not None
    copied = store.content_backend.blobs[first_ref.pointer]
    # Copy the blob AND make the index agree, so only the AAD binding can catch it.
    store.content_backend.blobs[second_doc["content_ref"]["pointer"]] = copied
    second_doc["content_ref"]["ciphertext_sha256"] = hashlib.sha256(copied).hexdigest()
    second_doc["content_ref"]["byte_length"] = len(copied)
    with pytest.raises(EnvelopeError) as caught:
        await store.read_content(CUSTOMER, DOMAIN, second)
    assert caught.value.reason == CONTENT_INTEGRITY_FAILED


@pytest.mark.parametrize("tamper", ["sha", "length", "blob_byte", "pointer"])
async def test_tampering_fails_integrity_before_decrypt(
    store: InMemoryInteractionStore, tamper: str
) -> None:
    iid = new_id()
    await store.put(make_record(iid), make_content(iid), capture_retention_days=30)
    doc = _only_doc(store)
    ref = doc["content_ref"]
    if tamper == "sha":
        ref["ciphertext_sha256"] = "0" * 64
    elif tamper == "length":
        ref["byte_length"] += 1
    elif tamper == "blob_byte":
        blob = bytearray(store.content_backend.blobs[ref["pointer"]])
        blob[-1] ^= 0x01
        store.content_backend.blobs[ref["pointer"]] = bytes(blob)
    else:
        other = content_blob_name(CUSTOMER, DOMAIN, at("2026-01-01T00:00:00Z"), iid)
        store.content_backend.blobs[other] = store.content_backend.blobs[ref["pointer"]]
        ref["pointer"] = other
    with pytest.raises(EnvelopeError) as caught:
        await store.read_content(CUSTOMER, DOMAIN, iid)
    assert str(caught.value) == CONTENT_INTEGRITY_FAILED


@pytest.mark.parametrize("state", ["redaction_failed", "pending", "unknown"])
async def test_unstorable_redaction_state_is_refused(
    store: InMemoryInteractionStore, state: str
) -> None:
    iid = new_id()
    content = RedactedContent.model_construct(**{**content_doc(iid), "redaction_state": state})
    with pytest.raises(InteractionStoreError) as caught:
        await store.put(make_record(iid), content, capture_retention_days=30)
    assert caught.value.reason == "content_not_secret_free"
    _assert_nothing_written(store)


def test_validate_refuses_unstorable_state_document() -> None:
    with pytest.raises(InteractionStoreError):
        validate_redacted_content(content_doc(new_id(), state="redaction_failed"))


@pytest.mark.parametrize("kind", sorted(secret_shaped_texts()))
async def test_secret_shaped_text_is_refused_with_no_value_in_error(
    store: InMemoryInteractionStore, kind: str, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    value = secret_shaped_texts()[kind]
    iid = new_id()
    # Pydantic ignores `not`, so this constructs; only the JSON Schema check refuses it.
    content = make_content(iid, f"before {value} after")
    with pytest.raises(InteractionStoreError) as caught:
        await store.put(make_record(iid), content, capture_retention_days=30)
    assert str(caught.value) == "content_not_secret_free"
    assert caught.value.__cause__ is None
    assert value not in caplog.text
    _assert_nothing_written(store)
    assert store.refusals["content_not_secret_free"] == 1


@pytest.mark.parametrize("bad", ["plain text", b"raw bytes", {"interaction_id": "x"}, None])
async def test_put_takes_only_redacted_content(store: InMemoryInteractionStore, bad: Any) -> None:
    iid = new_id()
    with pytest.raises(InteractionStoreError) as caught:
        await store.put(make_record(iid), bad, capture_retention_days=30)
    assert caught.value.reason == "content_not_secret_free"
    _assert_nothing_written(store)


def test_no_public_write_method_takes_str_or_bytes() -> None:
    for name, member in inspect.getmembers(EncryptedInteractionStore, inspect.isfunction):
        if name.startswith("_"):
            continue
        hints = inspect.get_annotations(member)
        for param, annotation in hints.items():
            if param == "return":
                continue
            assert annotation not in {"str | bytes", "bytes", "bytes | str"}, (name, param)
    assert inspect.get_annotations(EncryptedInteractionStore.put)["content"] == "RedactedContent"


@pytest.mark.parametrize(
    "overrides",
    [
        {"record_id": "00000000-0000-4000-8000-000000000000"},
        {"redaction_state": "not_required"},
        {"redaction_state": "redaction_failed"},
        {"detector_set_version": "detectors-2.0"},
    ],
)
async def test_record_and_content_must_agree(
    store: InMemoryInteractionStore, overrides: dict[str, str]
) -> None:
    iid = new_id()
    fields = dict(overrides)
    record = make_record(fields.pop("record_id", iid), **fields)
    with pytest.raises(InteractionStoreError) as caught:
        await store.put(record, make_content(iid), capture_retention_days=30)
    assert caught.value.reason == "content_record_mismatch"
    _assert_nothing_written(store)


async def test_vault_on_another_cloud_is_refused(local_wrapper: Any) -> None:
    store = InMemoryInteractionStore(local_wrapper, kek_uri=GOV_KEK_URI, policy=policy())
    iid = new_id()
    with pytest.raises(EnvelopeError) as caught:
        await store.put(make_record(iid), make_content(iid), capture_retention_days=30)
    assert caught.value.reason == "key_host_refused"
    _assert_nothing_written(store)


async def test_duplicate_put_is_refused_and_keeps_the_original(
    store: InMemoryInteractionStore,
) -> None:
    iid = new_id()
    await store.put(make_record(iid), make_content(iid, "first"), capture_retention_days=30)
    before_blobs = dict(store.content_backend.blobs)
    before_docs = json.dumps(list(store.index_backend.documents.values()))
    with pytest.raises(InteractionStoreError) as caught:
        await store.put(make_record(iid), make_content(iid, "second"), capture_retention_days=30)
    assert caught.value.reason == "interaction_exists"
    assert store.content_backend.blobs == before_blobs
    assert json.dumps(list(store.index_backend.documents.values())) == before_docs
    assert (await store.read_content(CUSTOMER, DOMAIN, iid)).parts[0].text.root == "first"


async def test_duplicate_after_partial_purge_leaves_no_orphan_blob(
    store: InMemoryInteractionStore,
) -> None:
    iid = new_id()
    await store.put(make_record(iid), make_content(iid), capture_retention_days=30)
    store.content_backend.blobs.clear()  # interrupted purge: blob gone, index left
    with pytest.raises(InteractionStoreError) as caught:
        await store.put(make_record(iid), make_content(iid), capture_retention_days=30)
    assert caught.value.reason == "interaction_exists"
    assert store.content_backend.blobs == {}


async def test_index_failure_removes_the_blob(local_wrapper: Any) -> None:
    store = InMemoryInteractionStore(local_wrapper, kek_uri=KEK_URI, policy=policy())

    async def failing_create(record: InteractionRecord) -> None:
        raise InteractionStoreError("interaction_store_unavailable")

    store.index_backend.create = failing_create  # type: ignore[method-assign]
    iid = new_id()
    with pytest.raises(InteractionStoreError) as caught:
        await store.put(make_record(iid), make_content(iid), capture_retention_days=30)
    assert caught.value.reason == "interaction_store_unavailable"
    _assert_nothing_written(store)
    assert store.orphan_cleanups["removed"] == 1


async def test_create_that_committed_despite_an_error_keeps_the_blob(local_wrapper: Any) -> None:
    store = InMemoryInteractionStore(local_wrapper, kek_uri=KEK_URI, policy=policy())
    real_create = store.index_backend.create

    async def committed_then_timed_out(record: InteractionRecord) -> None:
        await real_create(record)
        raise InteractionStoreError("interaction_store_unavailable")

    store.index_backend.create = committed_then_timed_out  # type: ignore[method-assign]
    iid = new_id()
    stored = await store.put(make_record(iid), make_content(iid), capture_retention_days=30)
    assert stored.interaction_id.root == iid
    assert store.orphan_cleanups["removed"] == 0
    assert (await store.read_content(CUSTOMER, DOMAIN, iid)).interaction_id.root == iid


async def test_unreadable_index_after_failed_create_keeps_the_blob(local_wrapper: Any) -> None:
    store = InMemoryInteractionStore(local_wrapper, kek_uri=KEK_URI, policy=policy())
    real_get = store.index_backend.get
    calls = {"get": 0}

    async def failing_create(record: InteractionRecord) -> None:
        raise InteractionStoreError("interaction_store_unavailable")

    async def get_then_fail(*args: Any) -> InteractionRecord | None:
        calls["get"] += 1
        if calls["get"] > 1:
            raise InteractionStoreError("interaction_store_unavailable")
        return await real_get(*args)

    store.index_backend.create = failing_create  # type: ignore[method-assign]
    store.index_backend.get = get_then_fail  # type: ignore[method-assign]
    iid = new_id()
    with pytest.raises(InteractionStoreError):
        await store.put(make_record(iid), make_content(iid), capture_retention_days=30)
    assert len(store.content_backend.blobs) == 1
    assert store.orphan_cleanups["kept"] == 1


async def test_delete_ignores_a_corrupted_pointer(store: InMemoryInteractionStore) -> None:
    victim, target = new_id(), new_id()
    await store.put(make_record(victim), make_content(victim), capture_retention_days=30)
    await store.put(make_record(target), make_content(target), capture_retention_days=30)
    docs = store.index_backend.documents
    victim_pointer = next(
        d["content_ref"]["pointer"] for d in docs.values() if d["interaction_id"] == victim
    )
    target_doc = next(d for d in docs.values() if d["interaction_id"] == target)
    target_doc["content_ref"]["pointer"] = victim_pointer
    assert await store.delete(CUSTOMER, DOMAIN, target) is True
    assert (await store.read_content(CUSTOMER, DOMAIN, victim)).interaction_id.root == victim
    assert len(store.content_backend.blobs) == 1


async def test_read_after_interrupted_delete_is_content_purged_and_rerun_completes(
    store: InMemoryInteractionStore,
) -> None:
    iid = new_id()
    await store.put(make_record(iid), make_content(iid), capture_retention_days=30)
    ref = _only_doc(store)["content_ref"]
    assert await store.content_backend.delete(ref["pointer"])  # purge stopped after the blob
    with pytest.raises(InteractionStoreError) as caught:
        await store.read_content(CUSTOMER, DOMAIN, iid)
    assert caught.value.reason == "content_purged"
    assert await store.delete(CUSTOMER, DOMAIN, iid) is True
    _assert_nothing_written(store)
    assert await store.delete(CUSTOMER, DOMAIN, iid) is False


async def test_delete_removes_blob_and_index(store: InMemoryInteractionStore) -> None:
    iid = new_id()
    await store.put(make_record(iid), make_content(iid), capture_retention_days=30)
    assert await store.delete(CUSTOMER, DOMAIN, iid) is True
    _assert_nothing_written(store)
    with pytest.raises(InteractionStoreError) as caught:
        await store.read_content(CUSTOMER, DOMAIN, iid)
    assert caught.value.reason == "interaction_not_found"


async def test_fake_key_wrapper_and_distinct_ciphertexts() -> None:
    store = InMemoryInteractionStore(FakeKeyWrapper(), kek_uri=KEK_URI, policy=policy())
    first, second = new_id(), new_id()
    await store.put(make_record(first), make_content(first, "same"), capture_retention_days=5)
    await store.put(make_record(second), make_content(second, "same"), capture_retention_days=5)
    blobs = list(store.content_backend.blobs.values())
    assert len(set(blobs)) == 2
    assert (await store.read_content(CUSTOMER, DOMAIN, second)).parts[0].text.root == "same"


async def test_domain_with_slash_is_one_path_segment(store: InMemoryInteractionStore) -> None:
    iid = new_id()
    await store.put(
        make_record(iid, domain_id=OTHER_DOMAIN), make_content(iid), capture_retention_days=30
    )
    (name,) = store.content_backend.blobs
    assert name.count("/") == 5
    parsed = parse_content_blob_name(name)
    assert parsed is not None and parsed.domain_id == OTHER_DOMAIN
    assert (await store.read_content(CUSTOMER, OTHER_DOMAIN, iid)).interaction_id.root == iid


@pytest.mark.parametrize(
    "name",
    [
        "acme/commercial:acme:neurosphere:domain:support/2026/11/20/not-a-uuid.env",
        "../acme/commercial:acme:neurosphere:domain:support/2026/11/20/"
        + "5b0e8a3c-2f7d-4e19-8c61-0a9d3f7b2e44.env",
        "acme/commercial:acme:neurosphere:domain:sales/emea/2026/11/20/"
        + "5b0e8a3c-2f7d-4e19-8c61-0a9d3f7b2e44.env",
        "acme/commercial:acme:neurosphere:domain:support/2026/02/30/"
        + "5b0e8a3c-2f7d-4e19-8c61-0a9d3f7b2e44.env",
        "acme/commercial:acme:neurosphere:domain:support/2026/11/20/"
        + "5b0e8a3c-2f7d-4e19-8c61-0a9d3f7b2e44.json",
        "acme/commercial%3Aacme:neurosphere:domain:support/2026/11/20/"
        + "5b0e8a3c-2f7d-4e19-8c61-0a9d3f7b2e44.env",
        ".",
    ],
)
def test_blob_names_are_strict(name: str) -> None:
    assert parse_content_blob_name(name) is None


def test_blob_name_builder_refuses_bad_parts() -> None:
    when = at("2026-11-20T10:15:01Z")
    iid = new_id()
    for customer, domain, interaction in (
        ("..", DOMAIN, iid),
        ("Acme", DOMAIN, iid),
        (CUSTOMER, "support", iid),
        (CUSTOMER, DOMAIN, iid.upper()),
    ):
        with pytest.raises(ValueError):
            content_blob_name(customer, domain, when, interaction)


# --- BlobInteractionContent over a fake container ---------------------------------------------


class _FakeDownload:
    def __init__(self, data: bytes) -> None:
        self._data = data

    async def readall(self) -> bytes:
        return self._data


class _FakeContainer:
    def __init__(self, *, exists: bool) -> None:
        self.exists = exists
        self.blobs: dict[str, bytes] = {}
        self.created = 0

    def _missing(self) -> Exception:
        from azure.core.exceptions import ResourceNotFoundError

        exc = ResourceNotFoundError("missing")
        exc.error_code = "ContainerNotFound"  # type: ignore[attr-defined]
        return exc

    async def create_container(self, **kwargs: Any) -> Any:
        from azure.core.exceptions import ResourceExistsError

        if self.exists:
            raise ResourceExistsError("exists")
        self.exists = True
        self.created += 1

    async def upload_blob(
        self, name: str, data: bytes, *, overwrite: bool = False, **kw: Any
    ) -> Any:
        from azure.core.exceptions import ResourceExistsError

        if not self.exists:
            raise self._missing()
        if name in self.blobs and not overwrite:
            raise ResourceExistsError("exists")
        self.blobs[name] = data

    async def download_blob(self, blob: str, **kwargs: Any) -> _FakeDownload:
        from azure.core.exceptions import ResourceNotFoundError

        if not self.exists:
            raise self._missing()
        if blob not in self.blobs:
            raise ResourceNotFoundError("missing")
        return _FakeDownload(self.blobs[blob])

    async def delete_blob(self, blob: str, **kwargs: Any) -> None:
        from azure.core.exceptions import ResourceNotFoundError

        if not self.exists:
            raise self._missing()
        if blob not in self.blobs:
            raise ResourceNotFoundError("missing")
        del self.blobs[blob]


def _name() -> str:
    return content_blob_name(CUSTOMER, DOMAIN, at("2026-11-20T10:15:01Z"), new_id())


async def test_blob_backend_creates_container_only_under_local() -> None:
    container = _FakeContainer(exists=False)
    backend = BlobInteractionContent(container, settings=Settings(env="local"))
    name = _name()
    await backend.put(name, b"NSEV-bytes")
    assert container.created == 1
    assert await backend.get(name) == b"NSEV-bytes"
    with pytest.raises(InteractionStoreError) as caught:
        await backend.put(name, b"other")
    assert caught.value.reason == "interaction_exists"
    assert await backend.delete(name) is True
    assert await backend.delete(name) is False
    assert await backend.get(name) is None


async def test_blob_backend_never_creates_container_outside_local() -> None:
    container = _FakeContainer(exists=False)
    backend = BlobInteractionContent(
        container, settings=Settings(env="prod", cloud=CloudName.COMMERCIAL)
    )
    for call in (backend.put(_name(), b"x"), backend.get(_name()), backend.delete(_name())):
        with pytest.raises(InteractionStoreError) as caught:
            await call
        assert caught.value.reason == "content_container_missing"
    assert container.created == 0
    assert container.blobs == {}


async def test_blob_backend_refuses_names_it_did_not_build() -> None:
    backend = BlobInteractionContent(_FakeContainer(exists=True), settings=Settings(env="local"))
    with pytest.raises(ValueError):
        await backend.put("acme/../escape.env", b"x")


async def test_store_over_blob_backend_round_trips(local_wrapper: Any) -> None:
    from neurosphere_core.interactions import InMemoryInteractionIndex

    container = _FakeContainer(exists=True)
    store = EncryptedInteractionStore(
        InMemoryInteractionIndex(),
        BlobInteractionContent(container, settings=Settings(env="local")),
        local_wrapper,
        kek_uri=KEK_URI,
        policy=policy(),
    )
    iid = new_id()
    content = make_content(iid, canary())
    await store.put(make_record(iid), content, capture_retention_days=30)
    assert await store.read_content(CUSTOMER, DOMAIN, iid) == content
    assert await store.delete(CUSTOMER, DOMAIN, iid) is True
    assert container.blobs == {}
