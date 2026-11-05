"""Client hardening from the 2026-11-04 audit (issue #112): SIIT/SRv6 blocks, IPv4-mapped forms of
every blocked IPv4 range, ASCII-only hosts (no IDNA2003/UTS-46 differential) and outbound
credential header syntax. No network: DNS is :class:`StubResolver`.

The confusable characters are the point of the Unicode cases, so RUF001 is off for this module.
"""

# ruff: noqa: RUF001 - confusable code points are the inputs under test

from __future__ import annotations

import ipaddress

import pytest
from neurosphere_core.errors import ForbiddenError, InvalidSchemaError
from neurosphere_core.mcp import (
    blocked_address_reason,
    check_credential_headers,
    normalize_server_url,
    server_id_for,
    vet_target,
)
from neurosphere_core.mcp.outbound_auth import MAX_CREDENTIAL_HEADERS
from neurosphere_core.mcp.ssrf import _V4  # pyright: ignore[reportPrivateUsage]

from .mcp_core_helpers import PUBLIC_V4, SERVER_URL, StubResolver

# -- SIIT (::ffff:0:0:0/96) and SRv6 SID (5f00::/16) ----------------------------------------------


@pytest.mark.parametrize(
    ("address", "reason"),
    [
        ("::ffff:0:0:0", "ipv4_translated"),
        ("::ffff:0:7f00:1", "ipv4_translated"),
        ("::ffff:0:a9fe:a9fe", "ipv4_translated"),
        ("::ffff:0:5db8:d70e", "ipv4_translated"),  # translated PUBLIC v4: still refused
        ("::ffff:0:ffff:ffff", "ipv4_translated"),
        ("5f00::", "srv6_sid"),
        ("5f00::1", "srv6_sid"),
        ("5f00:1234:5678::9", "srv6_sid"),
        ("5f00:ffff:ffff:ffff:ffff:ffff:ffff:ffff", "srv6_sid"),
    ],
)
def test_siit_and_srv6_ranges_are_blocked(address: str, reason: str) -> None:
    assert blocked_address_reason(ipaddress.ip_address(address)) == reason


@pytest.mark.parametrize("address", ["::ffff:0:7f00:1", "5f00::1", "5f00:ab::cd"])
async def test_siit_and_srv6_answers_are_refused_by_vetting(address: str) -> None:
    resolver = StubResolver({"mcp.example.com": [[PUBLIC_V4, address]]})
    with pytest.raises(ForbiddenError) as caught:
        await vet_target(normalize_server_url(SERVER_URL), resolver)
    assert caught.value.reason == "ssrf_blocked_address"


@pytest.mark.parametrize("url", ["https://[::ffff:0:7f00:1]/mcp", "https://[5f00::1]/mcp"])
async def test_siit_and_srv6_literals_are_refused_without_dns(url: str) -> None:
    resolver = StubResolver()
    with pytest.raises(ForbiddenError):
        await vet_target(normalize_server_url(url), resolver)
    assert resolver.calls == []


# -- IPv4-mapped forms of EVERY blocked IPv4 range ------------------------------------------------


def _samples(network: ipaddress.IPv4Network) -> list[ipaddress.IPv4Address]:
    middle = network[network.num_addresses // 2]
    return sorted({network.network_address, middle, network.broadcast_address})


_V4_CASES = [
    pytest.param(address, id=f"{network}-{address}")
    for network, _reason in _V4
    for address in _samples(network)
]


@pytest.mark.parametrize("address", _V4_CASES)
def test_ipv4_mapped_form_of_every_blocked_v4_range_is_blocked(
    address: ipaddress.IPv4Address,
) -> None:
    v4_reason = blocked_address_reason(address)
    assert v4_reason is not None
    mapped = ipaddress.IPv6Address(f"::ffff:{address}")
    assert blocked_address_reason(mapped) == v4_reason
    # The hex spelling a resolver may return is the same address.
    value = int(address)
    hex_mapped = ipaddress.IPv6Address(f"::ffff:{value >> 16:x}:{value & 0xFFFF:x}")
    assert blocked_address_reason(hex_mapped) == v4_reason


@pytest.mark.parametrize("address", _V4_CASES)
async def test_mapped_answers_for_every_blocked_v4_range_are_refused(
    address: ipaddress.IPv4Address,
) -> None:
    resolver = StubResolver({"mcp.example.com": [[f"::ffff:{address}"]]})
    with pytest.raises(ForbiddenError) as caught:
        await vet_target(normalize_server_url(SERVER_URL), resolver)
    assert caught.value.reason == "ssrf_blocked_address"


# -- hostnames: ASCII only, no IDNA conversion differential ---------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        # sharp s: IDNA2003 gives fass.example, UTS-46 non-transitional gives xn--fa-hia.example
        "https://faß.example/mcp",
        "https://bücher.example/mcp",
        "https://Key.example.com/mcp",  # Kelvin sign: lowercases to ASCII "k"
        "https://mcp。example.com/mcp",  # ideographic full stop as a label separator
        "https://ｍcp.example.com/mcp",  # fullwidth m: NFKC-folds to "mcp"
        "https://mcp.example.com＃x/mcp",  # NFKC-folds to "#": urlsplit would raise
        "https://mcp.example.com/mé",  # non-ASCII path is re-encoded by the client
        "https://mcp.example.com/mcp?q=é",
        "https://xn--fa-hia.example/ß",
    ],
)
def test_non_ascii_urls_are_refused(url: str) -> None:
    with pytest.raises(InvalidSchemaError) as caught:
        normalize_server_url(url)
    assert caught.value.reason == "invalid_server_url"


def test_the_checked_host_is_exactly_the_connected_host() -> None:
    # The A-label registers and is used byte for byte: no conversion, so no differential.
    a_label = normalize_server_url("https://xn--fa-hia.example/mcp")
    assert a_label.host == "xn--fa-hia.example"
    assert a_label.url == "https://xn--fa-hia.example/mcp"
    # The IDNA2003 spelling is a different registration, not a silent alias of the A-label.
    idna2003 = normalize_server_url("https://fass.example/mcp")
    assert server_id_for(idna2003) != server_id_for(a_label)
    # Upper-case A-labels normalise like any ASCII host.
    assert normalize_server_url("https://XN--FA-HIA.example/mcp").host == "xn--fa-hia.example"


async def test_a_metadata_name_cannot_hide_behind_unicode() -> None:
    resolver = StubResolver({"metadata.google.internal": [[PUBLIC_V4]]})
    for url in (
        "https://metadata.google.ınternal/mcp",  # dotless i
        "https://ⓜetadata.azure.com/mcp",  # circled m: NFKC-folds to "metadata"
    ):
        with pytest.raises(InvalidSchemaError):
            await vet_target(normalize_server_url(url), resolver)
    assert resolver.calls == []


# -- outbound credential headers ------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "X-Key\r\nHost",
        "X-Key\n",
        "X-Key\r",
        "\r\nX-Key",
        "X-Key\x00",
        "Bad Name",
        " X-Key",
        "X-Key:",
        "",
        "X-Kéy",
        "X-Key\t",
        "(x)",
    ],
)
def test_invalid_credential_header_names_are_invalid_schema(name: str) -> None:
    with pytest.raises(InvalidSchemaError) as caught:
        check_credential_headers({name: "value"})
    assert caught.value.reason == "invalid_credential_header"


@pytest.mark.parametrize(
    "value",
    [
        "Bearer abc\r\nX-Injected: 1",
        "Bearer abc\nX-Injected: 1",
        "Bearer abc\r",
        "Bearer\x00abc",
        "Bearer \x7f",
        "Bearer \x1b[0m",
        "Bearer é",
        " Bearer abc",
        "Bearer abc ",
    ],
)
def test_invalid_credential_header_values_are_invalid_schema(value: str) -> None:
    with pytest.raises(InvalidSchemaError) as caught:
        check_credential_headers({"Authorization": value})
    assert caught.value.reason == "invalid_credential_header"
    assert value.strip() not in str(caught.value)  # the credential is never echoed


def test_valid_credential_headers_are_lowercased_and_bounded() -> None:
    assert check_credential_headers({}) == {}
    checked = check_credential_headers(
        {"Authorization": "Bearer a.b-c_d~e+f/g=", "X-Api-Key": "k\tv"}
    )
    assert checked == {"authorization": "Bearer a.b-c_d~e+f/g=", "x-api-key": "k\tv"}
    with pytest.raises(InvalidSchemaError):
        check_credential_headers({"X-Key": "a", "x-key": "b"})
    with pytest.raises(InvalidSchemaError):
        check_credential_headers({f"x-k{i}": "v" for i in range(MAX_CREDENTIAL_HEADERS + 1)})
    with pytest.raises(InvalidSchemaError):
        check_credential_headers({"x-big": "v" * 9000})
