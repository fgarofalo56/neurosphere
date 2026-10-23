"""Exact HTTPS server URLs: parsing, normalisation and hostname policy (no network).

A registered MCP server is one exact URL. :func:`normalize_server_url` accepts only
``https://host[:port]/path[?query]`` with no userinfo, no fragment, no wildcard, no zone id, no
whitespace or control characters and no backslash. The host is lowercased, IDNA-encoded (stdlib
``idna`` codec) and stripped of one trailing dot; the default port 443 is dropped from the
normalised form. Single-label names (``intranet``, ``metadata``) and names whose last label is
numeric (``127.1``, ``0x7f.1``: alternate IPv4 spellings a resolver would accept) are refused
unless the host is a canonical IP literal.

Every comparison is on the parsed hostname. Suffix rules always carry a leading dot and match
whole labels; nothing here is a substring test on the URL string.
"""

from __future__ import annotations

import hashlib
import ipaddress
import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final
from urllib.parse import urlsplit

from neurosphere_core.errors import InvalidSchemaError
from neurosphere_core.mcp.errors import (
    INVALID_SERVER_URL,
    SSRF_BLOCKED_HOST,
    forbidden,
    invalid,
)

__all__ = [
    "BLOCKED_HOSTNAMES",
    "BLOCKED_HOST_SUFFIXES",
    "MAX_URL_CHARS",
    "ServerUrl",
    "blocked_hostname",
    "check_hostname_allowed",
    "host_matches_suffix",
    "normalize_host_suffix",
    "normalize_server_url",
    "server_id_for",
]

MAX_URL_CHARS: Final = 2048
_DEFAULT_PORT: Final = 443
_LABEL_RE: Final = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_NUMERIC_LABEL_RE: Final = re.compile(r"^(?:0x[0-9a-f]*|[0-9]+)$")

#: Exact hostnames refused before any DNS lookup (compared after normalisation).
BLOCKED_HOSTNAMES: Final = frozenset(
    {
        "localhost",
        "localhost.localdomain",
        "ip6-localhost",
        "ip6-loopback",
        "metadata",
        "metadata.google.internal",
        "metadata.azure.com",
        "metadata.azure.internal",
        "instance-data",
        "instance-data.ec2.internal",
    }
)

#: Hostname suffixes (whole labels) refused before any DNS lookup.
BLOCKED_HOST_SUFFIXES: Final = (
    ".localhost",
    ".local",
    ".localdomain",
    ".internal",
    ".home.arpa",
    ".arpa",
)


@dataclass(frozen=True, slots=True)
class ServerUrl:
    """A normalised server URL. ``host`` is ASCII, lowercase, without brackets or trailing dot."""

    url: str
    host: str
    port: int
    target: str
    ip_literal: bool


def _bad(detail: str) -> InvalidSchemaError:
    return invalid(INVALID_SERVER_URL, detail)


def _has_forbidden_chars(raw: str) -> bool:
    return any(ord(ch) < 0x21 or ord(ch) == 0x7F or ch == "\\" for ch in raw)


def _normalize_dns_host(host: str) -> str:
    if host.endswith("."):
        host = host[:-1]
    if not host or host.endswith(".") or "*" in host:
        raise _bad("server host must be an exact DNS name")
    try:
        ascii_host = host.encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise _bad("server host is not a valid internationalised name") from exc
    if len(ascii_host) > 253:
        raise _bad("server host is too long")
    labels = ascii_host.split(".")
    if len(labels) < 2:
        raise _bad("server host must be a fully qualified name")
    if not all(_LABEL_RE.fullmatch(label) for label in labels):
        raise _bad("server host has an invalid label")
    if _NUMERIC_LABEL_RE.fullmatch(labels[-1]):
        raise _bad("server host is not a canonical name or IP literal")
    return ascii_host


def _normalize_host(raw_host: str, netloc: str) -> tuple[str, bool]:
    if "%" in netloc:
        raise _bad("server host must not carry a zone id")
    if netloc.startswith("["):
        try:
            address = ipaddress.IPv6Address(raw_host)
        except ValueError as exc:
            raise _bad("server host is not a valid IPv6 literal") from exc
        return address.compressed, True
    try:
        v4 = ipaddress.IPv4Address(raw_host)
    except ValueError:
        return _normalize_dns_host(raw_host), False
    return v4.compressed, True


def normalize_server_url(raw: str) -> ServerUrl:
    """Parse and normalise ``raw``; anything outside the exact-HTTPS rule is ``invalid_schema``.

    Hostname policy (metadata names, ``localhost``) is applied separately by
    :func:`check_hostname_allowed` so the two refusals keep distinct reason codes.
    """
    if not raw or len(raw) > MAX_URL_CHARS:
        raise _bad(f"server URL must be 1..{MAX_URL_CHARS} characters")
    if _has_forbidden_chars(raw):
        raise _bad("server URL contains whitespace, control characters or a backslash")
    if "#" in raw:
        raise _bad("server URL must not carry a fragment")
    parts = urlsplit(raw)
    if parts.scheme.lower() != "https":
        raise _bad("server URL must use https")
    netloc = parts.netloc
    if not netloc or "@" in netloc:
        raise _bad("server URL must have a host and no userinfo")
    raw_host = parts.hostname
    if raw_host is None:
        raise _bad("server URL must have a host")
    try:
        explicit_port = parts.port
    except ValueError as exc:
        raise _bad("server URL port is invalid") from exc
    if explicit_port is not None and not 1 <= explicit_port <= 65535:
        raise _bad("server URL port is invalid")
    if netloc.endswith(":"):
        raise _bad("server URL port is invalid")
    host, ip_literal = _normalize_host(raw_host, netloc)
    port = explicit_port if explicit_port is not None else _DEFAULT_PORT
    path = parts.path or "/"
    target = path + (f"?{parts.query}" if parts.query else "")
    authority = f"[{host}]" if ":" in host else host
    if port != _DEFAULT_PORT:
        authority = f"{authority}:{port}"
    return ServerUrl(
        url=f"https://{authority}{target}",
        host=host,
        port=port,
        target=target,
        ip_literal=ip_literal,
    )


def normalize_host_suffix(suffix: str) -> str:
    """A boundary suffix: leading dot, lowercase ASCII, at least two labels (``.azure.us``)."""
    if not suffix.startswith(".") or suffix.endswith("."):
        raise ValueError("host suffixes must start with '.' and not end with '.'")
    labels = suffix[1:].lower().split(".")
    if len(labels) < 2 or not all(_LABEL_RE.fullmatch(label) for label in labels):
        raise ValueError("host suffix must be at least two valid DNS labels")
    return "." + ".".join(labels)


def host_matches_suffix(host: str, suffixes: Iterable[str]) -> bool:
    """True when parsed ``host`` is a strict subdomain of one ``.suffix`` (whole-label match)."""
    host = host.lower()
    return any(len(host) > len(s) and host.endswith(s) for s in suffixes if s.startswith("."))


def blocked_hostname(host: str) -> bool:
    """True for well-known metadata/loopback names and private-use suffixes (normalised host)."""
    host = host.lower().rstrip(".")
    return host in BLOCKED_HOSTNAMES or host_matches_suffix(host, BLOCKED_HOST_SUFFIXES)


def check_hostname_allowed(url: ServerUrl) -> None:
    """Refuse blocked hostnames with ``forbidden`` ``ssrf_blocked_host`` (before resolution)."""
    if not url.ip_literal and blocked_hostname(url.host):
        raise forbidden(SSRF_BLOCKED_HOST, "server host is a blocked metadata or local name")


def server_id_for(url: ServerUrl) -> str:
    """Deterministic server id: one registration per exact normalised URL."""
    return "mcp-" + hashlib.sha256(url.url.encode("utf-8")).hexdigest()[:32]
