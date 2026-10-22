"""Every Commercial corpus host is unreachable from the egress-blocked compose network.

Result label: static and compose only; in-cluster proof OPEN (no Government subscription, D7).
This proves only the local `internal: true` compose network. It says nothing about Government
services, a cluster, authorization or parity (G12, D8).

Probe tools (busybox in `egress-probe`): `nslookup` for resolution, `nc -z -w 3 <host> 443` for
the TCP connect.
"""

from __future__ import annotations

import subprocess

import pytest

from .conftest import compose
from .corpus import concrete_host, load_corpus

pytestmark = pytest.mark.integration

HOSTS = sorted({concrete_host(p) for p in load_corpus()})


def _probe(*cmd: str) -> subprocess.CompletedProcess[str]:
    return compose("--profile", "test", "exec", "-T", "egress-probe", *cmd, timeout=60)


def test_probe_is_alive_and_reaches_an_emulator(stack: None) -> None:
    """Positive control: a dead probe must not make the blocked checks pass vacuously."""
    result = _probe("nc", "-z", "-w", "5", "azurite", "10000")
    assert result.returncode == 0, f"azurite:10000 unreachable: {result.stderr}"


@pytest.mark.parametrize("host", HOSTS)
def test_commercial_host_does_not_resolve_or_connect(stack: None, host: str) -> None:
    resolved = _probe("nslookup", host).returncode == 0
    connected = _probe("nc", "-z", "-w", "3", host, "443").returncode == 0
    assert not connected, f"unexpected TCP connect to {host}:443 (resolved={resolved})"
