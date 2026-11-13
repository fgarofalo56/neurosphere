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

from .ci_gate import skip_or_fail

REPO_ROOT = Path(__file__).resolve().parents[3]

# Only the probe and its positive control (azurite, reachable from `isolated`). `--no-deps`
# keeps the Cosmos emulator and Event Hubs out of the egress job; the probe's depends_on is
# a startup ordering aid, not something the blocked-network checks need.
EGRESS_SERVICES = ("egress-probe", "azurite")


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
    """Bring up the probe plus azurite on the `test` profile; tear down afterwards."""
    if shutil.which("docker") is None:
        skip_or_fail("docker is not installed")
    result = compose(
        "--profile", "test", "up", "-d", "--wait", "--no-deps", *EGRESS_SERVICES, timeout=900
    )
    if result.returncode != 0:
        compose("--profile", "test", "down", "-v", "--remove-orphans")
        pytest.fail(f"compose up failed:\n{result.stdout}\n{result.stderr}")
    try:
        yield
    finally:
        compose("--profile", "test", "down", "-v", "--remove-orphans")


# Exit codes that mean the exec itself failed, not that the probed command did.
EXEC_FAILURE_CODES = frozenset({125, 126, 127})
EXEC_FAILURE_MARKERS = ("no such container", "is not running", "no service")


def probe(*cmd: str) -> subprocess.CompletedProcess[str]:
    """Run ``cmd`` inside egress-probe; fail the test when the exec itself failed.

    A failed `docker exec` makes the caller's `nc` look "blocked", which would pass vacuously
    (issue #98), so exec failure (container missing, 125/126/127, daemon error text) fails here.
    """
    result = compose("--profile", "test", "exec", "-T", "egress-probe", *cmd, timeout=60)
    stderr = result.stderr.lower()
    exec_failed = result.returncode in EXEC_FAILURE_CODES or any(
        m in stderr for m in EXEC_FAILURE_MARKERS
    )
    if exec_failed:
        pytest.fail(
            f"docker exec failed (not a blocked result): {cmd} rc={result.returncode}\n"
            f"{result.stdout}\n{result.stderr}"
        )
    return result


@pytest.fixture(scope="session")
def positive_control(stack: None) -> None:
    """The probe can exec and reach an in-network service, so 'blocked' results are meaningful.

    Every per-host test requires this fixture, so `-k <one host>` cannot pass vacuously.
    """
    connect = probe("nc", "-z", "-w", "5", "azurite", "10000")
    assert connect.returncode == 0, f"azurite:10000 unreachable from the probe: {connect.stderr}"
    # Absolute name: the probe inherits the host's DNS search list (on GitHub runners
    # *.internal.cloudapp.net). Docker's embedded DNS answers SERVFAIL for the suffixed name on an
    # internal network and busybox nslookup stops there instead of trying the bare name.
    resolve = probe("nslookup", "azurite.")
    assert resolve.returncode == 0, f"probe cannot resolve in-network name: {resolve.stdout}"
