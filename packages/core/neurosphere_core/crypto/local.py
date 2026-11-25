"""Local development key wrapper: a random file key, ``NS_ENV=local`` only (PRP-102 item 3).

Construction is refused (``invalid_schema``, reason ``config``) unless ``NS_ENV=local``, the same
local-only rule as the dev token issuer and the emulator client factories. The key file is
created with owner-only permissions (``0o600``, exclusive create; on Windows the mode is
best-effort) when absent. Data keys are wrapped with AES-256-GCM under the file key with a fresh
random nonce. The key id is a short SHA-256 fingerprint, never the key; the path is never logged.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Final

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from neurosphere_core.cloud import Settings, load_settings
from neurosphere_core.crypto.envelope import NONCE_BYTES, WrappedKey
from neurosphere_core.crypto.errors import (
    CONTENT_INTEGRITY_FAILED,
    KEY_WRAP_UNAVAILABLE,
    EnvelopeError,
)
from neurosphere_core.errors import InvalidSchemaError

__all__ = ["LOCAL_WRAP_ALGORITHM", "LocalFileKeyWrapper"]

LOCAL_WRAP_ALGORITHM: Final = "local-a256gcm"
_FILE_KEY_BYTES: Final = 32
_FINGERPRINT_LABEL: Final = b"neurosphere-local-kek-fingerprint-v1"


def _refused(detail: str) -> InvalidSchemaError:
    return InvalidSchemaError(detail, reason="config")


def _load_or_create(path: Path) -> bytes:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, flags, 0o600)
    except FileExistsError:
        pass
    except OSError:
        raise _refused("the local key file could not be created") from None
    else:
        material = os.urandom(_FILE_KEY_BYTES)
        try:
            view = memoryview(material)
            while view:
                written = os.write(fd, view)
                view = view[written:]
        except OSError:
            raise _refused("the local key file could not be written") from None
        finally:
            os.close(fd)
        return material
    try:
        material = path.read_bytes()
    except OSError:
        raise _refused("the local key file could not be read") from None
    if len(material) != _FILE_KEY_BYTES:
        raise _refused("the local key file is not a 32-byte key")
    return material


class LocalFileKeyWrapper:
    """Wraps data keys under a local 256-bit file key. Development and tests only."""

    def __init__(self, path: str | os.PathLike[str], *, settings: Settings | None = None) -> None:
        try:
            env = (settings or load_settings()).env
        except Exception:
            # An unreadable environment is not local.
            raise _refused("the local key wrapper is available only when NS_ENV=local") from None
        if env != "local":
            raise _refused("the local key wrapper is available only when NS_ENV=local")
        material = _load_or_create(Path(path))
        fingerprint = hashlib.sha256(_FINGERPRINT_LABEL + material).hexdigest()[:16]
        self._key_id = f"local:{fingerprint}"
        self._aead = AESGCM(material)
        del material

    @property
    def key_id(self) -> str:
        return self._key_id

    def _associated(self) -> bytes:
        return f"{self._key_id}|{LOCAL_WRAP_ALGORITHM}".encode("ascii")

    async def wrap(self, data_key: bytes) -> WrappedKey:
        if not isinstance(data_key, bytes) or not data_key:
            raise EnvelopeError(KEY_WRAP_UNAVAILABLE)
        nonce = os.urandom(NONCE_BYTES)
        sealed = self._aead.encrypt(nonce, data_key, self._associated())
        return WrappedKey(key_id=self._key_id, algorithm=LOCAL_WRAP_ALGORITHM, value=nonce + sealed)

    async def unwrap(self, wrapped: WrappedKey) -> bytes:
        if (
            not isinstance(wrapped, WrappedKey)
            or wrapped.key_id != self._key_id
            or wrapped.algorithm != LOCAL_WRAP_ALGORITHM
            or not isinstance(wrapped.value, bytes)
            or len(wrapped.value) <= NONCE_BYTES
        ):
            raise EnvelopeError(CONTENT_INTEGRITY_FAILED)
        nonce, sealed = wrapped.value[:NONCE_BYTES], wrapped.value[NONCE_BYTES:]
        try:
            return self._aead.decrypt(nonce, sealed, self._associated())
        except InvalidTag:
            raise EnvelopeError(CONTENT_INTEGRITY_FAILED) from None
