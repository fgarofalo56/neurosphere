"""Every Commercial corpus host is unreachable from the egress-blocked compose network.

Result label: static and compose only; in-cluster proof OPEN (no Government subscription, D7).
This proves only the local `internal: true` compose network. It says nothing about Government
services, a cluster, authorization or parity (G12, D8).

Probe tools (busybox in `egress-probe`): `nslookup` for resolution, `nc -z -w 3 <host> 443` for
the TCP connect. A failed `docker exec` fails the test instead of counting as blocked, and the
`positive_control` fixture proves the probe reaches an in-network service first (issue #98).
"""

from __future__ import annotations

import pytest

from .conftest import probe
from .corpus import concrete_host, load_corpus

pytestmark = pytest.mark.integration

# Messages busybox nslookup prints when a name does not resolve.
NSLOOKUP_FAILURE_TEXT = (
    "nxdomain",
    "can't find",
    "can't resolve",
    "no servers could be reached",
    "server failed",
    "servfail",
    "refused",
)

HOSTS = sorted({concrete_host(p) for p in load_corpus()})


def test_probe_is_alive_and_reaches_an_emulator(positive_control: None) -> None:
    """Positive control: a dead probe must not make the blocked checks pass vacuously."""


@pytest.mark.parametrize("host", HOSTS)
def test_commercial_host_does_not_resolve_or_connect(positive_control: None, host: str) -> None:
    # Absolute name (trailing dot): busybox nslookup stops at the first search-domain SERVFAIL,
    # so a relative lookup would test the runner's search suffix, not the corpus host itself.
    resolve = probe("nslookup", f"{host}.")
    # busybox nslookup normally exits non-zero on failure, but some builds exit 0 and only
    # print the failure; fall back to the output text so a quiet exit cannot pass vacuously.
    output = f"{resolve.stdout}\n{resolve.stderr}".lower()
    failed_lookup = resolve.returncode != 0 or any(m in output for m in NSLOOKUP_FAILURE_TEXT)
    assert failed_lookup, f"{host} resolved from the isolated network:\n{resolve.stdout}"
    connect = probe("nc", "-z", "-w", "3", host, "443")
    assert connect.returncode != 0, f"unexpected TCP connect to {host}:443"
