from __future__ import annotations

from pathlib import Path

import pytest
from neurosphere_core.crypto import LocalFileKeyWrapper

from ._harness import SpyWrapper


@pytest.fixture(autouse=True)
def _local_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # LocalFileKeyWrapper refuses to construct outside NS_ENV=local.
    monkeypatch.setenv("NS_ENV", "local")


@pytest.fixture
def key_file(tmp_path: Path) -> Path:
    return tmp_path / "interaction-kek.bin"


@pytest.fixture
def spy(key_file: Path) -> SpyWrapper:
    return SpyWrapper(LocalFileKeyWrapper(key_file))
