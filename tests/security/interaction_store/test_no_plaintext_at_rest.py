"""PRP-102 item 6, acceptance criteria 1 and 2: nothing readable rests outside the envelope.

Synthetic content carries several runtime canaries plus the placeholder that replaced a generated
credential-shaped value. After ``put`` every stored blob is scanned as bytes for each canary in
raw, UTF-8, UTF-16, hex, base64 and base64url form; the index documents carry no canary and no
content field; an envelope moved to another interaction fails with ``content_integrity_failed``.
"""

from __future__ import annotations

import base64
import hashlib
from pathlib import Path

import pytest
from neurosphere_core.cloud import CloudName
from neurosphere_core.crypto import (
    CONTENT_INTEGRITY_FAILED,
    Envelope,
    EnvelopeError,
    KeyVaultKeyWrapper,
    LocalFileKeyWrapper,
    open_envelope,
)
from neurosphere_core.crypto.envelope import ENVELOPE_MAGIC
from neurosphere_core.interactions import InMemoryInteractionStore
from neurosphere_core.interactions.settings import local_kek_placeholder
from neurosphere_core.interactions.store import content_aad

from ._harness import (
    CUSTOMER,
    DOMAIN,
    OTHER_DOMAIN,
    PLACEHOLDER,
    Corpus,
    FakeVault,
    SpyWrapper,
    TokenSpy,
    all_keys,
    build_corpus,
    canary,
    exception_text,
    found,
    index_dump,
    make_content,
    make_record,
    new_id,
    policy,
)

_CONTENT_KEYS = {
    "text",
    "texts",
    "content",
    "body",
    "plaintext",
    "prompt",
    "response",
    "parts_text",
}


def _store(kind: str, key_file: Path) -> tuple[InMemoryInteractionStore, SpyWrapper]:
    if kind == "local":
        spy = SpyWrapper(LocalFileKeyWrapper(key_file))
        kek_uri = local_kek_placeholder(CloudName.COMMERCIAL)
    else:
        vault = FakeVault()
        spy = SpyWrapper(
            KeyVaultKeyWrapper(
                vault.key_uri,
                cloud=CloudName.COMMERCIAL,
                token_provider=TokenSpy(),
                transport=vault.transport(),
                timeout_seconds=1.0,
            )
        )
        kek_uri = vault.key_uri
    return InMemoryInteractionStore(spy, kek_uri=kek_uri, policy=policy()), spy


async def _put_many(store: InMemoryInteractionStore, corpus: Corpus, count: int = 3) -> list[str]:
    ids = [new_id() for _ in range(count)]
    for iid in ids:
        await store.put(
            make_record(iid), make_content(iid, corpus.texts), capture_retention_days=30
        )
    return ids


def _plaintext_needles(corpus: Corpus) -> list[str]:
    return [*corpus.forbidden, *corpus.texts, PLACEHOLDER]


def test_encodings_positive_control() -> None:
    """The scanner finds a canary in every form it claims to cover, at every offset."""
    value = canary()
    raw = value.encode()
    for prefix in (b"", b"x", b"xy"):
        for wrapped in (
            prefix + raw + b"tail",
            base64.b64encode(prefix + raw + b"tail"),
            base64.urlsafe_b64encode(prefix + raw + b"tail"),
            prefix + value.encode("utf-16-le"),
            prefix + value.encode("utf-16-be"),
            prefix + raw.hex().encode(),
        ):
            assert found(wrapped, [value]), wrapped
    assert found(b"unrelated bytes " * 8, [value]) == []


@pytest.mark.parametrize("kind", ["local", "key_vault"])
async def test_blob_bytes_hold_no_canary_in_any_encoding(kind: str, key_file: Path) -> None:
    store, spy = _store(kind, key_file)
    corpus = build_corpus()
    ids = await _put_many(store, corpus)

    blobs = store.content_backend.blobs
    assert len(blobs) == len(ids)
    needles = _plaintext_needles(corpus)
    for name, data in blobs.items():
        assert data.startswith(ENVELOPE_MAGIC)
        assert found(data, needles) == [], name
        # The blob name is derived from ids and the capture time, never from content.
        assert found(name.encode(), needles) == []
        # The data key never rests in the envelope next to its ciphertext.
        assert found(data, spy.data_keys) == []
    assert found(b"".join(blobs.values()), needles) == []

    # Positive control: the content is really there, sealed.
    for iid in ids:
        read = await store.read_content(CUSTOMER, DOMAIN, iid)
        assert tuple(part.text.root for part in read.parts) == corpus.texts


async def test_index_documents_hold_no_canary_and_no_content_field(spy: SpyWrapper) -> None:
    store = InMemoryInteractionStore(
        spy, kek_uri=local_kek_placeholder(CloudName.COMMERCIAL), policy=policy()
    )
    corpus = build_corpus()
    await _put_many(store, corpus)

    documents = store.index_backend.documents
    dump = index_dump(documents)
    assert found(dump.encode("utf-8"), _plaintext_needles(corpus)) == []
    # No plaintext hash either: neither a part text nor the whole text is fingerprinted.
    for text in (*corpus.texts, "".join(corpus.texts)):
        assert hashlib.sha256(text.encode()).hexdigest() not in dump
    assert all_keys(list(documents.values())) & _CONTENT_KEYS == set()
    for doc in documents.values():
        assert set(doc["content_ref"]) == {
            "pointer",
            "kek_uri",
            "algorithm",
            "ciphertext_sha256",
            "byte_length",
        }
        for part in doc["parts"]:
            assert set(part) <= {"part", "char_count", "truncated"}


@pytest.mark.parametrize("destination", ["other_interaction", "same_id_other_domain"])
async def test_envelope_moved_to_another_interaction_fails_integrity(
    spy: SpyWrapper, destination: str
) -> None:
    store = InMemoryInteractionStore(
        spy, kek_uri=local_kek_placeholder(CloudName.COMMERCIAL), policy=policy()
    )
    corpus = build_corpus()
    source = new_id()
    await store.put(
        make_record(source), make_content(source, corpus.texts), capture_retention_days=30
    )
    if destination == "other_interaction":
        target_id, target_domain = new_id(), DOMAIN
    else:
        target_id, target_domain = source, OTHER_DOMAIN
    target = await store.put(
        make_record(target_id, domain_id=target_domain),
        make_content(target_id, ["decoy " + canary()]),
        capture_retention_days=30,
    )
    source_record = await store.get_metadata(CUSTOMER, DOMAIN, source)
    assert source_record is not None and source_record.content_ref is not None
    assert target.content_ref is not None
    moved = store.content_backend.blobs[source_record.content_ref.pointer]

    # Overwrite the target's blob with the source envelope and make the index agree with it,
    # so only the AAD binding (customer, domain, interaction id) stands in the way.
    store.content_backend.blobs[target.content_ref.pointer] = moved
    ref = store.index_backend.documents[(CUSTOMER, target_domain, target_id)]["content_ref"]
    ref["byte_length"] = len(moved)
    ref["ciphertext_sha256"] = hashlib.sha256(moved).hexdigest()

    with pytest.raises(EnvelopeError) as caught:
        await store.read_content(CUSTOMER, target_domain, target_id)
    assert caught.value.reason == CONTENT_INTEGRITY_FAILED
    assert found(exception_text(caught.value).encode(), _plaintext_needles(corpus)) == []

    # The same envelope opened directly under the destination's AAD fails the same way.
    with pytest.raises(EnvelopeError) as direct:
        await open_envelope(
            Envelope.from_bytes(moved), content_aad(CUSTOMER, target_domain, target_id), spy
        )
    assert direct.value.reason == CONTENT_INTEGRITY_FAILED

    # The source is untouched and still opens under its own binding.
    read = await store.read_content(CUSTOMER, DOMAIN, source)
    assert tuple(part.text.root for part in read.parts) == corpus.texts
