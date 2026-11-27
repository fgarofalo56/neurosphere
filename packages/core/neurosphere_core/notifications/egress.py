"""Egress guard for notification channels (PRP-107 item 3).

Every notification that leaves the process goes through :class:`EgressGuard`. Two entry points:

* :meth:`EgressGuard.check_channel_host` runs when a channel is created (and again on every
  send): the channel's cloud must equal the deployment cloud (a Government deployment never
  calls a Commercial-boundary channel, and the reverse), its ``allowed_host`` must match an entry
  of ``NotificationsSetting.egress_allowed_hosts`` and ``local_sink`` is refused unless
  ``NS_ENV=local`` (clarification 7).
* :meth:`EgressGuard.post` sends one POST. The URL is parsed strictly (https only, no userinfo,
  no query-less tricks such as backslashes or control characters), its host must be exactly the
  channel's ``allowed_host``, the host is resolved ONCE and refused when any address is blocked
  (:func:`neurosphere_core.mcp.ssrf.blocked_address_reason`), and the socket is pinned to the
  vetted addresses (:class:`PinnedNetworkBackend`, imitating the API MCP transport on httpcore
  1.x). TLS SNI and certificate verification stay on the hostname because httpcore passes the
  origin host as ``server_hostname``. Redirects are never followed (a 3xx is reported as
  ``redirect`` and its location is never requested), a content-encoded response is refused, the
  response body is streamed under a cap, the request body is capped before any connection and
  one total deadline covers resolve, connect, send and read.

Host matching is by DNS label, never by substring: after normalisation (IDNA, lowercase,
trailing dot stripped) ``host == entry or host.endswith("." + entry)``. ``evil-example.com`` does
not match ``example.com`` and ``example.com.evil.net`` does not either.

The local sink (``NS_ENV=local`` plus ``channel.local_sink`` plus a URL equal to
``channel.local_sink_url``) is the only path allowed to use plain HTTP and loopback or a compose
service name; it skips the blocked-address check and nothing else.

Every refusal is one of the stable snake_case codes in :data:`REASON_CODES`. Exceptions and logs
carry the channel id and the reason only: never the URL path or query (a Teams webhook URL is a
bearer secret), the headers or the body.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, Literal, NoReturn, cast

import httpcore
import httpx
from neurosphere_contracts.admin.v1.system_setting import NotificationsSetting
from neurosphere_contracts.notifications.v1.notification_channel import NotificationChannel
from neurosphere_core.mcp.ssrf import (
    MAX_RESOLVED_ADDRESSES,
    Resolver,
    SystemResolver,
    blocked_address_reason,
    canonical_address,
)

__all__ = [
    "DEFAULT_DNS_TIMEOUT_SECONDS",
    "DEFAULT_MAX_BODY_BYTES",
    "DEFAULT_MAX_RESPONSE_BYTES",
    "DEFAULT_TIMEOUT_SECONDS",
    "REASON_CODES",
    "RETRYABLE_REASON_CODES",
    "EgressGuard",
    "EgressRefusedError",
    "EgressResponse",
    "PinnedNetworkBackend",
    "ReasonCode",
    "host_matches_entry",
    "normalize_host",
]

logger = logging.getLogger("neurosphere.core.notifications.egress")

#: Request body cap; a larger body is refused before any connection (``body_too_large``).
DEFAULT_MAX_BODY_BYTES: Final = 64 * 1024
#: Response body cap; the stream is aborted once it is exceeded (``response_too_large``).
DEFAULT_MAX_RESPONSE_BYTES: Final = 16 * 1024
#: One deadline over resolve, connect, send and read (``timeout``).
DEFAULT_TIMEOUT_SECONDS: Final = 10.0
#: DNS lookup bound inside the total deadline (``dns_unavailable``).
DEFAULT_DNS_TIMEOUT_SECONDS: Final = 5.0

_MAX_URL_LENGTH: Final = 2048
_LOCAL_ENV: Final = "local"

ReasonCode = Literal[
    "cloud_boundary",
    "host_not_allowed",
    "invalid_host",
    "local_sink_not_permitted",
    "invalid_url",
    "scheme_not_allowed",
    "userinfo_not_allowed",
    "host_mismatch",
    "body_too_large",
    "dns_unavailable",
    "blocked_address",
    "connect_failed",
    "timeout",
    "redirect",
    "encoded_response",
    "response_too_large",
    "protocol_error",
    "http_status",
]

#: Every reason code the guard can produce (stable; senders and the outbox persist them).
REASON_CODES: Final[frozenset[str]] = frozenset(
    {
        "cloud_boundary",
        "host_not_allowed",
        "invalid_host",
        "local_sink_not_permitted",
        "invalid_url",
        "scheme_not_allowed",
        "userinfo_not_allowed",
        "host_mismatch",
        "body_too_large",
        "dns_unavailable",
        "blocked_address",
        "connect_failed",
        "timeout",
        "redirect",
        "encoded_response",
        "response_too_large",
        "protocol_error",
        "http_status",
    }
)

#: Outcomes worth another attempt (transient network trouble); everything else is final, except
#: ``http_status``, whose retryability depends on the status code (the sender decides).
RETRYABLE_REASON_CODES: Final[frozenset[str]] = frozenset(
    {"dns_unavailable", "connect_failed", "timeout", "protocol_error"}
)

# Headers the guard owns: the caller may not set them (framing, routing, compression, cookies).
_GUARD_OWNED_HEADERS: Final = frozenset(
    {
        "host",
        "content-length",
        "transfer-encoding",
        "connection",
        "keep-alive",
        "upgrade",
        "te",
        "trailer",
        "accept-encoding",
        "cookie",
        "proxy-authorization",
        "proxy-connection",
    }
)

_LABEL: Final = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")
_PORT: Final = re.compile(r"^[0-9]{1,5}$")
# Characters that never belong in a URL we send: whitespace, controls and backslash (a parser
# differential vector).
_FORBIDDEN_URL_CHARS: Final = re.compile(r"[\x00-\x20\x7f\\]")
_SCHEME_SPLIT: Final = re.compile(r"^([A-Za-z][A-Za-z0-9+.-]*)://([^/?#]*)([^#]*)$")


class EgressRefusedError(Exception):
    """A channel or send refused by policy. Carries only the channel id and a reason code."""

    def __init__(self, reason_code: ReasonCode, channel_id: str | None = None) -> None:
        self.reason_code: ReasonCode = reason_code
        self.channel_id = channel_id
        super().__init__(f"notification egress refused for channel {channel_id}: {reason_code}")


@dataclass(frozen=True, slots=True)
class EgressResponse:
    """Outcome of :meth:`EgressGuard.post`.

    ``status_code`` is the HTTP status when a response line arrived (also for ``redirect`` and
    ``http_status``), else ``None``. ``reason_code`` is ``None`` only for a 2xx response.
    """

    status_code: int | None
    reason_code: ReasonCode | None

    @property
    def ok(self) -> bool:
        return self.reason_code is None

    @property
    def retryable(self) -> bool:
        """Transient network failures and 408/429/5xx statuses are worth another attempt."""
        if self.reason_code is None:
            return False
        if self.reason_code == "http_status":
            code = self.status_code or 0
            return code in (408, 429) or code >= 500
        return self.reason_code in RETRYABLE_REASON_CODES


@dataclass(frozen=True, slots=True)
class _Target:
    scheme: Literal["http", "https"]
    host: str
    port: int
    target: str


def normalize_host(name: str) -> str | None:
    """IDNA-encode, lowercase and strip one trailing dot; ``None`` when ``name`` is not a hostname.

    IP literals, empty labels, labels over 63 octets, names over 253 octets and characters
    outside ``[a-z0-9-]`` after IDNA encoding all return ``None``.
    """
    if not name or len(name) > 254:
        return None
    candidate = name[:-1] if name.endswith(".") else name
    if not candidate or candidate.startswith(".") or ".." in candidate:
        return None
    try:
        ascii_name = candidate.encode("idna").decode("ascii").lower()
    except (UnicodeError, ValueError):
        return None
    if len(ascii_name) > 253:
        return None
    labels = ascii_name.split(".")
    if not all(_LABEL.match(label) for label in labels):
        return None
    try:
        ipaddress.ip_address(ascii_name)
    except ValueError:
        pass
    else:
        return None
    return ascii_name


def host_matches_entry(host: str, entry: str) -> bool:
    """DNS-label match: ``host`` equals ``entry`` or is a subdomain of it (never a substring)."""
    norm_host = normalize_host(host)
    norm_entry = normalize_host(entry)
    if norm_host is None or norm_entry is None:
        return False
    return norm_host == norm_entry or norm_host.endswith("." + norm_entry)


def _entries(setting: NotificationsSetting) -> list[str]:
    return [entry.root for entry in setting.egress_allowed_hosts]


def _parse_url(raw: str, channel_id: str) -> _Target:
    """Strict URL split. Refuses userinfo, fragments, bad ports and parser-differential chars."""
    if not isinstance(raw, str) or not raw or len(raw) > _MAX_URL_LENGTH:
        raise EgressRefusedError("invalid_url", channel_id)
    if _FORBIDDEN_URL_CHARS.search(raw):
        raise EgressRefusedError("invalid_url", channel_id)
    match = _SCHEME_SPLIT.match(raw)
    if match is None:
        raise EgressRefusedError("invalid_url", channel_id)
    scheme, authority, rest = match.group(1).lower(), match.group(2), match.group(3)
    if scheme not in ("http", "https"):
        raise EgressRefusedError("scheme_not_allowed", channel_id)
    if "@" in authority:
        raise EgressRefusedError("userinfo_not_allowed", channel_id)
    if authority.startswith("["):
        # IPv6 literal: never equal to a channel's allowed_host (which is a bare hostname).
        raise EgressRefusedError("host_mismatch", channel_id)
    host_part, sep, port_part = authority.partition(":")
    if sep:
        if not _PORT.match(port_part):
            raise EgressRefusedError("invalid_url", channel_id)
        port = int(port_part)
        if not 1 <= port <= 65535:
            raise EgressRefusedError("invalid_url", channel_id)
    else:
        port = 443 if scheme == "https" else 80
    host = normalize_host(host_part)
    if host is None:
        # An IPv4 literal is kept as-is: it can never equal a channel's allowed_host, so only
        # the local sink (127.0.0.1) can use it.
        try:
            host = ipaddress.IPv4Address(host_part).compressed
        except ValueError:
            raise EgressRefusedError("invalid_url", channel_id) from None
    target = rest or "/"
    if not target.startswith("/"):
        raise EgressRefusedError("invalid_url", channel_id)
    return _Target(
        scheme="https" if scheme == "https" else "http", host=host, port=port, target=target
    )


def _default_backend() -> httpcore.AsyncNetworkBackend:
    # httpcore declares AnyIOBackend conditionally (anyio is installed: httpx depends on it).
    return cast(httpcore.AsyncNetworkBackend, httpcore.AnyIOBackend())


class PinnedNetworkBackend(httpcore.AsyncNetworkBackend):
    """Connects to the vetted addresses of one host:port only; never resolves DNS itself."""

    def __init__(
        self,
        host: str,
        port: int,
        addresses: Sequence[str],
        inner: httpcore.AsyncNetworkBackend | None = None,
    ) -> None:
        if not addresses:
            raise ValueError("a pinned backend needs at least one vetted address")
        self._host = host
        self._port = port
        self._addresses = tuple(addresses)
        self._inner = inner if inner is not None else _default_backend()
        self.connected_to: list[str] = []

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,  # noqa: ASYNC109 - httpcore backend signature
        local_address: str | None = None,
        socket_options: Iterable[Any] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        if port != self._port or host.lower() != self._host:
            raise httpcore.ConnectError("connection target is not the vetted host")
        last: Exception | None = None
        for address in self._addresses:
            try:
                stream = await self._inner.connect_tcp(
                    address,
                    port,
                    timeout=timeout,
                    local_address=local_address,
                    socket_options=socket_options,
                )
            except (httpcore.ConnectError, httpcore.ConnectTimeout) as exc:
                last = exc
                continue
            self.connected_to.append(address)
            return stream
        raise last or httpcore.ConnectError("no vetted address accepted the connection")

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,  # noqa: ASYNC109 - httpcore backend signature
        socket_options: Iterable[Any] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        raise httpcore.ConnectError("unix sockets are never used for notifications")

    async def sleep(self, seconds: float) -> None:
        await self._inner.sleep(seconds)


class _ResponseTooLargeError(Exception):
    pass


class EgressGuard:
    """Policy plus transport for one outbound notification POST (module docstring)."""

    def __init__(
        self,
        *,
        resolver: Resolver | None = None,
        network_backend: httpcore.AsyncNetworkBackend | None = None,
        max_body_bytes: int = DEFAULT_MAX_BODY_BYTES,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        dns_timeout_seconds: float = DEFAULT_DNS_TIMEOUT_SECONDS,
    ) -> None:
        if max_body_bytes < 0 or max_response_bytes < 0:
            raise ValueError("byte caps must be non-negative")
        if timeout_seconds <= 0 or dns_timeout_seconds <= 0:
            raise ValueError("timeouts must be positive")
        self._resolver: Resolver = resolver if resolver is not None else SystemResolver()
        self._backend = network_backend
        self.max_body_bytes = max_body_bytes
        self.max_response_bytes = max_response_bytes
        self.timeout_seconds = timeout_seconds
        self.dns_timeout_seconds = dns_timeout_seconds

    # -- channel policy ---------------------------------------------------------------------

    def check_channel_host(
        self,
        channel: NotificationChannel,
        setting: NotificationsSetting,
        *,
        deployment_cloud: str,
        ns_env: str,
    ) -> None:
        """Refuse a channel outside the deployment boundary, off the allow-list or a stray sink.

        Raises :class:`EgressRefusedError` with ``cloud_boundary``, ``invalid_host``,
        ``host_not_allowed`` or ``local_sink_not_permitted``.
        """
        channel_id = channel.channel_id.root
        if channel.cloud.root != deployment_cloud:
            self._refuse("cloud_boundary", channel_id)
        if channel.local_sink and ns_env != _LOCAL_ENV:
            self._refuse("local_sink_not_permitted", channel_id)
        host = normalize_host(channel.allowed_host)
        if host is None:
            self._refuse("invalid_host", channel_id)
        if not any(host_matches_entry(host, entry) for entry in _entries(setting)):
            self._refuse("host_not_allowed", channel_id)

    # -- send ------------------------------------------------------------------------------

    async def post(
        self,
        channel: NotificationChannel,
        url: str,
        body: bytes,
        headers: Mapping[str, str],
        *,
        setting: NotificationsSetting,
        deployment_cloud: str,
        ns_env: str,
    ) -> EgressResponse:
        """POST ``body`` to ``url`` for ``channel``; never raises for egress outcomes.

        Policy refusals return ``EgressResponse(None, <reason>)`` without any network activity
        (except the DNS lookup for ``blocked_address``/``dns_unavailable``).
        """
        channel_id = channel.channel_id.root
        try:
            self.check_channel_host(
                channel, setting, deployment_cloud=deployment_cloud, ns_env=ns_env
            )
            if len(body) > self.max_body_bytes:
                self._refuse("body_too_large", channel_id)
            local_sink = self._is_local_sink(channel, url, ns_env)
            target = _parse_url(url, channel_id)
            if not local_sink:
                if target.scheme != "https":
                    self._refuse("scheme_not_allowed", channel_id)
                expected = normalize_host(channel.allowed_host)
                if expected is None or target.host != expected:
                    self._refuse("host_mismatch", channel_id)
            async with asyncio.timeout(self.timeout_seconds):
                return await self._send(channel_id, target, body, headers, pinned=not local_sink)
        except EgressRefusedError as exc:
            return EgressResponse(status_code=None, reason_code=exc.reason_code)
        except TimeoutError:
            self._log("timeout", channel_id)
            return EgressResponse(status_code=None, reason_code="timeout")

    def _is_local_sink(self, channel: NotificationChannel, url: str, ns_env: str) -> bool:
        """True only for NS_ENV=local, local_sink true and the exact configured sink URL."""
        if not channel.local_sink:
            return False
        if ns_env != _LOCAL_ENV:  # also refused by check_channel_host; kept for defence in depth
            self._refuse("local_sink_not_permitted", channel.channel_id.root)
        sink = channel.local_sink_url.root if channel.local_sink_url is not None else None
        if sink is None or url != sink:
            self._refuse("local_sink_not_permitted", channel.channel_id.root)
        return True

    async def _vet(self, channel_id: str, host: str, port: int) -> list[str]:
        try:
            async with asyncio.timeout(self.dns_timeout_seconds):
                raw = list(await self._resolver.resolve(host, port))
        except (OSError, TimeoutError, UnicodeError):
            self._refuse("dns_unavailable", channel_id)
        if not raw or len(raw) > MAX_RESOLVED_ADDRESSES:
            self._refuse("dns_unavailable", channel_id)
        vetted: list[str] = []
        for item in raw:
            try:
                address = canonical_address(ipaddress.ip_address(item))
            except ValueError:
                self._refuse("blocked_address", channel_id)
            category = blocked_address_reason(address)
            if category is not None:
                logger.warning(
                    "notification egress refused",
                    extra={
                        "channel_id": channel_id,
                        "reason_code": "blocked_address",
                        "address_category": category,
                    },
                )
                raise EgressRefusedError("blocked_address", channel_id)
            text = address.compressed
            if text not in vetted:
                vetted.append(text)
        return vetted

    def _request_headers(
        self, target: _Target, headers: Mapping[str, str], length: int
    ) -> list[tuple[bytes, bytes]]:
        default_port = 443 if target.scheme == "https" else 80
        host_value = target.host if target.port == default_port else f"{target.host}:{target.port}"
        out: list[tuple[bytes, bytes]] = [
            (b"Host", host_value.encode("ascii")),
            (b"Content-Length", str(length).encode("ascii")),
            (b"Accept-Encoding", b"identity"),
            (b"Connection", b"close"),
        ]
        for name, value in headers.items():
            if name.lower() in _GUARD_OWNED_HEADERS:
                continue
            out.append((name.encode("latin-1"), value.encode("latin-1")))
        return out

    async def _send(
        self,
        channel_id: str,
        target: _Target,
        body: bytes,
        headers: Mapping[str, str],
        *,
        pinned: bool,
    ) -> EgressResponse:
        inner = self._backend if self._backend is not None else _default_backend()
        backend: httpcore.AsyncNetworkBackend
        if pinned:
            addresses = await self._vet(channel_id, target.host, target.port)
            backend = PinnedNetworkBackend(target.host, target.port, addresses, inner=inner)
        else:
            backend = inner
        try:
            request_headers = self._request_headers(target, headers, len(body))
        except UnicodeError:
            self._refuse("protocol_error", channel_id)
        per_phase = self.timeout_seconds
        pool = httpcore.AsyncConnectionPool(
            ssl_context=httpx.create_ssl_context(verify=True, trust_env=False),
            max_connections=1,
            max_keepalive_connections=0,
            http1=True,
            http2=False,
            retries=0,
            network_backend=backend,
        )
        try:
            async with pool:
                async with pool.stream(
                    b"POST",
                    httpcore.URL(
                        scheme=target.scheme.encode("ascii"),
                        host=target.host.encode("ascii"),
                        port=target.port,
                        target=target.target.encode("ascii"),
                    ),
                    headers=request_headers,
                    content=body,
                    extensions={
                        "timeout": {
                            "connect": per_phase,
                            "read": per_phase,
                            "write": per_phase,
                            "pool": per_phase,
                        }
                    },
                ) as response:
                    return await self._read(channel_id, response)
        except _ResponseTooLargeError:
            return self._outcome(channel_id, None, "response_too_large")
        except httpcore.TimeoutException:
            return self._outcome(channel_id, None, "timeout")
        except (httpcore.ConnectError, OSError):
            return self._outcome(channel_id, None, "connect_failed")
        except (httpcore.NetworkError, httpcore.ProtocolError, httpcore.UnsupportedProtocol):
            return self._outcome(channel_id, None, "protocol_error")

    async def _read(self, channel_id: str, response: httpcore.Response) -> EgressResponse:
        status = response.status
        if 300 <= status < 400:
            # Never followed: the Location header is not even read.
            return self._outcome(channel_id, status, "redirect")
        encoding = _header(response.headers, b"content-encoding")
        if encoding is not None and encoding.strip().lower() not in (b"", b"identity"):
            return self._outcome(channel_id, status, "encoded_response")
        declared = _header(response.headers, b"content-length")
        if declared is not None:
            try:
                if int(declared) > self.max_response_bytes:
                    return self._outcome(channel_id, status, "response_too_large")
            except ValueError:
                return self._outcome(channel_id, status, "protocol_error")
        total = 0
        async for chunk in response.aiter_stream():
            total += len(chunk)
            if total > self.max_response_bytes:
                raise _ResponseTooLargeError
        if 200 <= status < 300:
            return EgressResponse(status_code=status, reason_code=None)
        return self._outcome(channel_id, status, "http_status")

    def _outcome(self, channel_id: str, status: int | None, reason: ReasonCode) -> EgressResponse:
        self._log(reason, channel_id)
        return EgressResponse(status_code=status, reason_code=reason)

    def _refuse(self, reason: ReasonCode, channel_id: str) -> NoReturn:
        """Log and raise a refusal."""
        self._log(reason, channel_id)
        raise EgressRefusedError(reason, channel_id)

    @staticmethod
    def _log(reason: str, channel_id: str) -> None:
        logger.warning(
            "notification egress refused",
            extra={"channel_id": channel_id, "reason_code": reason},
        )


def _header(headers: Sequence[tuple[bytes, bytes]], name: bytes) -> bytes | None:
    for key, value in headers:
        if key.lower() == name:
            return value
    return None
