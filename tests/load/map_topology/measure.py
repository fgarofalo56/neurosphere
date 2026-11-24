"""The five measured calls and the Cosmos read counter (PRP-74 item 5).

MEASURED, never asserted: nothing here compares a time to a threshold. ``CountingContainer`` wraps
a Cosmos container so each paged round trip (one ``response_hook`` call) is a read, each
``query_items`` call is a query and the ``x-ms-request-charge`` header, when the service sends
one, adds to ``ru`` (the vNext emulator may not send it: then ``ru`` stays ``None``).
"""

import statistics
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from neurosphere_api.map.settings import MapSettings
from neurosphere_api.map.topology import TopologySource

from .world import PERF_DOMAIN, ROOT_SERVICE, PerfApi

CALL_NAMES = (
    "viewport_clusters",
    "viewport_2000_nodes",
    "search",
    "impact_depth_5",
    "topology_poll",
)


class CountingContainer:
    """Counts Cosmos round trips and request charge for the wrapped async container."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.reads = 0
        self.queries = 0
        self._ru = 0.0
        self._ru_seen = False
        self._charges: set[float] = set()

    @property
    def ru(self) -> float | None:
        """Summed request charge, or ``None`` when no header arrived or it is a flat placeholder.

        The vNext emulator answers ``x-ms-request-charge: 1`` to every request. That is a
        constant, not a measurement, so a run whose every charge is exactly 1.0 reports ``None``.
        """
        if not self._ru_seen or self._charges == {1.0}:
            return None
        return self._ru

    @property
    def charges_are_placeholder(self) -> bool:
        return self._ru_seen and self._charges == {1.0}

    def snapshot(self) -> tuple[int, int, float | None]:
        return self.reads, self.queries, self.ru

    def _hook(self, headers: Any, _result: Any) -> None:
        self.reads += 1
        charge = None if headers is None else headers.get("x-ms-request-charge")
        if charge is not None:
            self._ru += float(charge)
            self._ru_seen = True
            self._charges.add(float(charge))

    def query_items(self, *args: Any, **kwargs: Any) -> Any:
        self.queries += 1
        kwargs.setdefault("response_hook", self._hook)
        return self._inner.query_items(*args, **kwargs)

    def create_item(self, *args: Any, **kwargs: Any) -> Any:
        return self._inner.create_item(*args, **kwargs)

    def replace_item(self, *args: Any, **kwargs: Any) -> Any:
        return self._inner.replace_item(*args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


@dataclass
class CallResult:
    name: str
    wall_ms: list[float] = field(default_factory=list)
    status: int = 0
    shape: dict[str, Any] = field(default_factory=dict)
    cosmos_reads_per_call: float | None = None
    cosmos_queries_per_call: float | None = None
    ru_per_call: float | None = None

    def summary(self) -> dict[str, Any]:
        ordered = sorted(self.wall_ms)
        p95 = ordered[min(len(ordered) - 1, max(0, round(0.95 * len(ordered)) - 1))]
        return {
            "wall_ms_median": round(statistics.median(ordered), 1),
            "wall_ms_p95": round(p95, 1),
            "wall_ms_all": [round(v, 1) for v in self.wall_ms],
            "repeats": len(ordered),
            "http_status": self.status,
            "cosmos_reads_per_call": self.cosmos_reads_per_call,
            "cosmos_queries_per_call": self.cosmos_queries_per_call,
            "ru_per_call": self.ru_per_call,
            "response_shape": self.shape,
        }


def _shape(body: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in ("nodes", "edges", "matches"):
        if isinstance(body.get(key), list):
            out[f"{key}_returned"] = len(body[key])
    if isinstance(body.get("levels"), list):
        out["levels_returned"] = len(body["levels"])
        out["nodes_returned"] = sum(len(lv["nodes"]) for lv in body["levels"])
    if isinstance(body.get("counts"), dict):
        out["match_total"] = sum(body["counts"].get("by_kind", {}).values())
    for key in ("truncated", "truncation_reason", "next_cursor"):
        if key in body:
            out[key] = body[key] if key != "next_cursor" else body[key] is not None
    return out


async def _repeat(
    name: str,
    repeats: int,
    counter: CountingContainer | None,
    call: Callable[[], Awaitable[tuple[int, dict[str, Any]]]],
) -> CallResult:
    result = CallResult(name)
    before = counter.snapshot() if counter else None
    for _ in range(repeats):
        start = time.perf_counter()
        status, body = await call()
        result.wall_ms.append((time.perf_counter() - start) * 1000)
        result.status = status
        result.shape = body
    if counter and before:
        reads, queries, ru = counter.snapshot()
        result.cosmos_reads_per_call = (reads - before[0]) / repeats
        result.cosmos_queries_per_call = (queries - before[1]) / repeats
        result.ru_per_call = None if ru is None else (ru - (before[2] or 0.0)) / repeats
    return result


async def run_calls(
    perf: PerfApi,
    counter: CountingContainer | None = None,
    *,
    repeats: int = 5,
    heavy_repeats: int = 3,
    impact_depth: int = 5,
) -> list[CallResult]:
    """Viewport (clusters, then one 2000-node page), search, impact and one topology poll."""

    async def http(response: Any) -> tuple[int, dict[str, Any]]:
        body = response.json()
        return response.status_code, _shape(body) if response.status_code == 200 else body

    async def clusters() -> tuple[int, dict[str, Any]]:
        return await http(await perf.get("viewport", node_budget=2000, edge_budget=5000))

    async def page() -> tuple[int, dict[str, Any]]:
        response = await perf.get(
            "viewport", cluster_id="kind:agent", node_budget=2000, edge_budget=5000
        )
        return await http(response)

    async def search() -> tuple[int, dict[str, Any]]:
        return await http(await perf.get("search", q="w0", limit=50))

    async def impact() -> tuple[int, dict[str, Any]]:
        return await http(await perf.post_impact(ROOT_SERVICE, impact_depth))

    source = TopologySource(perf.repo, MapSettings(), clock=time.monotonic)

    async def poll() -> tuple[int, dict[str, Any]]:
        source._cache.clear()  # a poll that follows a catalog write, not a TTL-cached read
        snap = await source.snapshot(perf.reader, PERF_DOMAIN)
        return 200, {"nodes": snap.node_count, "edges": snap.edge_count}

    return [
        await _repeat("viewport_clusters", repeats, counter, clusters),
        await _repeat("viewport_2000_nodes", repeats, counter, page),
        await _repeat("search", heavy_repeats, counter, search),
        await _repeat("impact_depth_5", heavy_repeats, counter, impact),
        await _repeat("topology_poll", heavy_repeats, counter, poll),
    ]
