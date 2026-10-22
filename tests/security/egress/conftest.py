"""Local compose helpers for the egress tests. Needs a running Docker daemon.

Mirrors tests/integration/compose/conftest.py (not importable as a sibling package here without
editing it). Static and compose only; in-cluster proof OPEN (no Government subscription, D7).
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]


def compose(*args: str, timeout: int = 600) -> subprocess.CompletedProcess[str]:
    """Run `docker compose` from the repo root and capture text output."""
    return subprocess.run(
        ["docker", "compose", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


@pytest.fixture(scope="session")
def stack() -> Iterator[None]:
    """Bring up the emulators plus the `test` profile; tear down afterwards."""
    if shutil.which("docker") is None:
        pytest.skip("docker is not installed")
    result = compose("--profile", "test", "up", "-d", "--wait", timeout=900)
    if result.returncode != 0:
        compose("--profile", "test", "down", "-v", "--remove-orphans")
        pytest.fail(f"compose up failed:\n{result.stdout}\n{result.stderr}")
    try:
        yield
    finally:
        compose("--profile", "test", "down", "-v", "--remove-orphans")
