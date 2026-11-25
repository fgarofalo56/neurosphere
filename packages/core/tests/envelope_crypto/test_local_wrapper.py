"""PRP-102 item 3: the local file key wrapper is NS_ENV=local only and owner-only on disk."""

from __future__ import annotations

import logging
import os
import stat
import sys
from pathlib import Path

import pytest
from neurosphere_core.cloud import CloudName, Settings
from neurosphere_core.crypto import (
    CONTENT_INTEGRITY_FAILED,
    LOCAL_WRAP_ALGORITHM,
    EnvelopeError,
    LocalFileKeyWrapper,
    WrappedKey,
    canonical_aad,
    open_envelope,
    seal,
)
from neurosphere_core.errors import InvalidSchemaError


@pytest.mark.parametrize("env", ["dev", "test", "staging", "prod"])
def test_refuses_outside_local_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, env: str
) -> None:
    monkeypatch.setenv("NS_ENV", env)
    monkeypatch.setenv("NS_CLOUD", "commercial")
    path = tmp_path / "kek.bin"
    with pytest.raises(InvalidSchemaError) as caught:
        LocalFileKeyWrapper(path)
    assert caught.value.reason == "config"
    assert str(path) not in str(caught.value)
    assert not path.exists()


def test_refuses_explicit_non_local_settings(tmp_path: Path) -> None:
    with pytest.raises(InvalidSchemaError):
        LocalFileKeyWrapper(
            tmp_path / "kek.bin", settings=Settings(env="prod", cloud=CloudName.COMMERCIAL)
        )
    assert not (tmp_path / "kek.bin").exists()


def test_refuses_when_environment_is_unreadable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NS_ENV", "prod")
    monkeypatch.delenv("NS_CLOUD", raising=False)
    with pytest.raises(InvalidSchemaError):
        LocalFileKeyWrapper(tmp_path / "kek.bin")


async def test_creates_owner_only_key_file_and_round_trips(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("NS_ENV", "local")
    path = tmp_path / "nested" / "kek.bin"
    with caplog.at_level(logging.DEBUG):
        wrapper = LocalFileKeyWrapper(path)
        aad = canonical_aad({"interaction_id": "int-1"})
        envelope = await seal(b"local body", aad, wrapper)
        assert await open_envelope(envelope, aad, wrapper) == b"local body"
    material = path.read_bytes()
    assert len(material) == 32
    if sys.platform != "win32":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert wrapper.key_id.startswith("local:")
    assert len(wrapper.key_id) == len("local:") + 16
    assert material.hex() not in wrapper.key_id
    assert envelope.wrap_algorithm == LOCAL_WRAP_ALGORITHM
    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert str(path) not in logged
    assert "kek.bin" not in logged


async def test_existing_key_file_is_reused(tmp_path: Path) -> None:
    path = tmp_path / "kek.bin"
    local = Settings(env="local")
    first = LocalFileKeyWrapper(path, settings=local)
    data_key = os.urandom(32)
    wrapped = await first.wrap(data_key)
    second = LocalFileKeyWrapper(path, settings=local)
    assert second.key_id == first.key_id
    assert await second.unwrap(wrapped) == data_key


async def test_other_key_file_cannot_unwrap(tmp_path: Path) -> None:
    local = Settings(env="local")
    first = LocalFileKeyWrapper(tmp_path / "a.bin", settings=local)
    other = LocalFileKeyWrapper(tmp_path / "b.bin", settings=local)
    assert first.key_id != other.key_id
    wrapped = await first.wrap(os.urandom(32))
    with pytest.raises(EnvelopeError, match=f"^{CONTENT_INTEGRITY_FAILED}$"):
        await other.unwrap(wrapped)
    # Even with the key id forged to match, the AEAD under the other key refuses it.
    forged = WrappedKey(other.key_id, wrapped.algorithm, wrapped.value)
    with pytest.raises(EnvelopeError, match=f"^{CONTENT_INTEGRITY_FAILED}$"):
        await other.unwrap(forged)


def test_wrong_size_key_file_refused(tmp_path: Path) -> None:
    path = tmp_path / "kek.bin"
    path.write_bytes(os.urandom(16))
    with pytest.raises(InvalidSchemaError) as caught:
        LocalFileKeyWrapper(path, settings=Settings(env="local"))
    assert str(path) not in str(caught.value)
