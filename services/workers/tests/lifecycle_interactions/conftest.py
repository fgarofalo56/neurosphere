from __future__ import annotations

from pathlib import Path

import pytest

from .interaction_rig import Rig, make_rig


@pytest.fixture(autouse=True)
def _local_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # LocalFileKeyWrapper refuses to construct outside NS_ENV=local.
    monkeypatch.setenv("NS_ENV", "local")


@pytest.fixture
def rig(tmp_path: Path) -> Rig:
    return make_rig(tmp_path)
