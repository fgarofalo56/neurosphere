"""Optional short-lived cache of tool output for report runs (PRP-19 item 5).

The key is built from :func:`neurosphere_api.authz.scope_cache_key` (cloud, customer, policy
version and the viewer's SCOPE HASH) plus the report id and ETag. It is never keyed by report id
alone, so a viewer can only ever hit entries computed under an identical scope; a policy bump or a
changed role/domain set moves the viewer to a new key. Authorization and plan validation run on
every request BEFORE the cache is consulted and the filled plan is re-validated after, so a cache
hit saves tool work only. The cache is off unless ``app.state.report_run_cache`` is set.
"""

import time
from collections import OrderedDict
from collections.abc import Callable
from typing import Final
from urllib.parse import quote

from neurosphere_core.copilot.tools import ToolResult
from neurosphere_core.scope import IdentityScope

from neurosphere_api.authz import scope_cache_key

__all__ = ["RunCache", "run_cache_key"]

NAMESPACE: Final = "reports.run"
DEFAULT_TTL_SECONDS: Final = 30.0
DEFAULT_MAX_ENTRIES: Final = 256


def run_cache_key(scope: IdentityScope, report_id: str, etag: str | None) -> str:
    """``<scope key>:<report id>:<etag>``; the scope part always includes the scope hash."""
    return f"{scope_cache_key(scope, namespace=NAMESPACE)}:{quote(report_id, safe='')}:" + quote(
        etag or "", safe=""
    )


class RunCache:
    """Bounded in-memory TTL cache of :class:`ToolResult` keyed by :func:`run_cache_key`."""

    def __init__(
        self,
        *,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        max_entries: int = DEFAULT_MAX_ENTRIES,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl = ttl_seconds
        self._max = max_entries
        self._clock = clock
        self._entries: OrderedDict[str, tuple[float, ToolResult]] = OrderedDict()

    def get(self, key: str) -> ToolResult | None:
        found = self._entries.get(key)
        if found is None:
            return None
        expires, value = found
        if self._clock() >= expires:
            del self._entries[key]
            return None
        return value

    def put(self, key: str, value: ToolResult) -> None:
        self._entries[key] = (self._clock() + self._ttl, value)
        self._entries.move_to_end(key)
        while len(self._entries) > self._max:
            self._entries.popitem(last=False)

    def keys(self) -> tuple[str, ...]:
        return tuple(self._entries)
