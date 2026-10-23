"""Egress transport for external MCP servers: pinned connections and a request/response guard.

Two layers, both below the SDK's ``httpx2.AsyncClient``:

* :class:`PinnedTransport` drives an ``httpcore2`` connection pool whose network backend
  (:class:`PinnedNetworkBackend`) connects ONLY to the addresses ``vet_target`` approved for the
  registered host and port. It never resolves DNS, so a rebinding answer cannot redirect the
  socket. TLS still uses the registered HOSTNAME: ``httpcore2`` passes the request's origin host
  as ``server_hostname``, so SNI and certificate verification are against the name the
  administrator registered, not the IP.
* :class:`GuardedTransport` wraps any inner transport. It refuses every request whose scheme,
  host, port or target is not the exact registered URL (so a redirect, same-origin or not, is
  never followed: there is no second hop to re-vet), strips ``Authorization``,
  ``Proxy-Authorization`` and ``Cookie`` before applying only the outbound credential
  provider's headers (no token passthrough), forces ``Accept-Encoding: identity`` and refuses an
  encoded response (no decompression bomb), and caps every response body at
  ``max_response_bytes`` (Content-Length check plus a streaming byte counter).

Violations are recorded on the guard so the connector can report the precise reason even when
the SDK wraps the transport exception.
"""

from __future__ import annotations

import ipaddress
import ssl
from collections.abc import AsyncIterable, AsyncIterator, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Final, Literal, cast

import httpcore2
import httpx2
from neurosphere_core.mcp import ServerUrl, TransportLimits, VettedTarget

__all__ = [
    "STRIPPED_HEADERS",
    "EgressRefusedError",
    "EgressViolation",
    "GuardedTransport",
    "PinnedNetworkBackend",
    "PinnedTransport",
    "ResponseTooLargeError",
    "pinned_transport",
]

#: Request headers removed before credential-provider headers are applied.
STRIPPED_HEADERS: Final = ("authorization", "proxy-authorization", "cookie")

ViolationKind = Literal["egress_refused", "response_too_large", "encoded_response"]


class EgressRefusedError(httpx2.TransportError):
    """A request was refused before it left the process (not the registered URL)."""


class ResponseTooLargeError(httpx2.ReadError):
    """A response body exceeded the cap, or arrived content-encoded."""


@dataclass(slots=True)
class EgressViolation:
    kind: ViolationKind
    detail: str


def _default_backend() -> httpcore2.AsyncNetworkBackend:
    # httpcore2 declares AnyIOBackend conditionally (anyio is installed: the SDK depends on it).
    return cast(httpcore2.AsyncNetworkBackend, httpcore2.AnyIOBackend())


def _same_host(left: str, right: str) -> bool:
    try:
        return ipaddress.ip_address(left) == ipaddress.ip_address(right)
    except ValueError:
        return left.lower() == right.lower()


class PinnedNetworkBackend(httpcore2.AsyncNetworkBackend):
    """Connects to the vetted addresses of one host:port; refuses everything else."""

    def __init__(
        self, target: VettedTarget, inner: httpcore2.AsyncNetworkBackend | None = None
    ) -> None:
        if not target.addresses:
            raise ValueError("a pinned backend needs at least one vetted address")
        self._target = target
        self._inner = inner if inner is not None else _default_backend()
        self.connected_to: list[str] = []

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,  # noqa: ASYNC109 - httpcore2 backend signature
        local_address: str | None = None,
        socket_options: Iterable[Any] | None = None,
    ) -> httpcore2.AsyncNetworkStream:
        if port != self._target.port or not _same_host(host, self._target.host):
            raise httpcore2.ConnectError("connection target is not the vetted host")
        last: Exception | None = None
        for address in self._target.addresses:
            try:
                stream = await self._inner.connect_tcp(
                    address,
                    port,
                    timeout=timeout,
                    local_address=local_address,
                    socket_options=socket_options,
                )
            except (httpcore2.ConnectError, httpcore2.ConnectTimeout) as exc:
                last = exc
                continue
            self.connected_to.append(address)
            return stream
        raise last or httpcore2.ConnectError("no vetted address accepted the connection")

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,  # noqa: ASYNC109 - httpcore2 backend signature
        socket_options: Iterable[Any] | None = None,
    ) -> httpcore2.AsyncNetworkStream:
        raise httpcore2.ConnectError("unix sockets are never used for external MCP servers")

    async def sleep(self, seconds: float) -> None:
        await self._inner.sleep(seconds)


_CORE_TO_HTTPX: Final[tuple[tuple[type[Exception], type[httpx2.TransportError]], ...]] = (
    (httpcore2.ConnectTimeout, httpx2.ConnectTimeout),
    (httpcore2.ReadTimeout, httpx2.ReadTimeout),
    (httpcore2.WriteTimeout, httpx2.WriteTimeout),
    (httpcore2.PoolTimeout, httpx2.PoolTimeout),
    (httpcore2.ConnectError, httpx2.ConnectError),
    (httpcore2.ReadError, httpx2.ReadError),
    (httpcore2.WriteError, httpx2.WriteError),
    (httpcore2.RemoteProtocolError, httpx2.RemoteProtocolError),
    (httpcore2.LocalProtocolError, httpx2.LocalProtocolError),
    (httpcore2.UnsupportedProtocol, httpx2.UnsupportedProtocol),
)


def _mapped(exc: Exception) -> Exception:
    for core_type, httpx_type in _CORE_TO_HTTPX:
        if isinstance(exc, core_type):
            return httpx_type(str(exc))
    return httpx2.TransportError("transport failure")


class _CoreStream(httpx2.AsyncByteStream):
    def __init__(self, inner: AsyncIterable[bytes]) -> None:
        self._inner = inner

    async def __aiter__(self) -> AsyncIterator[bytes]:
        try:
            async for chunk in self._inner:
                yield chunk
        except httpcore2.TimeoutException as exc:
            raise _mapped(exc) from exc
        except (httpcore2.NetworkError, httpcore2.ProtocolError) as exc:
            raise _mapped(exc) from exc

    async def aclose(self) -> None:
        close = getattr(self._inner, "aclose", None)
        if close is not None:
            await close()


class PinnedTransport(httpx2.AsyncBaseTransport):
    """``httpx2`` transport over an ``httpcore2`` pool with a :class:`PinnedNetworkBackend`."""

    def __init__(
        self,
        target: VettedTarget,
        *,
        limits: TransportLimits,
        ssl_context: ssl.SSLContext | None = None,
        network_backend: httpcore2.AsyncNetworkBackend | None = None,
    ) -> None:
        self.backend = PinnedNetworkBackend(target, inner=network_backend)
        self._pool = httpcore2.AsyncConnectionPool(
            ssl_context=ssl_context or httpx2.create_ssl_context(verify=True, trust_env=False),
            max_connections=limits.max_connections,
            max_keepalive_connections=limits.max_connections,
            http1=True,
            http2=False,
            retries=0,
            network_backend=self.backend,
        )

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        if not isinstance(request.stream, httpx2.AsyncByteStream):
            raise EgressRefusedError("only async request bodies are supported")
        core_request = httpcore2.Request(
            method=request.method,
            url=httpcore2.URL(
                scheme=request.url.raw_scheme,
                host=request.url.raw_host,
                port=request.url.port,
                target=request.url.raw_path,
            ),
            headers=request.headers.raw,
            content=request.stream,
            extensions=request.extensions,
        )
        try:
            response = await self._pool.handle_async_request(core_request)
        except (httpcore2.TimeoutException, httpcore2.NetworkError, httpcore2.ProtocolError) as exc:
            raise _mapped(exc) from exc
        except httpcore2.UnsupportedProtocol as exc:
            raise _mapped(exc) from exc
        stream = response.stream
        if not isinstance(stream, AsyncIterable):
            raise httpx2.RemoteProtocolError("unexpected synchronous response stream")
        return httpx2.Response(
            status_code=response.status,
            headers=response.headers,
            stream=_CoreStream(stream),  # pyright: ignore[reportUnknownArgumentType]
            extensions=response.extensions,
        )

    async def aclose(self) -> None:
        await self._pool.aclose()


def pinned_transport(target: VettedTarget, limits: TransportLimits) -> httpx2.AsyncBaseTransport:
    """The production inner transport (default ``TransportFactory``)."""
    return PinnedTransport(target, limits=limits)


class _BoundedStream(httpx2.AsyncByteStream):
    def __init__(self, inner: httpx2.AsyncByteStream, guard: GuardedTransport) -> None:
        self._inner = inner
        self._guard = guard

    async def __aiter__(self) -> AsyncIterator[bytes]:
        total = 0
        limit = self._guard.max_response_bytes
        async for chunk in self._inner:
            total += len(chunk)
            if total > limit:
                raise self._guard.refuse_response(
                    "response_too_large", f"response body exceeds {limit} bytes"
                )
            yield chunk

    async def aclose(self) -> None:
        await self._inner.aclose()


@dataclass(slots=True)
class _GuardState:
    violations: list[EgressViolation] = field(default_factory=list[EgressViolation])
    requests: int = 0


class GuardedTransport(httpx2.AsyncBaseTransport):
    """Exact-URL, no-passthrough, bounded-response wrapper around ``inner`` (module docstring)."""

    def __init__(
        self,
        inner: httpx2.AsyncBaseTransport,
        *,
        server_url: ServerUrl,
        credential_headers: Mapping[str, str],
        max_response_bytes: int,
    ) -> None:
        self._inner = inner
        self._url = server_url
        self._credential_headers = dict(credential_headers)
        self.max_response_bytes = max_response_bytes
        self._state = _GuardState()

    @property
    def violations(self) -> tuple[EgressViolation, ...]:
        return tuple(self._state.violations)

    @property
    def request_count(self) -> int:
        return self._state.requests

    def _record(self, kind: ViolationKind, detail: str) -> None:
        self._state.violations.append(EgressViolation(kind=kind, detail=detail))

    def refuse_response(self, kind: ViolationKind, detail: str) -> ResponseTooLargeError:
        self._record(kind, detail)
        return ResponseTooLargeError(detail)

    def _check_target(self, request: httpx2.Request) -> None:
        url = request.url
        host = url.raw_host.decode("ascii", errors="replace")
        port = url.port if url.port is not None else 443
        target = url.raw_path.decode("ascii", errors="replace")
        if (
            url.scheme != "https"
            or not _same_host(host, self._url.host)
            or port != self._url.port
            or target != self._url.target
            or url.userinfo
        ):
            self._record("egress_refused", "request is not for the registered server URL")
            raise EgressRefusedError("request is not for the registered server URL")

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        self._check_target(request)
        self._state.requests += 1
        for name in STRIPPED_HEADERS:
            if name in request.headers:
                del request.headers[name]
        request.headers["accept-encoding"] = "identity"
        for name, value in self._credential_headers.items():
            request.headers[name] = value
        response = await self._inner.handle_async_request(request)
        encoding = response.headers.get("content-encoding", "identity").strip().lower()
        if encoding not in ("", "identity"):
            await response.aclose()
            raise self.refuse_response("encoded_response", "response is content-encoded")
        length = response.headers.get("content-length")
        if length is not None and (not length.isdigit() or int(length) > self.max_response_bytes):
            await response.aclose()
            raise self.refuse_response(
                "response_too_large", f"response body exceeds {self.max_response_bytes} bytes"
            )
        stream = response.stream
        if not isinstance(stream, httpx2.AsyncByteStream):
            await response.aclose()
            raise EgressRefusedError("unexpected synchronous response stream")
        return httpx2.Response(
            status_code=response.status_code,
            headers=response.headers,
            stream=_BoundedStream(stream, self),
            extensions=response.extensions,
        )

    async def aclose(self) -> None:
        await self._inner.aclose()
