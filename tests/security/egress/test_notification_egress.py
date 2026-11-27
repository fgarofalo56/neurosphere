"""Notification egress guard against real local HTTP servers (PRP-107 item 3, Egress criterion).

Two routes reach the 127.0.0.1 test servers:

* the local sink (``NS_ENV=local`` + ``local_sink`` + the exact ``local_sink_url``), plain HTTP;
* the pinned https path, with a stub resolver that answers a PUBLIC address for the test
  hostname and a network backend that records the pinned address, connects to the local server
  and skips TLS. That proves the guard connects to the vetted address and never re-resolves;
  the same server behind a resolver that answers 127.0.0.1 is refused with no hit.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any, cast

import httpcore
import pytest
from neurosphere_contracts.admin.v1.system_setting import NotificationsSetting
from neurosphere_contracts.notifications.v1.notification_channel import NotificationChannel
from neurosphere_core.notifications.egress import (
    REASON_CODES,
    EgressGuard,
    EgressRefusedError,
    EgressResponse,
)

HOOK_HOST = "hooks.example.com"
PUBLIC_ADDRESS = "8.8.8.8"


def make_channel(**overrides: Any) -> NotificationChannel:
    doc: dict[str, Any] = {
        "schema_version": "1.0.0",
        "channel_id": "ops-hook",
        "cloud": "commercial",
        "customer_id": "contoso",
        "domain_id": "",
        "display_name": "Ops hook",
        "kind": "teams_webhook",
        "allowed_host": HOOK_HOST,
        "endpoint_credential": None,
        "local_sink": False,
        "enabled": True,
    }
    doc.update(overrides)
    if not doc["domain_id"]:
        doc["domain_id"] = f"{doc['cloud']}:contoso:tenant:domain:finance"
    return NotificationChannel.model_validate(doc)


def make_setting(*hosts: str) -> NotificationsSetting:
    return NotificationsSetting.model_validate(
        {"egress_allowed_hosts": list(hosts) or ["example.com"]}
    )


@dataclass
class StubResolver:
    answers: dict[str, list[str]]
    calls: list[str] = field(default_factory=list[str])

    async def resolve(self, host: str, port: int) -> Sequence[str]:
        self.calls.append(host)
        return self.answers.get(host, [])


class _PlainStream(httpcore.AsyncNetworkStream):
    """Delegating stream whose start_tls is a no-op, so an https request runs over plain TCP."""

    def __init__(self, inner: httpcore.AsyncNetworkStream) -> None:
        self._inner = inner

    async def read(self, max_bytes: int, timeout: float | None = None) -> bytes:  # noqa: ASYNC109
        return await self._inner.read(max_bytes, timeout=timeout)

    async def write(self, buffer: bytes, timeout: float | None = None) -> None:  # noqa: ASYNC109
        await self._inner.write(buffer, timeout=timeout)

    async def aclose(self) -> None:
        await self._inner.aclose()

    async def start_tls(
        self,
        ssl_context: Any,
        server_hostname: str | None = None,
        timeout: float | None = None,  # noqa: ASYNC109
    ) -> httpcore.AsyncNetworkStream:
        self.sni = server_hostname
        return self

    def get_extra_info(self, info: str) -> Any:
        return self._inner.get_extra_info(info)


class LoopbackBackend(httpcore.AsyncNetworkBackend):
    """Records the address the guard pinned, then connects to the local test server instead."""

    def __init__(self, port: int) -> None:
        self._port = port
        self._inner = cast(httpcore.AsyncNetworkBackend, httpcore.AnyIOBackend())
        self.requested: list[tuple[str, int]] = []
        self.streams: list[_PlainStream] = []

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,  # noqa: ASYNC109
        local_address: str | None = None,
        socket_options: Iterable[Any] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        self.requested.append((host, port))
        stream = _PlainStream(await self._inner.connect_tcp("127.0.0.1", self._port, timeout))
        self.streams.append(stream)
        return stream

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,  # noqa: ASYNC109
        socket_options: Iterable[Any] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        raise httpcore.ConnectError("no unix sockets")

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)


@dataclass
class LocalServer:
    """A tiny asyncio HTTP/1.1 responder on 127.0.0.1 with a hit counter."""

    mode: str = "ok"
    location: str = ""
    hits: int = 0
    bodies: list[bytes] = field(default_factory=list[bytes])
    hosts: list[str] = field(default_factory=list[str])
    port: int = 0
    _server: asyncio.Server | None = None

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            head = await reader.readuntil(b"\r\n\r\n")
            length = 0
            for line in head.split(b"\r\n")[1:]:
                name, _, value = line.partition(b":")
                if name.strip().lower() == b"content-length":
                    length = int(value.strip())
                if name.strip().lower() == b"host":
                    self.hosts.append(value.strip().decode())
            self.bodies.append(await reader.readexactly(length) if length else b"")
            self.hits += 1
            writer.write(await self._response())
            await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()

    async def _response(self) -> bytes:
        if self.mode == "redirect":
            return (
                f"HTTP/1.1 302 Found\r\nLocation: {self.location}\r\n"
                "Content-Length: 0\r\nConnection: close\r\n\r\n"
            ).encode()
        if self.mode == "big":
            # No Content-Length: the guard must count the streamed bytes and abort.
            return b"HTTP/1.1 200 OK\r\nConnection: close\r\n\r\n" + b"x" * (256 * 1024)
        if self.mode == "big_declared":
            return b"HTTP/1.1 200 OK\r\nContent-Length: 100000\r\nConnection: close\r\n\r\n"
        if self.mode == "gzip":
            return (
                b"HTTP/1.1 200 OK\r\nContent-Encoding: gzip\r\n"
                b"Content-Length: 2\r\nConnection: close\r\n\r\nzz"
            )
        if self.mode == "slow":
            await asyncio.sleep(5)
        if self.mode == "error":
            return b"HTTP/1.1 503 Busy\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
        return b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok"

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self._server.wait_closed(), 2)


@pytest.fixture
async def server() -> AsyncIterator[LocalServer]:
    srv = LocalServer()
    await srv.start()
    try:
        yield srv
    finally:
        await srv.stop()


@pytest.fixture
async def second_server() -> AsyncIterator[LocalServer]:
    srv = LocalServer()
    await srv.start()
    try:
        yield srv
    finally:
        await srv.stop()


def sink_channel(port: int, **overrides: Any) -> NotificationChannel:
    return make_channel(
        local_sink=True, local_sink_url=f"http://127.0.0.1:{port}/hook", **overrides
    )


class PinnedGuard(EgressGuard):
    """An EgressGuard whose resolver and backend stay reachable for assertions."""

    def __init__(self, srv: LocalServer, address: str, **kw: Any) -> None:
        self.test_backend = LoopbackBackend(srv.port)
        self.test_resolver = StubResolver({HOOK_HOST: [address]})
        super().__init__(resolver=self.test_resolver, network_backend=self.test_backend, **kw)


def pinned_guard(srv: LocalServer, address: str = PUBLIC_ADDRESS, **kw: Any) -> PinnedGuard:
    return PinnedGuard(srv, address, **kw)


async def post_pinned(
    guard: EgressGuard, url: str = f"https://{HOOK_HOST}/hook", **kw: Any
) -> EgressResponse:
    return await guard.post(
        make_channel(),
        url,
        kw.pop("body", b"{}"),
        kw.pop("headers", {"Content-Type": "application/json"}),
        setting=make_setting("example.com"),
        deployment_cloud="commercial",
        ns_env=kw.pop("ns_env", "dev"),
    )


# -- allow-list and boundary at channel create ---------------------------------------------


@pytest.mark.parametrize(
    ("host", "entry"),
    [
        ("evil-example.com", "example.com"),
        ("example.com.evil.net", "example.com"),
        ("notexample.com", "example.com"),
        ("example.org", "example.com"),
        ("hooks.example.com", "hooks.example.com.au"),
    ],
)
def test_host_off_list_refused_at_create(host: str, entry: str) -> None:
    with pytest.raises(EgressRefusedError) as exc:
        EgressGuard().check_channel_host(
            make_channel(allowed_host=host),
            make_setting(entry),
            deployment_cloud="commercial",
            ns_env="dev",
        )
    assert exc.value.reason_code == "host_not_allowed"


@pytest.mark.parametrize(
    ("host", "entry"),
    [("example.com", "example.com"), ("hooks.example.com", "example.com"), ("a.b.c.io", "c.io")],
)
def test_host_on_list_accepted(host: str, entry: str) -> None:
    EgressGuard().check_channel_host(
        make_channel(allowed_host=host),
        make_setting(entry),
        deployment_cloud="commercial",
        ns_env="dev",
    )


def test_government_refuses_commercial_channel() -> None:
    with pytest.raises(EgressRefusedError) as exc:
        EgressGuard().check_channel_host(
            make_channel(cloud="commercial", allowed_host="hooks.example.com"),
            make_setting("example.com"),
            deployment_cloud="government",
            ns_env="dev",
        )
    assert exc.value.reason_code == "cloud_boundary"


def test_government_refuses_host_off_its_list() -> None:
    gov_setting = make_setting("webhook.office365.us")
    guard = EgressGuard()
    guard.check_channel_host(
        make_channel(cloud="government", allowed_host="contoso.webhook.office365.us"),
        gov_setting,
        deployment_cloud="government",
        ns_env="dev",
    )
    with pytest.raises(EgressRefusedError) as exc:
        guard.check_channel_host(
            make_channel(cloud="government", allowed_host="contoso.webhook.office.com"),
            gov_setting,
            deployment_cloud="government",
            ns_env="dev",
        )
    assert exc.value.reason_code == "host_not_allowed"


@pytest.mark.parametrize("ns_env", ["dev", "test", "prod", "LOCAL", ""])
def test_local_sink_refused_outside_local(ns_env: str) -> None:
    with pytest.raises(EgressRefusedError) as exc:
        EgressGuard().check_channel_host(
            sink_channel(8080),
            make_setting("example.com"),
            deployment_cloud="commercial",
            ns_env=ns_env,
        )
    assert exc.value.reason_code == "local_sink_not_permitted"


# -- address vetting -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "address",
    ["127.0.0.1", "169.254.169.254", "10.1.2.3", "::1", "::ffff:127.0.0.1", "::ffff:10.0.0.5"],
)
async def test_blocked_resolution_refused_without_connect(
    server: LocalServer, address: str
) -> None:
    guard = pinned_guard(server, address=address)
    result = await post_pinned(guard)
    assert result.reason_code == "blocked_address"
    assert result.status_code is None
    assert guard.test_backend.requested == []
    assert server.hits == 0


async def test_any_blocked_address_in_answer_refused(server: LocalServer) -> None:
    guard = EgressGuard(
        resolver=StubResolver({HOOK_HOST: [PUBLIC_ADDRESS, "192.168.1.1"]}),
        network_backend=LoopbackBackend(server.port),
    )
    assert (await post_pinned(guard)).reason_code == "blocked_address"
    assert server.hits == 0


async def test_unresolvable_host_is_dns_unavailable(server: LocalServer) -> None:
    guard = EgressGuard(resolver=StubResolver({}), network_backend=LoopbackBackend(server.port))
    result = await post_pinned(guard)
    assert result.reason_code == "dns_unavailable"
    assert result.retryable


async def test_pinned_send_connects_to_vetted_address_with_hostname(server: LocalServer) -> None:
    guard = pinned_guard(server)
    result = await post_pinned(guard, body=b'{"id":"r1"}')
    assert result.ok and result.status_code == 200
    backend = guard.test_backend
    assert backend.requested == [(PUBLIC_ADDRESS, 443)]
    assert backend.streams[0].sni == HOOK_HOST
    assert server.hosts == [HOOK_HOST]
    assert server.bodies == [b'{"id":"r1"}']


async def test_same_server_refused_when_resolver_says_loopback(server: LocalServer) -> None:
    assert (await post_pinned(pinned_guard(server))).ok
    assert server.hits == 1
    refused = await post_pinned(pinned_guard(server, address="127.0.0.1"))
    assert refused.reason_code == "blocked_address"
    assert server.hits == 1


async def test_http_error_status_reported(server: LocalServer) -> None:
    server.mode = "error"
    result = await post_pinned(pinned_guard(server))
    assert (result.status_code, result.reason_code) == (503, "http_status")
    assert result.retryable


# -- redirects, caps and deadline ----------------------------------------------------------


async def test_redirect_never_followed(server: LocalServer, second_server: LocalServer) -> None:
    server.mode = "redirect"
    server.location = f"http://127.0.0.1:{second_server.port}/steal"
    result = await post_pinned(pinned_guard(server))
    assert (result.status_code, result.reason_code) == (302, "redirect")
    assert server.hits == 1
    assert second_server.hits == 0


async def test_redirect_never_followed_on_local_sink(
    server: LocalServer, second_server: LocalServer
) -> None:
    server.mode = "redirect"
    server.location = f"http://127.0.0.1:{second_server.port}/hook"
    channel = sink_channel(server.port)
    result = await EgressGuard().post(
        channel,
        f"http://127.0.0.1:{server.port}/hook",
        b"{}",
        {},
        setting=make_setting("example.com"),
        deployment_cloud="commercial",
        ns_env="local",
    )
    assert result.reason_code == "redirect"
    assert second_server.hits == 0


@pytest.mark.parametrize("mode", ["big", "big_declared"])
async def test_oversized_response_aborted(server: LocalServer, mode: str) -> None:
    server.mode = mode
    result = await post_pinned(pinned_guard(server, max_response_bytes=1024))
    assert result.reason_code == "response_too_large"


async def test_encoded_response_refused(server: LocalServer) -> None:
    server.mode = "gzip"
    assert (await post_pinned(pinned_guard(server))).reason_code == "encoded_response"


async def test_slow_response_times_out(server: LocalServer) -> None:
    server.mode = "slow"
    loop = asyncio.get_running_loop()
    started = loop.time()
    result = await post_pinned(pinned_guard(server, timeout_seconds=0.5))
    assert result.reason_code == "timeout"
    assert result.retryable
    assert loop.time() - started < 3


async def test_oversized_body_refused_before_connect(server: LocalServer) -> None:
    guard = pinned_guard(server, max_body_bytes=16)
    result = await post_pinned(guard, body=b"x" * 17)
    assert result.reason_code == "body_too_large"
    assert guard.test_backend.requested == []
    assert guard.test_resolver.calls == []
    assert server.hits == 0


# -- URL policy ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "reason"),
    [
        (f"https://user:pw@{HOOK_HOST}/hook", "userinfo_not_allowed"),
        (f"https://{HOOK_HOST}@evil.net/hook", "userinfo_not_allowed"),
        (f"http://{HOOK_HOST}/hook", "scheme_not_allowed"),
        (f"ftp://{HOOK_HOST}/hook", "scheme_not_allowed"),
        ("https://evil-example.com/hook", "host_mismatch"),
        ("https://other.example.com/hook", "host_mismatch"),
        ("https://127.0.0.1/hook", "host_mismatch"),
        ("https://[::1]/hook", "host_mismatch"),
        (f"https://{HOOK_HOST}\\@evil.net/", "invalid_url"),
        (f"https://{HOOK_HOST}/a b", "invalid_url"),
        (f"https://{HOOK_HOST}:99999/hook", "invalid_url"),
        ("not a url", "invalid_url"),
    ],
)
async def test_url_policy(server: LocalServer, url: str, reason: str) -> None:
    guard = pinned_guard(server)
    result = await post_pinned(guard, url=url)
    assert result.reason_code == reason
    assert guard.test_backend.requested == []
    assert server.hits == 0


# -- local sink ----------------------------------------------------------------------------


async def test_local_sink_accepted_with_local_env_flag_and_matching_url(
    server: LocalServer,
) -> None:
    url = f"http://127.0.0.1:{server.port}/hook"
    result = await EgressGuard().post(
        sink_channel(server.port),
        url,
        b"payload",
        {"Content-Type": "application/json"},
        setting=make_setting("example.com"),
        deployment_cloud="commercial",
        ns_env="local",
    )
    assert result.ok and result.status_code == 200
    assert server.bodies == [b"payload"]


@pytest.mark.parametrize(
    ("ns_env", "local_sink", "path"),
    [
        ("dev", True, "/hook"),  # not NS_ENV=local
        ("local", False, "/hook"),  # channel not marked local sink
        ("local", True, "/other"),  # url differs from local_sink_url
    ],
)
async def test_local_sink_refused_otherwise(
    server: LocalServer, ns_env: str, local_sink: bool, path: str
) -> None:
    channel = sink_channel(server.port) if local_sink else make_channel()
    result = await EgressGuard().post(
        channel,
        f"http://127.0.0.1:{server.port}{path}",
        b"{}",
        {},
        setting=make_setting("example.com"),
        deployment_cloud="commercial",
        ns_env=ns_env,
    )
    assert result.reason_code in {"local_sink_not_permitted", "scheme_not_allowed"}
    assert server.hits == 0


# -- no leakage ----------------------------------------------------------------------------


async def test_refusal_logs_and_errors_carry_no_url_or_body(
    server: LocalServer, caplog: pytest.LogCaptureFixture
) -> None:
    secret_path = "/workflows/token-abc123/hook?sig=zzz"
    caplog.set_level("DEBUG", logger="neurosphere.core.notifications.egress")
    guard = pinned_guard(server, address="169.254.169.254")
    result = await post_pinned(
        guard, url=f"https://{HOOK_HOST}{secret_path}", headers={"X-Sig": "sig-value"}
    )
    assert result.reason_code == "blocked_address"
    text = caplog.text + " ".join(
        str(getattr(r, k, "")) for r in caplog.records for k in r.__dict__
    )
    for needle in ("token-abc123", "sig=zzz", "sig-value", "/workflows"):
        assert needle not in text
    err = EgressRefusedError("host_mismatch", "ops-hook")
    assert str(err) == "notification egress refused for channel ops-hook: host_mismatch"


def test_reason_codes_are_snake_case() -> None:
    for code in REASON_CODES:
        assert code.replace("_", "").isalpha() and code == code.lower()
