"""Make the lifecycle harness and the PRP-06 authz harness importable; provide ``env``."""

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _path in (_HERE.parent, _HERE):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import pytest  # noqa: E402
from lifecycle_harness import Env, make_env  # noqa: E402  # pyright: ignore[reportMissingImports]


@pytest.fixture
def env() -> Env:
    return make_env()
