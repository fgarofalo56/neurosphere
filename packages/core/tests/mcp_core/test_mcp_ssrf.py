"""SSRF policy corpus (clarification 10): URL rules, hostname blocks and resolved-address blocks.

No real DNS: every lookup goes through :class:`StubResolver`. The checks are on what a host
RESOLVES to, so a public-looking name that answers with a blocked address is refused.
"""

from __future__ import annotations

import asyncio
import ipaddress
from collections.abc import Sequence

import pytest
from neurosphere_core.errors import DependencyTransientError, ForbiddenError, InvalidSchemaError
from neurosphere_core.mcp import (
    blocked_address_reason,
    blocked_hostname,
    normalize_server_url,
    server_id_for,
    vet_target,
)
from neurosphere_core.mcp.ssrf import MAX_RESOLVED_ADDRESSES

from .mcp_core_helpers import PUBLIC_V4, PUBLIC_V6, SERVER_URL, StubResolver

# -- blocked address corpus -----------------------------------------------------------------------

BLOCKED_ADDRESSES = [
    # loopback
    "127.0.0.1",
    "127.255.255.254",
    "::1",
    # link-local, including the instance metadata endpoint
    "169.254.169.254",
    "169.254.0.1",
    "fe80::1",
    "febf:ffff::1",
    # RFC 1918
    "10.0.0.1",
    "10.255.255.255",
    "172.16.0.1",
    "172.31.255.255",
    "192.168.0.1",
    "192.168.255.255",
    # unique local
    "fc00::1",
    "fd12:3456:789a::1",
    # CGNAT
    "100.64.0.1",
    "100.127.255.254",
    # Azure platform (WireServer / DNS)
    "168.63.129.16",
    # this-network, unspecified, broadcast, multicast, reserved, documentation, benchmarking
    "0.0.0.0",  # noqa: S104 - an address under test, not a bind
    "0.1.2.3",
    "::",
    "255.255.255.255",
    "224.0.0.1",
    "239.255.255.250",
    "ff02::1",
    "240.0.0.1",
    "192.0.2.10",
    "198.51.100.7",
    "203.0.113.9",
    "198.18.0.1",
    "192.0.0.8",
    "2001:db8::1",
    # IPv4-mapped / IPv4-compatible forms of blocked IPv4
    "::ffff:127.0.0.1",
    "::ffff:169.254.169.254",
    "::ffff:10.0.0.1",
    "::ffff:168.63.129.16",
    "::127.0.0.1",
    "::10.0.0.1",
    # NAT64 embedding a blocked IPv4, local-use NAT64, 6to4, Teredo, site-local
    "64:ff9b::7f00:1",
    "64:ff9b::a9fe:a9fe",
    "64:ff9b::a00:1",
    "64:ff9b:1::1",
    "2002:7f00:1::1",
    "2001::1",
    "fec0::1",
]

PUBLIC_ADDRESSES = [PUBLIC_V4, "20.42.65.92", "8.8.8.8", PUBLIC_V6, "::ffff:93.184.215.14"]


@pytest.mark.parametrize("address", BLOCKED_ADDRESSES)
def test_blocked_ranges_are_classified(address: str) -> None:
    assert blocked_address_reason(ipaddress.ip_address(address)) is not None


@pytest.mark.parametrize("address", PUBLIC_ADDRESSES)
def test_public_unicast_is_allowed(address: str) -> None:
    assert blocked_address_reason(ipaddress.ip_address(address)) is None


def test_metadata_and_platform_reasons_are_specific() -> None:
    assert blocked_address_reason(ipaddress.ip_address("169.254.169.254")) == "metadata"
    assert blocked_address_reason(ipaddress.ip_address("168.63.129.16")) == "azure_platform"
    assert blocked_address_reason(ipaddress.ip_address("100.64.1.1")) == "cgnat"
    assert blocked_address_reason(ipaddress.ip_address("::ffff:127.0.0.1")) == "loopback"
    assert blocked_address_reason(ipaddress.ip_address("64:ff9b::7f00:1")) == "nat64_loopback"


# -- resolution: every address is checked ---------------------------------------------------------


@pytest.mark.parametrize("address", BLOCKED_ADDRESSES)
async def test_registered_name_resolving_to_blocked_address_is_refused(address: str) -> None:
    resolver = StubResolver({"mcp.example.com": [[address]]})
    with pytest.raises(ForbiddenError) as caught:
        await vet_target(normalize_server_url(SERVER_URL), resolver)
    assert caught.value.reason == "ssrf_blocked_address"
    assert address not in str(caught.value)  # the address list is never echoed


async def test_any_blocked_address_among_many_refuses_the_target() -> None:
    resolver = StubResolver({"mcp.example.com": [[PUBLIC_V4, PUBLIC_V6, "10.1.2.3"]]})
    with pytest.raises(ForbiddenError):
        await vet_target(normalize_server_url(SERVER_URL), resolver)


async def test_public_answers_are_vetted_deduplicated_and_canonical() -> None:
    resolver = StubResolver(
        {"mcp.example.com": [[PUBLIC_V4, "::ffff:93.184.215.14", PUBLIC_V6, PUBLIC_V4]]}
    )
    target = await vet_target(normalize_server_url(SERVER_URL), resolver)
    assert target.addresses == (PUBLIC_V4, PUBLIC_V6)
    assert (target.host, target.port, target.url) == ("mcp.example.com", 443, SERVER_URL)
    assert resolver.calls == [("mcp.example.com", 443)]


async def test_vetting_resolves_exactly_once_so_a_rebinding_answer_is_never_seen() -> None:
    resolver = StubResolver({"mcp.example.com": [[PUBLIC_V4], ["127.0.0.1"]]})
    target = await vet_target(normalize_server_url(SERVER_URL), resolver)
    assert target.addresses == (PUBLIC_V4,)
    assert len(resolver.calls) == 1
    # A later connection re-vets and sees the rebinding answer: it is refused, not followed.
    with pytest.raises(ForbiddenError):
        await vet_target(normalize_server_url(SERVER_URL), resolver)


@pytest.mark.parametrize(
    "answer",
    [[], ["not-an-ip"]],
)
async def test_empty_or_garbage_answers_fail_closed(answer: Sequence[str]) -> None:
    resolver = StubResolver({"mcp.example.com": [answer]})
    with pytest.raises((DependencyTransientError, ForbiddenError)):
        await vet_target(normalize_server_url(SERVER_URL), resolver)


async def test_too_many_answers_fail_closed() -> None:
    many = [f"93.184.{i // 250}.{i % 250 + 1}" for i in range(MAX_RESOLVED_ADDRESSES + 1)]
    with pytest.raises(DependencyTransientError):
        await vet_target(
            normalize_server_url(SERVER_URL), StubResolver({"mcp.example.com": [many]})
        )


async def test_resolver_failure_and_timeout_are_transient() -> None:
    failing = StubResolver()
    failing.error = OSError("dns down")
    with pytest.raises(DependencyTransientError) as caught:
        await vet_target(normalize_server_url(SERVER_URL), failing)
    assert caught.value.reason == "mcp_dns_unavailable"

    class Slow:
        async def resolve(self, host: str, port: int) -> Sequence[str]:
            await asyncio.sleep(5)
            return [PUBLIC_V4]

    with pytest.raises(DependencyTransientError):
        await vet_target(normalize_server_url(SERVER_URL), Slow(), dns_timeout_seconds=0.01)


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1/mcp",
        "https://169.254.169.254/latest/meta-data",
        "https://10.0.0.5:8443/mcp",
        "https://[::1]/mcp",
        "https://[::ffff:127.0.0.1]/mcp",
        "https://[fd00::1]/mcp",
        "https://100.64.0.1/mcp",
        "https://168.63.129.16/machine",
    ],
)
async def test_ip_literal_urls_in_blocked_ranges_are_refused_without_dns(url: str) -> None:
    resolver = StubResolver()
    with pytest.raises(ForbiddenError):
        await vet_target(normalize_server_url(url), resolver)
    assert resolver.calls == []


async def test_public_ip_literal_is_vetted_without_dns() -> None:
    resolver = StubResolver()
    target = await vet_target(normalize_server_url(f"https://{PUBLIC_V4}/mcp"), resolver)
    assert target.addresses == (PUBLIC_V4,)
    assert resolver.calls == []


# -- hostname blocks (before resolution) ----------------------------------------------------------

BLOCKED_HOSTS = [
    "metadata.google.internal",
    "metadata.google.internal.",
    "metadata.azure.com",
    "METADATA.AZURE.COM.",
    "instance-data.ec2.internal",
    "localhost.localdomain",
    "api.localhost",
    "api.localhost.",
    "printer.local",
    "svc.cluster.internal",
    "router.home.arpa",
    "1.0.0.127.in-addr.arpa",
]


@pytest.mark.parametrize("host", BLOCKED_HOSTS)
async def test_metadata_and_local_names_are_refused_before_dns(host: str) -> None:
    resolver = StubResolver({host.lower().rstrip("."): [[PUBLIC_V4]]})
    with pytest.raises(ForbiddenError) as caught:
        await vet_target(normalize_server_url(f"https://{host}/mcp"), resolver)
    assert caught.value.reason == "ssrf_blocked_host"
    assert resolver.calls == []


@pytest.mark.parametrize("host", ["metadata", "localhost", "instance-data", "localhost."])
def test_single_label_metadata_names_never_parse(host: str) -> None:
    assert blocked_hostname(host)
    with pytest.raises(InvalidSchemaError):
        normalize_server_url(f"https://{host}/mcp")


def test_lookalike_hosts_are_not_blocked_by_substring() -> None:
    assert not blocked_hostname("metadata.example.com")
    assert not blocked_hostname("notlocalhost.example.com")
    assert not blocked_hostname("localhost-tools.example.com")


# -- URL rules ------------------------------------------------------------------------------------

INVALID_URLS = [
    "http://mcp.example.com/mcp",
    "ftp://mcp.example.com/mcp",
    "https://user@mcp.example.com/mcp",
    "https://user:pw@mcp.example.com/mcp",
    "https://mcp.example.com/mcp#frag",
    "https://*.example.com/mcp",
    "https://mcp.*.com/mcp",
    "https://mcp.example.com:0/mcp",
    "https://mcp.example.com:99999/mcp",
    "https://mcp.example.com:/mcp",
    "https://mcp.example.com/m cp",
    "https://mcp.example.com/mcp\\..",
    "https://mcp.example.com/\x00",
    "https:///mcp",
    "https://intranet/mcp",
    "https://127.1/mcp",
    "https://0x7f.0.0.1/mcp",
    "https://2130706433/mcp",
    "https://[fe80::1%25eth0]/mcp",
    "https://bad_label.example.com/mcp",
    "https://-bad.example.com/mcp",
    "",
    "https://" + "a" * 2050 + ".com/",
]


@pytest.mark.parametrize("url", INVALID_URLS)
def test_only_exact_https_urls_parse(url: str) -> None:
    with pytest.raises(InvalidSchemaError) as caught:
        normalize_server_url(url)
    assert caught.value.reason == "invalid_server_url"


@pytest.mark.parametrize(
    ("raw", "normalised", "host", "port"),
    [
        ("https://MCP.Example.COM/mcp", "https://mcp.example.com/mcp", "mcp.example.com", 443),
        ("https://mcp.example.com./mcp", "https://mcp.example.com/mcp", "mcp.example.com", 443),
        ("https://mcp.example.com:443/mcp", "https://mcp.example.com/mcp", "mcp.example.com", 443),
        (
            "https://mcp.example.com:8443/mcp?v=1",
            "https://mcp.example.com:8443/mcp?v=1",
            "mcp.example.com",
            8443,
        ),
        ("https://mcp.example.com", "https://mcp.example.com/", "mcp.example.com", 443),
        (
            "https://bücher.example/mcp",
            "https://xn--bcher-kva.example/mcp",
            "xn--bcher-kva.example",
            443,
        ),
        (
            "https://[2606:4700:0::1111]/mcp",
            "https://[2606:4700::1111]/mcp",
            "2606:4700::1111",
            443,
        ),
    ],
)
def test_normalisation(raw: str, normalised: str, host: str, port: int) -> None:
    url = normalize_server_url(raw)
    assert (url.url, url.host, url.port) == (normalised, host, port)


def test_server_id_is_derived_from_the_normalised_url() -> None:
    a = normalize_server_url("https://MCP.example.com:443/mcp")
    b = normalize_server_url("https://mcp.example.com/mcp")
    c = normalize_server_url("https://mcp.example.com/mcp2")
    assert server_id_for(a) == server_id_for(b) != server_id_for(c)
