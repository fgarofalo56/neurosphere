"""AES-256-GCM envelope encryption with a wrapped per-blob data key (PRP-102 item 3).

``seal`` draws a fresh 256-bit data key and a fresh random 96-bit nonce per call, wraps the data
key with a :class:`KeyWrapper` (Key Vault key or, under ``NS_ENV=local`` only, a local file key)
and encrypts with ``AESGCM``. The AEAD associated data is the caller's ``aad`` plus the envelope
header (format version, key id, wrap algorithm), so tampering with any header field, the nonce,
the ciphertext, the tag or the caller's bound fields fails to open with
``content_integrity_failed``. The data key is never stored on the envelope or logged.

Binary layout (big-endian, no trailing bytes)::

    b"NSEV" | u8 format_version | u16 len + key_id (ASCII) | u8 len + wrap_algorithm (ASCII)
    | u16 len + wrapped_key | u8 len (=12) + nonce | u32 len + ciphertext (tag appended)

The serialized envelope holds no plaintext and no plaintext hash.
"""

from __future__ import annotations

import os
import struct
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final, Protocol, runtime_checkable

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from neurosphere_core.crypto.errors import (
    CONTENT_INTEGRITY_FAILED,
    KEY_WRAP_UNAVAILABLE,
    EnvelopeError,
)

__all__ = [
    "DATA_KEY_BYTES",
    "ENVELOPE_FORMAT_VERSION",
    "ENVELOPE_MAGIC",
    "NONCE_BYTES",
    "TAG_BYTES",
    "Envelope",
    "KeyWrapper",
    "WrappedKey",
    "canonical_aad",
    "open_envelope",
    "seal",
]

ENVELOPE_MAGIC: Final = b"NSEV"
ENVELOPE_FORMAT_VERSION: Final = 1
DATA_KEY_BYTES: Final = 32
NONCE_BYTES: Final = 12
TAG_BYTES: Final = 16

_MAX_KEY_ID: Final = 512
_MAX_ALGORITHM: Final = 64
_MAX_WRAPPED: Final = 2048
# AESGCM.encrypt raises OverflowError above 2**31 - 1 bytes of data (runbook U-2).
_MAX_CIPHERTEXT: Final = 2**31 - 1
_MAX_PLAINTEXT: Final = _MAX_CIPHERTEXT - TAG_BYTES
_AAD_MAGIC: Final = b"NSAAD1"
_HEADER_AAD_MAGIC: Final = b"NSEV-AAD"


@dataclass(frozen=True, slots=True)
class WrappedKey:
    """A data key encrypted under a key-encryption key. ``key_id`` names the exact KEK version."""

    key_id: str
    algorithm: str
    value: bytes


@runtime_checkable
class KeyWrapper(Protocol):
    """Wraps and unwraps data keys under one key-encryption key."""

    @property
    def key_id(self) -> str: ...

    async def wrap(self, data_key: bytes) -> WrappedKey: ...

    async def unwrap(self, wrapped: WrappedKey) -> bytes: ...


def _integrity() -> EnvelopeError:
    return EnvelopeError(CONTENT_INTEGRITY_FAILED)


def _ascii_label(value: object, limit: int) -> bytes:
    if not isinstance(value, str) or not value or not value.isascii() or not value.isprintable():
        raise _integrity()
    encoded = value.encode("ascii")
    if len(encoded) > limit:
        raise _integrity()
    return encoded


@dataclass(frozen=True, slots=True)
class Envelope:
    """One sealed content blob; construction validates shapes (``content_integrity_failed``)."""

    format_version: int
    key_id: str
    wrap_algorithm: str
    wrapped_key: bytes
    nonce: bytes
    ciphertext: bytes

    def __post_init__(self) -> None:
        if (
            not isinstance(self.format_version, int)
            or isinstance(self.format_version, bool)
            or not 0 <= self.format_version <= 0xFF
        ):
            raise _integrity()
        _ascii_label(self.key_id, _MAX_KEY_ID)
        _ascii_label(self.wrap_algorithm, _MAX_ALGORITHM)
        if not isinstance(self.wrapped_key, bytes) or not 0 < len(self.wrapped_key) <= _MAX_WRAPPED:
            raise _integrity()
        if not isinstance(self.nonce, bytes) or len(self.nonce) != NONCE_BYTES:
            raise _integrity()
        if (
            not isinstance(self.ciphertext, bytes)
            or not TAG_BYTES <= len(self.ciphertext) <= _MAX_CIPHERTEXT
        ):
            raise _integrity()

    def to_bytes(self) -> bytes:
        if self.format_version != ENVELOPE_FORMAT_VERSION:
            raise _integrity()
        key_id = self.key_id.encode("ascii")
        algorithm = self.wrap_algorithm.encode("ascii")
        return b"".join(
            (
                ENVELOPE_MAGIC,
                struct.pack(">B", self.format_version),
                struct.pack(">H", len(key_id)),
                key_id,
                struct.pack(">B", len(algorithm)),
                algorithm,
                struct.pack(">H", len(self.wrapped_key)),
                self.wrapped_key,
                struct.pack(">B", len(self.nonce)),
                self.nonce,
                struct.pack(">I", len(self.ciphertext)),
                self.ciphertext,
            )
        )

    @classmethod
    def from_bytes(cls, data: bytes) -> Envelope:
        """Strict parse: magic, known version, bounded lengths, exact nonce, no trailing bytes."""
        if not isinstance(data, bytes | bytearray | memoryview):
            raise _integrity()
        reader = _Reader(bytes(data))
        if reader.take(len(ENVELOPE_MAGIC)) != ENVELOPE_MAGIC:
            raise _integrity()
        version = reader.uint(">B")
        if version != ENVELOPE_FORMAT_VERSION:
            raise _integrity()
        key_id = reader.field(">H", 1, _MAX_KEY_ID)
        algorithm = reader.field(">B", 1, _MAX_ALGORITHM)
        wrapped = reader.field(">H", 1, _MAX_WRAPPED)
        nonce = reader.field(">B", NONCE_BYTES, NONCE_BYTES)
        ciphertext = reader.field(">I", TAG_BYTES, _MAX_CIPHERTEXT)
        if not reader.at_end():
            raise _integrity()
        try:
            key_id_text = key_id.decode("ascii")
            algorithm_text = algorithm.decode("ascii")
        except UnicodeDecodeError:
            raise _integrity() from None
        return cls(
            format_version=version,
            key_id=key_id_text,
            wrap_algorithm=algorithm_text,
            wrapped_key=wrapped,
            nonce=nonce,
            ciphertext=ciphertext,
        )


class _Reader:
    __slots__ = ("_data", "_offset")

    def __init__(self, data: bytes) -> None:
        self._data = data
        self._offset = 0

    def take(self, count: int) -> bytes:
        end = self._offset + count
        if end > len(self._data):
            raise _integrity()
        chunk = self._data[self._offset : end]
        self._offset = end
        return chunk

    def uint(self, fmt: str) -> int:
        (value,) = struct.unpack(fmt, self.take(struct.calcsize(fmt)))
        return int(value)

    def field(self, fmt: str, minimum: int, maximum: int) -> bytes:
        length = self.uint(fmt)
        if not minimum <= length <= maximum:
            raise _integrity()
        return self.take(length)

    def at_end(self) -> bool:
        return self._offset == len(self._data)


def canonical_aad(fields: Mapping[str, str]) -> bytes:
    """Deterministic, unambiguous encoding: sorted keys, each key and value u32-length-prefixed."""
    parts = [_AAD_MAGIC, struct.pack(">I", len(fields))]
    for name in sorted(fields):
        value = fields[name]
        if not isinstance(name, str) or not isinstance(value, str):
            raise TypeError("canonical_aad takes str keys and str values")
        for text in (name, value):
            encoded = text.encode("utf-8")
            parts.append(struct.pack(">I", len(encoded)))
            parts.append(encoded)
    return b"".join(parts)


def _aead_associated_data(version: int, key_id: str, algorithm: str, aad: bytes) -> bytes:
    key_id_bytes = key_id.encode("ascii")
    algorithm_bytes = algorithm.encode("ascii")
    return b"".join(
        (
            _HEADER_AAD_MAGIC,
            struct.pack(">B", version),
            struct.pack(">H", len(key_id_bytes)),
            key_id_bytes,
            struct.pack(">B", len(algorithm_bytes)),
            algorithm_bytes,
            struct.pack(">I", len(aad)),
            aad,
        )
    )


async def seal(plaintext: bytes, aad: bytes, wrapper: KeyWrapper) -> Envelope:
    """Encrypt ``plaintext`` under a fresh data key; bind ``aad`` and the envelope header."""
    if not isinstance(plaintext, bytes) or not isinstance(aad, bytes):
        raise TypeError("seal takes bytes plaintext and bytes aad")
    if len(plaintext) > _MAX_PLAINTEXT or len(aad) > _MAX_CIPHERTEXT // 2:
        raise ValueError("content_too_large")
    data_key = AESGCM.generate_key(bit_length=256)
    try:
        try:
            wrapped = await wrapper.wrap(data_key)
        except EnvelopeError:
            raise
        except Exception:
            raise EnvelopeError(KEY_WRAP_UNAVAILABLE) from None
        if not isinstance(wrapped, WrappedKey):
            raise EnvelopeError(KEY_WRAP_UNAVAILABLE)
        nonce = os.urandom(NONCE_BYTES)
        try:
            associated = _aead_associated_data(
                ENVELOPE_FORMAT_VERSION, wrapped.key_id, wrapped.algorithm, aad
            )
        except (AttributeError, UnicodeEncodeError):
            raise EnvelopeError(KEY_WRAP_UNAVAILABLE) from None
        ciphertext = AESGCM(data_key).encrypt(nonce, plaintext, associated)
        try:
            return Envelope(
                format_version=ENVELOPE_FORMAT_VERSION,
                key_id=wrapped.key_id,
                wrap_algorithm=wrapped.algorithm,
                wrapped_key=wrapped.value,
                nonce=nonce,
                ciphertext=ciphertext,
            )
        except EnvelopeError:
            # A wrapper returned an unusable key id, algorithm or wrapped value.
            raise EnvelopeError(KEY_WRAP_UNAVAILABLE) from None
    finally:
        # bytes are immutable, so this only drops the reference; the key is never stored.
        del data_key


async def open_envelope(envelope: Envelope, aad: bytes, wrapper: KeyWrapper) -> bytes:
    """Unwrap the data key and decrypt; any mismatch raises ``content_integrity_failed``."""
    if not isinstance(envelope, Envelope) or not isinstance(aad, bytes):
        raise _integrity()
    if envelope.format_version != ENVELOPE_FORMAT_VERSION:
        raise _integrity()
    wrapped = WrappedKey(
        key_id=envelope.key_id, algorithm=envelope.wrap_algorithm, value=envelope.wrapped_key
    )
    try:
        data_key = await wrapper.unwrap(wrapped)
    except EnvelopeError:
        raise
    except Exception:
        raise EnvelopeError(KEY_WRAP_UNAVAILABLE) from None
    try:
        if not isinstance(data_key, bytes) or len(data_key) != DATA_KEY_BYTES:
            raise _integrity()
        associated = _aead_associated_data(
            envelope.format_version, envelope.key_id, envelope.wrap_algorithm, aad
        )
        try:
            return AESGCM(data_key).decrypt(envelope.nonce, envelope.ciphertext, associated)
        except InvalidTag:
            raise _integrity() from None
    finally:
        del data_key
