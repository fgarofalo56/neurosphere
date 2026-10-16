"""Fixtures for the ingestion integration suite. Needs the default compose emulators.

Names only: connection settings are the same documented placeholders the PRP-05 roundtrip test
uses. ``.env`` is never read.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from .support import REPO_ROOT, emulator_env

SEED = 7


def compose(*args: str, timeout: int = 900) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", "compose", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _is_live(request: pytest.FixtureRequest) -> bool:
    """The live module talks to real cloud resources: it must never touch the emulators."""
    marks = getattr(request.module, "pytestmark", [])
    if not isinstance(marks, list):  # a single ``pytestmark = pytest.mark.x``
        marks = [marks]
    return any(getattr(m, "name", None) == "live" for m in marks)


@pytest.fixture(scope="module", autouse=True)
def _emulator_env(request: pytest.FixtureRequest) -> Iterator[None]:
    if _is_live(request):
        yield
        return
    patch = pytest.MonkeyPatch()
    for name, value in emulator_env().items():
        patch.setenv(name, value)
    patch.delenv("NS_CLOUD", raising=False)
    try:
        yield
    finally:
        patch.undo()


@pytest.fixture(scope="module", autouse=True)
def fresh_hub(request: pytest.FixtureRequest, _emulator_env: None) -> Iterator[None]:
    """Restart the Event Hubs emulator so the hub is empty (it keeps nothing across restarts).

    Each module starts from an empty hub; nothing here relies on retained offsets.
    """
    if _is_live(request):
        yield
        return
    if shutil.which("docker") is None:
        pytest.skip("docker is not installed")
    up = compose("up", "-d", "--wait")
    if up.returncode != 0:
        pytest.fail(f"compose up failed:\n{up.stdout}\n{up.stderr}")
    restart = compose("restart", "eventhubs")
    if restart.returncode != 0:
        pytest.fail(f"eventhubs restart failed:\n{restart.stdout}\n{restart.stderr}")
    waited = compose("up", "-d", "--wait")
    if waited.returncode != 0:
        pytest.fail(f"compose up (after restart) failed:\n{waited.stdout}\n{waited.stderr}")
    _wait_for_hub()
    yield


def _wait_for_hub() -> None:
    """Block until the telemetry hub answers (the emulator needs a moment after a restart)."""
    from azure.eventhub import EventHubProducerClient

    from .support import EVENTHUBS_CONNECTION, HUB

    deadline = time.monotonic() + 180
    while True:
        try:
            with EventHubProducerClient.from_connection_string(
                EVENTHUBS_CONNECTION, eventhub_name=HUB
            ) as producer:
                if len(producer.get_partition_ids()) > 0:
                    return
        except Exception:
            if time.monotonic() > deadline:
                raise
        time.sleep(3)


@pytest.fixture(scope="session")
def sandbox_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A small seeded sandbox bundle with raised defect rates (duplicates, out-of-order, bad)."""
    out = tmp_path_factory.mktemp("ingest-sandbox")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "sandbox.generate",
            "--seed",
            str(SEED),
            "--profile",
            "tiny",
            "--traces-per-agent-day",
            "1",
            "--duplicate-rate",
            "0.05",
            "--out-of-order-rate",
            "0.10",
            "--malformed-rate",
            "0.05",
            "--cloud",
            "commercial",
            "--out",
            str(out),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return out
