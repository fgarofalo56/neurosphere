"""Shared fixtures for the MCP core tests: stub DNS, a fake Cosmos container, sample tools."""

from __future__ import annotations

import itertools
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from azure.cosmos.exceptions import (
    CosmosAccessConditionFailedError,
    CosmosResourceExistsError,
    CosmosResourceNotFoundError,
)

NOW = datetime(2026, 10, 22, 12, 0, tzinfo=UTC)
ADMIN = "commercial:contoso:entra:person:p-00000000000000aa"
OTHER_ADMIN = "commercial:contoso:entra:person:p-00000000000000bb"
PUBLIC_V4 = "93.184.215.14"
PUBLIC_V6 = "2606:4700::1111"
SERVER_URL = "https://mcp.example.com/mcp"


def later(minutes: int) -> datetime:
    return NOW + timedelta(minutes=minutes)


class StubResolver:
    """DNS stub: each lookup pops the next answer for the host (the last answer repeats)."""

    def __init__(self, answers: dict[str, Sequence[Sequence[str]]] | None = None) -> None:
        self.answers = {k: [list(a) for a in v] for k, v in (answers or {}).items()}
        self.calls: list[tuple[str, int]] = []
        self.error: BaseException | None = None

    async def resolve(self, host: str, port: int) -> Sequence[str]:
        self.calls.append((host, port))
        if self.error is not None:
            raise self.error
        queue = self.answers.get(host)
        if not queue:
            raise OSError("no such host")
        return queue.pop(0) if len(queue) > 1 else queue[0]


def tool(
    name: str = "lookup",
    *,
    description: str = "Look up a record by id.",
    properties: dict[str, Any] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """One raw MCP wire tool (camelCase members, as a server sends it)."""
    raw: dict[str, Any] = {
        "name": name,
        "description": description,
        "inputSchema": {
            "type": "object",
            "properties": properties if properties is not None else {"id": {"type": "string"}},
        },
    }
    raw.update(extra)
    return raw


class FakeContainer:
    """Just enough of ``azure.cosmos.aio.ContainerProxy`` for the registry store."""

    def __init__(self) -> None:
        self.items: dict[str, dict[str, Any]] = {}
        self._etags = itertools.count(1)
        self.error: BaseException | None = None

    def _check(self) -> None:
        if self.error is not None:
            raise self.error

    def _stamp(self, body: dict[str, Any]) -> dict[str, Any]:
        row = {**body, "_etag": f'"{next(self._etags)}"', "_rid": "r", "_ts": 1}
        self.items[body["id"]] = row
        return dict(row)

    async def read_item(self, item: str, partition_key: str) -> dict[str, Any]:
        self._check()
        assert item == partition_key
        if item not in self.items:
            raise CosmosResourceNotFoundError(status_code=404, message="missing")
        return dict(self.items[item])

    async def create_item(self, body: dict[str, Any]) -> dict[str, Any]:
        self._check()
        if body["id"] in self.items:
            raise CosmosResourceExistsError(status_code=409, message="exists")
        return self._stamp(body)

    async def replace_item(
        self, item: str, body: dict[str, Any], *, etag: str, match_condition: Any
    ) -> dict[str, Any]:
        self._check()
        current = self.items.get(item)
        if current is None:
            raise CosmosResourceNotFoundError(status_code=404, message="missing")
        if current["_etag"] != etag:
            raise CosmosAccessConditionFailedError(status_code=412, message="etag")
        return self._stamp(body)

    def query_items(self, query: str, *, parameters: list[dict[str, Any]]) -> AsyncIterator[Any]:
        self._check()
        values = {p["name"]: p["value"] for p in parameters}
        assert "@doc_type" in values and "@limit" in values
        rows = [dict(r) for r in self.items.values() if r.get("doc_type") == values["@doc_type"]]

        async def iterate() -> AsyncIterator[Any]:
            for row in rows[: values["@limit"]]:
                yield row

        return iterate()
