"""PRP-102 item 3: envelope sealing, opening, tamper detection and strict parsing."""

from __future__ import annotations

import dataclasses
import struct
from pathlib import Path

import pytest
from neurosphere_core.cloud import Settings
from neurosphere_core.crypto import (
    CONTENT_INTEGRITY_FAILED,
    KEY_WRAP_UNAVAILABLE,
    Envelope,
    EnvelopeError,
    KeyWrapper,
    LocalFileKeyWrapper,
    WrappedKey,
    canonical_aad,
    open_envelope,
    seal,
)

CANARY = "NS-CANARY-7f3a-interaction-body"
PLAINTEXT = f"user asked about {CANARY} and the model answered".encode()
AAD = canonical_aad({"customer_id": "cust-1", "domain_id": "dom-1", "interaction_id": "int-1"})


@pytest.fixture
def wrapper(tmp_path: Path) -> LocalFileKeyWrapper:
    return LocalFileKeyWrapper(tmp_path / "kek.bin", settings=Settings(env="local"))


def _flip(data: bytes, index: int) -> bytes:
    mutable = bytearray(data)
    mutable[index] ^= 0x01
    return bytes(mutable)


async def _expect_integrity(envelope: Envelope, aad: bytes, wrapper: KeyWrapper) -> None:
    with pytest.raises(EnvelopeError) as caught:
        await open_envelope(envelope, aad, wrapper)
    assert caught.value.reason == CONTENT_INTEGRITY_FAILED
    assert str(caught.value) == CONTENT_INTEGRITY_FAILED
    assert caught.value.__cause__ is None


async def test_round_trip(wrapper: LocalFileKeyWrapper) -> None:
    envelope = await seal(PLAINTEXT, AAD, wrapper)
    assert envelope.format_version == 1
    assert envelope.key_id == wrapper.key_id
    assert len(envelope.nonce) == 12
    assert len(envelope.ciphertext) == len(PLAINTEXT) + 16
    assert await open_envelope(envelope, AAD, wrapper) == PLAINTEXT
    parsed = Envelope.from_bytes(envelope.to_bytes())
    assert parsed == envelope
    assert await open_envelope(parsed, AAD, wrapper) == PLAINTEXT


async def test_empty_plaintext_round_trips(wrapper: LocalFileKeyWrapper) -> None:
    envelope = await seal(b"", AAD, wrapper)
    assert await open_envelope(Envelope.from_bytes(envelope.to_bytes()), AAD, wrapper) == b""


async def test_two_seals_are_distinct(wrapper: LocalFileKeyWrapper) -> None:
    first = await seal(PLAINTEXT, AAD, wrapper)
    second = await seal(PLAINTEXT, AAD, wrapper)
    assert first.nonce != second.nonce
    assert first.wrapped_key != second.wrapped_key
    assert first.ciphertext != second.ciphertext
    # Distinct data keys, not just distinct wrapping nonces.
    first_key = await wrapper.unwrap(
        WrappedKey(first.key_id, first.wrap_algorithm, first.wrapped_key)
    )
    second_key = await wrapper.unwrap(
        WrappedKey(second.key_id, second.wrap_algorithm, second.wrapped_key)
    )
    assert first_key != second_key
    assert len(first_key) == 32


async def test_envelope_bytes_hold_no_plaintext(wrapper: LocalFileKeyWrapper) -> None:
    import hashlib

    blob = (await seal(PLAINTEXT, AAD, wrapper)).to_bytes()
    assert CANARY.encode() not in blob
    assert PLAINTEXT not in blob
    assert hashlib.sha256(PLAINTEXT).digest() not in blob
    assert hashlib.sha256(PLAINTEXT).hexdigest().encode() not in blob
    assert blob.startswith(b"NSEV\x01")


@pytest.mark.parametrize("part", ["ciphertext", "tag", "nonce"])
async def test_tampered_body_fails(wrapper: LocalFileKeyWrapper, part: str) -> None:
    envelope = await seal(PLAINTEXT, AAD, wrapper)
    if part == "ciphertext":
        tampered = dataclasses.replace(envelope, ciphertext=_flip(envelope.ciphertext, 0))
    elif part == "tag":
        tampered = dataclasses.replace(envelope, ciphertext=_flip(envelope.ciphertext, -1))
    else:
        tampered = dataclasses.replace(envelope, nonce=_flip(envelope.nonce, 5))
    await _expect_integrity(tampered, AAD, wrapper)


async def test_tampered_aad_fails(wrapper: LocalFileKeyWrapper) -> None:
    envelope = await seal(PLAINTEXT, AAD, wrapper)
    moved = canonical_aad(
        {"customer_id": "cust-1", "domain_id": "dom-1", "interaction_id": "int-2"}
    )
    await _expect_integrity(envelope, moved, wrapper)
    await _expect_integrity(envelope, b"", wrapper)


class _LenientWrapper:
    """Unwraps whatever it is given, so only the AEAD header binding can catch a changed header."""

    def __init__(self) -> None:
        self.keys: dict[bytes, bytes] = {}

    @property
    def key_id(self) -> str:
        return "test:kek/1"

    async def wrap(self, data_key: bytes) -> WrappedKey:
        handle = bytes(range(len(self.keys) + 1))
        self.keys[handle] = data_key
        return WrappedKey(key_id=self.key_id, algorithm="test-wrap", value=handle)

    async def unwrap(self, wrapped: WrappedKey) -> bytes:
        return self.keys[wrapped.value]


@pytest.mark.parametrize(
    "change",
    [{"key_id": "test:kek/2"}, {"wrap_algorithm": "test-wrap-b"}, {"format_version": 2}],
)
async def test_header_fields_are_bound(change: dict[str, object]) -> None:
    lenient = _LenientWrapper()
    envelope = await seal(PLAINTEXT, AAD, lenient)
    assert await open_envelope(envelope, AAD, lenient) == PLAINTEXT
    await _expect_integrity(dataclasses.replace(envelope, **change), AAD, lenient)


async def test_tampered_key_id_and_algorithm_fail_with_local_wrapper(
    wrapper: LocalFileKeyWrapper,
) -> None:
    envelope = await seal(PLAINTEXT, AAD, wrapper)
    await _expect_integrity(
        dataclasses.replace(envelope, key_id="local:0000000000000000"), AAD, wrapper
    )
    await _expect_integrity(
        dataclasses.replace(envelope, wrap_algorithm="RSA-OAEP-256"), AAD, wrapper
    )
    await _expect_integrity(
        dataclasses.replace(envelope, wrapped_key=_flip(envelope.wrapped_key, 20)), AAD, wrapper
    )


async def test_tampered_format_version_byte_is_refused(wrapper: LocalFileKeyWrapper) -> None:
    blob = bytearray((await seal(PLAINTEXT, AAD, wrapper)).to_bytes())
    blob[4] = 2
    with pytest.raises(EnvelopeError, match=f"^{CONTENT_INTEGRITY_FAILED}$"):
        Envelope.from_bytes(bytes(blob))


async def test_unwrap_failure_maps_to_unavailable() -> None:
    class Broken(_LenientWrapper):
        async def unwrap(self, wrapped: WrappedKey) -> bytes:
            raise ConnectionError("https://secret-host.example/keys/name")

        async def wrap(self, data_key: bytes) -> WrappedKey:
            raise ConnectionError("https://secret-host.example/keys/name")

    broken = Broken()
    with pytest.raises(EnvelopeError) as caught:
        await seal(PLAINTEXT, AAD, broken)
    assert str(caught.value) == KEY_WRAP_UNAVAILABLE
    assert caught.value.__cause__ is None
    assert caught.value.__suppress_context__
    lenient = _LenientWrapper()
    envelope = await seal(PLAINTEXT, AAD, lenient)
    with pytest.raises(EnvelopeError) as caught:
        await open_envelope(envelope, AAD, broken)
    assert str(caught.value) == KEY_WRAP_UNAVAILABLE


async def test_wrong_length_data_key_is_integrity_failure() -> None:
    class Short(_LenientWrapper):
        async def unwrap(self, wrapped: WrappedKey) -> bytes:
            return b"\x00" * 16

    short = Short()
    envelope = await seal(PLAINTEXT, AAD, short)
    await _expect_integrity(envelope, AAD, short)


async def _valid_blob(wrapper: LocalFileKeyWrapper) -> bytes:
    return (await seal(PLAINTEXT, AAD, wrapper)).to_bytes()


async def test_malformed_envelopes_are_refused(wrapper: LocalFileKeyWrapper) -> None:
    blob = await _valid_blob(wrapper)
    key_id_len = struct.unpack(">H", blob[5:7])[0]
    alg_at = 7 + key_id_len
    alg_len = blob[alg_at]
    wrapped_at = alg_at + 1 + alg_len
    wrapped_len = struct.unpack(">H", blob[wrapped_at : wrapped_at + 2])[0]
    nonce_at = wrapped_at + 2 + wrapped_len
    assert blob[nonce_at] == 12
    bad_nonce = blob[:nonce_at] + b"\x0b" + blob[nonce_at + 1 :]
    cases = [
        b"",
        b"NSEV",
        b"XXXX" + blob[4:],
        blob + b"\x00",
        blob[:-1],
        blob[: len(blob) // 2],
        blob[:5] + b"\xff\xff" + blob[7:],
        bad_nonce,
        blob[:5] + b"\x00\x00" + blob[7:],
    ]
    for case in cases:
        with pytest.raises(EnvelopeError) as caught:
            Envelope.from_bytes(case)
        assert str(caught.value) == CONTENT_INTEGRITY_FAILED
    # Every possible truncation is refused, none crashes with another exception type.
    for cut in range(len(blob)):
        with pytest.raises(EnvelopeError):
            Envelope.from_bytes(blob[:cut])


def test_envelope_construction_is_validated() -> None:
    good = {
        "format_version": 1,
        "key_id": "local:abc",
        "wrap_algorithm": "local-a256gcm",
        "wrapped_key": b"\x01" * 40,
        "nonce": b"\x00" * 12,
        "ciphertext": b"\x00" * 16,
    }
    Envelope(**good)  # type: ignore[arg-type]
    for change in (
        {"nonce": b"\x00" * 11},
        {"ciphertext": b"\x00" * 15},
        {"key_id": ""},
        {"key_id": "bad\nid"},
        {"wrapped_key": b""},
        {"format_version": 256},
    ):
        with pytest.raises(EnvelopeError, match=f"^{CONTENT_INTEGRITY_FAILED}$"):
            Envelope(**{**good, **change})  # type: ignore[arg-type]
    with pytest.raises(EnvelopeError):
        Envelope(**{**good, "format_version": 2}).to_bytes()  # type: ignore[arg-type]


def test_canonical_aad_is_deterministic_and_unambiguous() -> None:
    a = canonical_aad({"b": "2", "a": "1"})
    assert a == canonical_aad({"a": "1", "b": "2"})
    assert canonical_aad({"a": "bc"}) != canonical_aad({"ab": "c"})
    assert canonical_aad({"a": "1", "b": ""}) != canonical_aad({"a": "1"})
    assert canonical_aad({}) != canonical_aad({"": ""})
    with pytest.raises(TypeError):
        canonical_aad({"a": 1})  # type: ignore[dict-item]
