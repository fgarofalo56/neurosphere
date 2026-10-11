"""Real probe: a container on the internal network cannot leave, but reaches emulators."""

from __future__ import annotations

import subprocess

import pytest

from .conftest import compose

pytestmark = pytest.mark.integration

EMULATORS = [("cosmos", 8081), ("azurite", 10000), ("eventhubs", 5672)]
# Literal IPs so the result does not depend on DNS.
EXTERNAL_TCP = [("1.1.1.1", 443), ("8.8.8.8", 53)]


def _probe(*cmd: str) -> subprocess.CompletedProcess[str]:
    return compose("--profile", "test", "exec", "-T", "egress-probe", *cmd, timeout=60)


@pytest.mark.parametrize(("host", "port"), EMULATORS)
def test_probe_reaches_emulators_by_service_name(stack: None, host: str, port: int) -> None:
    result = _probe("nc", "-z", "-w", "5", host, str(port))
    assert result.returncode == 0, f"{host}:{port} unreachable: {result.stderr}"


@pytest.mark.parametrize(("host", "port"), EXTERNAL_TCP)
def test_probe_cannot_reach_external_addresses(stack: None, host: str, port: int) -> None:
    result = _probe("nc", "-z", "-w", "3", host, str(port))
    assert result.returncode != 0, f"unexpected egress to {host}:{port}"


def test_probe_cannot_fetch_external_http(stack: None) -> None:
    result = _probe("wget", "-T", "3", "-q", "-O", "/dev/null", "http://example.com")
    assert result.returncode != 0, "unexpected HTTP egress"
