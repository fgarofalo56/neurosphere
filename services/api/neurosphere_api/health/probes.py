"""Dependency probes for ``/readyz``.

Probes are plain async TCP/HTTP checks; they never construct Azure SDK clients and carry no
credentials. The PRP-05 item 6 clients can later be swapped in behind :class:`DependencyProbe`.

Environment variables (all optional, emulator defaults shown; no secrets belong here):

* ``NS_PROBE_COSMOS_URL``          default ``http://localhost:8081/``
* ``NS_PROBE_EVENTHUBS_HOSTPORT``  default ``localhost:5672`` (AMQP)
* ``NS_PROBE_BLOB_HOSTPORT``       default ``localhost:10000`` (Azurite blob)
* ``NS_PROBE_TIMEOUT_SECONDS``     default ``2.0``

Reason codes are an enumerated set. Nothing about the failing exception (message, host, URL)
ever leaves this module, so response bodies cannot leak connection details.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from typing import Literal, Protocol, runtime_checkable

import httpx

ReasonCode = Literal["ok", "timeout", "connection_refused", "unavailable"]

DEFAULT_PROBE_TIMEOUT_SECONDS = 2.0
DEFAULT_COSMOS_URL = "http://localhost:8081/"
DEFAULT_EVENTHUBS_HOSTPORT = "localhost:5672"
DEFAULT_BLOB_HOSTPORT = "localhost:10000"


@runtime_checkable
class DependencyProbe(Protocol):
    """A named dependency check. ``check`` returns a reason code or raises (treated as failure)."""

    name: str

    async def check(self) -> ReasonCode:
        """Probe the dependency once and return its reason code."""
        raise NotImplementedError


def classify(exc: BaseException) -> ReasonCode:
    """Map any failure to an enumerated reason code, discarding the exception details."""
    seen: BaseException | None = exc
    depth = 0
    while seen is not None and depth < 5:
        if isinstance(seen, TimeoutError | httpx.TimeoutException):
            return "timeout"
        if isinstance(seen, ConnectionRefusedError):
            return "connection_refused"
        seen = seen.__cause__ or seen.__context__
        depth += 1
    return "unavailable"


def _split_hostport(value: str) -> tuple[str, int]:
    host, sep, port = value.strip().rpartition(":")
    if not sep or not host or not port.isdigit():
        raise ValueError("expected HOST:PORT")
    return host, int(port)


class TcpProbe:
    """Succeeds when a TCP connection to ``hostport`` can be opened."""

    def __init__(self, name: str, hostport: str) -> None:
        self.name = name
        self._host, self._port = _split_hostport(hostport)

    async def check(self) -> ReasonCode:
        _reader, writer = await asyncio.open_connection(self._host, self._port)
        writer.close()
        try:
            await writer.wait_closed()
        except OSError:
            pass  # the connect already proved reachability
        return "ok"


class HttpProbe:
    """Succeeds on any HTTP response below 500 from a GET of ``url``."""

    def __init__(self, name: str, url: str, *, timeout: float) -> None:
        self.name = name
        self._url = url
        self._timeout = timeout

    async def check(self) -> ReasonCode:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.get(self._url)
        return "ok" if response.status_code < 500 else "unavailable"


def timeout_from_env(environ: Mapping[str, str]) -> float:
    raw = environ.get("NS_PROBE_TIMEOUT_SECONDS")
    if raw is None:
        return DEFAULT_PROBE_TIMEOUT_SECONDS
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_PROBE_TIMEOUT_SECONDS
    return value if 0 < value <= 60 else DEFAULT_PROBE_TIMEOUT_SECONDS


def probes_from_env(environ: Mapping[str, str]) -> tuple[DependencyProbe, ...]:
    timeout = timeout_from_env(environ)
    return (
        HttpProbe(
            "cosmos", environ.get("NS_PROBE_COSMOS_URL", DEFAULT_COSMOS_URL), timeout=timeout
        ),
        TcpProbe(
            "eventhubs", environ.get("NS_PROBE_EVENTHUBS_HOSTPORT", DEFAULT_EVENTHUBS_HOSTPORT)
        ),
        TcpProbe("blob", environ.get("NS_PROBE_BLOB_HOSTPORT", DEFAULT_BLOB_HOSTPORT)),
    )


async def _run_one(probe: DependencyProbe, limit_seconds: float) -> tuple[str, ReasonCode]:
    try:
        async with asyncio.timeout(limit_seconds):
            result = await probe.check()
    except Exception as exc:
        return probe.name, classify(exc)
    # Fail closed: anything that is not exactly "ok" counts as unavailable.
    return probe.name, "ok" if result == "ok" else "unavailable"


async def run_probes(
    probes: Sequence[DependencyProbe], limit_seconds: float
) -> dict[str, ReasonCode]:
    """Run all probes concurrently; an empty probe set is not ready (fail closed)."""
    if not probes:
        return {"probes": "unavailable"}
    results = await asyncio.gather(*(_run_one(p, limit_seconds) for p in probes))
    return dict(results)
