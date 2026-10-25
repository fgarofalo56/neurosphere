"""In-process fake Cosmos container for the store conformance suites (strict by design).

It honours what the stores rely on and rejects what they must not do:

* documents are JSON round-tripped on every read and write (so Decimal/datetime/tuple mistakes
  surface) and carry ``_etag``;
* partition keys (single or hierarchical) are read from the document at the configured paths;
  ``read_item``/``query_items`` address a partition exactly; a query without ``partition_key``
  needs ``enable_cross_partition_query=True`` (real Cosmos answers 400 otherwise);
* ``create_item`` is create-only (409), ``replace_item`` honours ``etag`` + ``IfNotModified`` (412);
* ``query_items`` parses ``SELECT [TOP @p] * FROM c [WHERE a AND b ...] [ORDER BY c.f ASC|DESC]``.
  Each WHERE clause must be a key of the ``clauses`` table (exact text) or the query is rejected,
  every ``@name`` must be supplied and every supplied parameter must be used. The query log
  (``queries``) lets tests assert that scope predicates were present in every query.
"""

from __future__ import annotations

import copy
import json
import re
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from typing import Any

from azure.core import MatchConditions
from azure.cosmos.exceptions import (
    CosmosAccessConditionFailedError,
    CosmosHttpResponseError,
    CosmosResourceExistsError,
    CosmosResourceNotFoundError,
)

Predicate = Callable[[dict[str, Any], dict[str, Any]], bool]

_SELECT = re.compile(
    r"SELECT (?:TOP @(?P<top>\w+) )?\* FROM c"
    r"(?: WHERE (?P<where>.+?))?"
    r"(?: ORDER BY c\.(?P<field>\w+) (?P<direction>ASC|DESC))?",
    re.DOTALL,
)
_PARAM = re.compile(r"@\w+")


class QueryRecord:
    def __init__(
        self, query: str, params: dict[str, Any], partition_key: tuple[Any, ...] | None
    ) -> None:
        self.query = query
        self.params = params
        self.partition_key = partition_key


def _normalise_key(partition_key: Any) -> tuple[Any, ...]:
    if isinstance(partition_key, (list, tuple)):
        return tuple(partition_key)  # pyright: ignore[reportUnknownArgumentType]
    return (partition_key,)


class _Engine:
    def __init__(self, key_paths: Sequence[str], clauses: Mapping[str, Predicate]) -> None:
        self.key_paths = tuple(p.lstrip("/") for p in key_paths)
        self.clauses = dict(clauses)
        self.items: dict[tuple[tuple[Any, ...], str], dict[str, Any]] = {}
        self.queries: list[QueryRecord] = []
        self._etag = 0

    def _key_of(self, body: Mapping[str, Any]) -> tuple[Any, ...]:
        missing = [p for p in self.key_paths if p not in body]
        if missing:
            raise CosmosHttpResponseError(status_code=400, message=f"missing key {missing}")
        return tuple(body[p] for p in self.key_paths)

    def _stamp(self, body: Mapping[str, Any]) -> dict[str, Any]:
        self._etag += 1
        stored = json.loads(json.dumps(body))  # JSON round trip, like the wire
        stored["_etag"] = f'"{self._etag}"'
        stored["_rid"] = "x"
        return stored

    def create(self, body: Mapping[str, Any]) -> dict[str, Any]:
        slot = (self._key_of(body), body["id"])
        if slot in self.items:
            raise CosmosResourceExistsError(status_code=409, message="conflict")
        self.items[slot] = self._stamp(body)
        return copy.deepcopy(self.items[slot])

    def upsert(self, body: Mapping[str, Any]) -> dict[str, Any]:
        self.items[(self._key_of(body), body["id"])] = self._stamp(body)
        return copy.deepcopy(self.items[(self._key_of(body), body["id"])])

    def replace(self, item: str, body: Mapping[str, Any], kwargs: Mapping[str, Any]) -> Any:
        slot = (self._key_of(body), item)
        if slot not in self.items:
            raise CosmosResourceNotFoundError(status_code=404, message="nf")
        etag = kwargs.get("etag")
        if etag is not None:
            assert kwargs.get("match_condition") == MatchConditions.IfNotModified
            if etag != self.items[slot]["_etag"]:
                raise CosmosAccessConditionFailedError(status_code=412, message="etag")
        self.items[slot] = self._stamp(body)
        return copy.deepcopy(self.items[slot])

    def read(self, item: str, partition_key: Any) -> dict[str, Any]:
        found = self.items.get((_normalise_key(partition_key), item))
        if found is None:
            raise CosmosResourceNotFoundError(status_code=404, message="nf")
        return copy.deepcopy(found)

    def delete(self, item: str, partition_key: Any) -> None:
        if self.items.pop((_normalise_key(partition_key), item), None) is None:
            raise CosmosResourceNotFoundError(status_code=404, message="nf")

    def query(
        self,
        query: str,
        parameters: Sequence[Mapping[str, Any]] | None,
        partition_key: Any,
        cross_partition: bool | None,
    ) -> list[dict[str, Any]]:
        params = {p["name"]: p["value"] for p in parameters or []}
        pk = None if partition_key is None else _normalise_key(partition_key)
        self.queries.append(QueryRecord(query, params, pk))
        if pk is None and not cross_partition:
            raise CosmosHttpResponseError(status_code=400, message="cross-partition query")
        used = set(_PARAM.findall(query))
        undefined = used - set(params)
        unused = set(params) - used
        assert not undefined, f"undefined parameters {sorted(undefined)} in {query!r}"
        assert not unused, f"unused parameters {sorted(unused)} in {query!r}"
        match = _SELECT.fullmatch(query)
        assert match is not None, f"query shape not supported by the fake: {query!r}"
        predicates: list[Predicate] = []
        for clause in (match["where"] or "").split(" AND ") if match["where"] else []:
            assert clause in self.clauses, f"clause not supported by the fake: {clause!r}"
            predicates.append(self.clauses[clause])
        rows = [
            copy.deepcopy(doc)
            for (key, _), doc in self.items.items()
            if (pk is None or key == pk) and all(p(doc, params) for p in predicates)
        ]
        if match["field"]:
            field = match["field"]
            rows.sort(key=lambda d: d[field], reverse=match["direction"] == "DESC")
        if match["top"]:
            rows = rows[: int(params["@" + match["top"]])]
        return rows


class FakeContainer:
    """Async (``azure.cosmos.aio``-shaped) fake container."""

    def __init__(self, key_paths: Sequence[str], clauses: Mapping[str, Predicate]) -> None:
        self._engine = _Engine(key_paths, clauses)

    @property
    def items(self) -> dict[tuple[tuple[Any, ...], str], dict[str, Any]]:
        return self._engine.items

    @property
    def queries(self) -> list[QueryRecord]:
        return self._engine.queries

    async def create_item(self, body: Mapping[str, Any]) -> dict[str, Any]:
        return self._engine.create(body)

    async def upsert_item(self, body: Mapping[str, Any]) -> dict[str, Any]:
        return self._engine.upsert(body)

    async def replace_item(self, item: str, body: Mapping[str, Any], **kwargs: Any) -> Any:
        return self._engine.replace(item, body, kwargs)

    async def read_item(self, item: str, partition_key: Any) -> dict[str, Any]:
        return self._engine.read(item, partition_key)

    async def delete_item(self, item: str, partition_key: Any) -> None:
        self._engine.delete(item, partition_key)

    async def query_items(
        self,
        query: str,
        parameters: Sequence[Mapping[str, Any]] | None = None,
        partition_key: Any = None,
    ) -> AsyncIterator[dict[str, Any]]:
        # The aio SDK takes no enable_cross_partition_query (cross-partition is the default) and
        # forwards unknown kwargs into the HTTP request, so this fake rejects it by omission.
        for row in self._engine.query(query, parameters, partition_key, True):
            yield row


class FakeSyncContainer:
    """Sync (``azure.cosmos``-shaped) fake container."""

    def __init__(self, key_paths: Sequence[str], clauses: Mapping[str, Predicate]) -> None:
        self._engine = _Engine(key_paths, clauses)

    @property
    def items(self) -> dict[tuple[tuple[Any, ...], str], dict[str, Any]]:
        return self._engine.items

    @property
    def queries(self) -> list[QueryRecord]:
        return self._engine.queries

    def create_item(self, body: Mapping[str, Any]) -> dict[str, Any]:
        return self._engine.create(body)

    def upsert_item(self, body: Mapping[str, Any]) -> dict[str, Any]:
        return self._engine.upsert(body)

    def replace_item(self, item: str, body: Mapping[str, Any], **kwargs: Any) -> Any:
        return self._engine.replace(item, body, kwargs)

    def read_item(self, item: str, partition_key: Any) -> dict[str, Any]:
        return self._engine.read(item, partition_key)

    def query_items(
        self,
        query: str,
        parameters: Sequence[Mapping[str, Any]] | None = None,
        partition_key: Any = None,
        enable_cross_partition_query: bool | None = None,
    ) -> list[dict[str, Any]]:
        return self._engine.query(query, parameters, partition_key, enable_cross_partition_query)
