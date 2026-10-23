"""SSRF policy for outbound MCP connections: resolve once, vet every address, pin the result.

The URL string is never trusted. :func:`vet_target` refuses blocked hostnames before any lookup,
resolves the host through an injectable :class:`Resolver` port (tests stub DNS; there is no
network in tests) and refuses the target when ANY returned address is blocked. The returned
:class:`VettedTarget` carries the vetted addresses; the API transport connects to those addresses
only and never re-resolves, which is the DNS-rebinding defence (a second lookup that answers
``127.0.0.1`` is never made).

Blocked (clarification 10 plus the ranges no public MCP server can legitimately use):

* IPv4: 0.0.0.0/8, 10/8, 100.64/10 (CGNAT), 127/8, 169.254/16 (incl. 169.254.169.254),
  172.16/12, 192.0.0/24, 192.0.2/24, 192.88.99/24, 192.168/16, 198.18/15, 198.51.100/24,
  203.0.113/24, 224/4 (multicast), 240/4 and 255.255.255.255, Azure platform 168.63.129.16, and
  anything else :attr:`ipaddress.IPv4Address.is_global` rejects.
* IPv6: ::/128, ::1, the IPv4-compatible block ::/96, fe80::/10, fec0::/10, fc00::/7, ff00::/8,
  100::/64, 2001::/23 (incl. Teredo), 2001:db8::/32, 2002::/16 (6to4), 64:ff9b:1::/48, and
  anything else that is not global. IPv4-mapped addresses (``::ffff:a.b.c.d``) are judged and
  pinned as the embedded IPv4 address; NAT64 ``64:ff9b::/96`` is refused when the embedded IPv4
  address is blocked.

There is no per-server override (private MCP servers are a recorded follow-up).
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, Protocol, runtime_checkable

from neurosphere_core.mcp.errors import (
    MCP_DNS_UNAVAILABLE,
    SSRF_BLOCKED_ADDRESS,
    forbidden,
    unavailable,
)
from neurosphere_core.mcp.urls import ServerUrl, check_hostname_allowed

__all__ = [
    "MAX_RESOLVED_ADDRESSES",
    "Resolver",
    "SystemResolver",
    "VettedTarget",
    "blocked_address_reason",
    "canonical_address",
    "vet_target",
]

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address

MAX_RESOLVED_ADDRESSES: Final = 32

_V4: Final[tuple[tuple[ipaddress.IPv4Network, str], ...]] = tuple(
    (ipaddress.IPv4Network(net), reason)
    for net, reason in (
        ("169.254.169.254/32", "metadata"),
        ("168.63.129.16/32", "azure_platform"),
        ("255.255.255.255/32", "broadcast"),
        ("0.0.0.0/8", "this_network"),
        ("10.0.0.0/8", "private"),
        ("100.64.0.0/10", "cgnat"),
        ("127.0.0.0/8", "loopback"),
        ("169.254.0.0/16", "link_local"),
        ("172.16.0.0/12", "private"),
        ("192.0.0.0/24", "ietf_protocol"),
        ("192.0.2.0/24", "documentation"),
        ("192.88.99.0/24", "relay_anycast"),
        ("192.168.0.0/16", "private"),
        ("198.18.0.0/15", "benchmarking"),
        ("198.51.100.0/24", "documentation"),
        ("203.0.113.0/24", "documentation"),
        ("224.0.0.0/4", "multicast"),
        ("240.0.0.0/4", "reserved"),
    )
)

_V6: Final[tuple[tuple[ipaddress.IPv6Network, str], ...]] = tuple(
    (ipaddress.IPv6Network(net), reason)
    for net, reason in (
        ("::/128", "unspecified"),
        ("::1/128", "loopback"),
        ("::/96", "ipv4_compatible"),
        ("fe80::/10", "link_local"),
        ("fec0::/10", "site_local"),
        ("fc00::/7", "unique_local"),
        ("ff00::/8", "multicast"),
        ("100::/64", "discard"),
        ("2001::/23", "ietf_protocol"),
        ("2001:db8::/32", "documentation"),
        ("2002::/16", "6to4"),
        ("64:ff9b:1::/48", "nat64_local"),
    )
)
_NAT64: Final = ipaddress.IPv6Network("64:ff9b::/96")


def canonical_address(address: IPAddress) -> IPAddress:
    """IPv4-mapped IPv6 collapses to its IPv4 address; everything else is unchanged."""
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        return address.ipv4_mapped
    return address


def _v4_reason(address: ipaddress.IPv4Address) -> str | None:
    for network, reason in _V4:
        if address in network:
            return reason
    return None if address.is_global else "non_global"


def _v6_reason(address: ipaddress.IPv6Address) -> str | None:
    if address in _NAT64:
        embedded = _v4_reason(ipaddress.IPv4Address(int(address) & 0xFFFFFFFF))
        if embedded is not None:
            return f"nat64_{embedded}"
    for network, reason in _V6:
        if address in network:
            return reason
    return None if address.is_global else "non_global"


def blocked_address_reason(address: IPAddress) -> str | None:
    """The block category for ``address``, or ``None`` when it is a public unicast address."""
    address = canonical_address(address)
    if isinstance(address, ipaddress.IPv4Address):
        return _v4_reason(address)
    return _v6_reason(address)


@runtime_checkable
class Resolver(Protocol):
    """DNS port. Returns textual IP addresses for ``host`` (any family, any order)."""

    async def resolve(self, host: str, port: int) -> Sequence[str]: ...


class SystemResolver:
    """The platform resolver (``getaddrinfo``, TCP). Production default; never used in tests."""

    async def resolve(self, host: str, port: int) -> Sequence[str]:
        infos = await asyncio.get_running_loop().getaddrinfo(
            host, port, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP
        )
        return [str(info[4][0]) for info in infos]


@dataclass(frozen=True, slots=True)
class VettedTarget:
    """A host whose every resolved address passed the policy. Connect to ``addresses`` only."""

    host: str
    port: int
    addresses: tuple[str, ...]
    url: str


def _parse(raw: str) -> IPAddress:
    try:
        return canonical_address(ipaddress.ip_address(raw))
    except ValueError:
        raise forbidden(
            SSRF_BLOCKED_ADDRESS, "server host resolved to an unparseable address"
        ) from None


async def _lookup(url: ServerUrl, resolver: Resolver, seconds: float) -> Sequence[str]:
    try:
        async with asyncio.timeout(seconds):
            return await resolver.resolve(url.host, url.port)
    except (OSError, TimeoutError, UnicodeError) as exc:
        raise unavailable(MCP_DNS_UNAVAILABLE, "server host could not be resolved") from exc


async def vet_target(
    url: ServerUrl, resolver: Resolver, *, dns_timeout_seconds: float = 5.0
) -> VettedTarget:
    """Resolve ``url.host`` once and refuse when any address is blocked (see module docstring).

    Raises ``forbidden`` (``ssrf_blocked_host`` / ``ssrf_blocked_address``) for policy refusals
    and ``dependency_transient`` (``mcp_dns_unavailable``) when resolution fails or is empty.
    """
    check_hostname_allowed(url)
    raw = [url.host] if url.ip_literal else list(await _lookup(url, resolver, dns_timeout_seconds))
    if not raw:
        raise unavailable(MCP_DNS_UNAVAILABLE, "server host resolved to no address")
    if len(raw) > MAX_RESOLVED_ADDRESSES:
        raise unavailable(MCP_DNS_UNAVAILABLE, "server host resolved to too many addresses")
    vetted: list[str] = []
    for item in raw:
        address = _parse(item)
        reason = blocked_address_reason(address)
        if reason is not None:
            raise forbidden(
                SSRF_BLOCKED_ADDRESS, f"server host resolves to a blocked address range ({reason})"
            )
        text = address.compressed
        if text not in vetted:
            vetted.append(text)
    return VettedTarget(host=url.host, port=url.port, addresses=tuple(vetted), url=url.url)
