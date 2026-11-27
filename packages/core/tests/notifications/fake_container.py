"""In-process stand-in for the async ``ContainerProxy`` (shared by the three PRP-29 item 3 suites).

It honours what the Cosmos stores rely on instead of pattern-matching one query each:

* partition keys: a ``/path`` list builds the partition value from the body; point operations
  and single-partition queries must pass the FULL key (a short MultiHash key raises);
* create-only ``create_item`` (409), ``read_item``/``delete_item`` (404), ETag-checked
  ``replace_item`` (412 on mismatch, 404 on missing), ``upsert_item``;
* a small SQL subset evaluated generically: ``SELECT [TOP n|@p] * | c.field FROM c [WHERE
  <conjuncts joined by AND>] [ORDER BY c.field [ASC|DESC]]`` with conjuncts ``c.f = @p``,
  ``<``, ``<=``, ``>``, ``>=``, ``IS_DEFINED(c.f)`` and ``ARRAY_CONTAINS(@p, c.f)``. Anything
  else raises ``AssertionError``, as do missing parameters and parameters the query never uses.
  A query without ``partition_key`` is cross-partition and is recorded as such.

``calls`` records every operation name, so a test can prove which operations a store used
(the append-only decision store must never call replace/upsert/delete).
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator
from typing import Any

from azure.cosmos.exceptions import (
    CosmosAccessConditionFailedError,
    CosmosHttpResponseError,
    CosmosResourceExistsError,
    CosmosResourceNotFoundError,
)

_SELECT = re.compile(
    r"^SELECT\s+(?:TOP\s+(?P<top>@\w+|\d+)\s+)?(?P<proj>\*|c\.\w+)\s+FROM\s+c"
    r"(?:\s+WHERE\s+(?P<where>.+?))?"
    r"(?:\s+ORDER\s+BY\s+c\.(?P<order>\w+)(?:\s+(?P<dir>ASC|DESC))?)?$",
    re.IGNORECASE | re.DOTALL,
)
_COMPARE = re.compile(r"^c\.(\w+)\s*(=|<=|>=|<|>)\s*(@\w+)$")
_DEFINED = re.compile(r"^IS_DEFINED\(c\.(\w+)\)$")
_CONTAINS = re.compile(r"^ARRAY_CONTAINS\((@\w+),\s*c\.(\w+)\)$")


class FakeContainer:
    def __init__(self, partition_paths: tuple[str, ...]) -> None:
        self._paths = tuple(p.lstrip("/") for p in partition_paths)
        self.docs: dict[tuple[tuple[Any, ...], str], dict[str, Any]] = {}
        self.calls: list[str] = []
        #: (sql, params, partition key or ``None`` for cross-partition)
        self.queries: list[tuple[str, dict[str, Any], tuple[Any, ...] | None]] = []
        self.fail: Exception | None = None
        self._etag = 0

    # -- helpers --------------------------------------------------------------------------------

    def _enter(self, name: str) -> None:
        self.calls.append(name)
        if self.fail is not None:
            raise self.fail

    def _pk_of(self, body: dict[str, Any]) -> tuple[Any, ...]:
        missing = [p for p in self._paths if p not in body]
        assert not missing, f"document is missing partition key fields {missing}"
        return tuple(body[p] for p in self._paths)

    def _pk_arg(self, partition_key: Any) -> tuple[Any, ...]:
        key = tuple(partition_key) if isinstance(partition_key, list | tuple) else (partition_key,)
        assert len(key) == len(self._paths), (
            f"partition key {key!r} does not match {self._paths!r}; supply the full key"
        )
        return key

    def _stamp(self, body: dict[str, Any]) -> dict[str, Any]:
        self._etag += 1
        return {**json.loads(json.dumps(body)), "_etag": f'"{self._etag}"', "_ts": 1}

    # -- point operations -----------------------------------------------------------------------

    async def create_item(self, body: dict[str, Any]) -> dict[str, Any]:
        self._enter("create_item")
        slot = (self._pk_of(body), body["id"])
        if slot in self.docs:
            raise CosmosResourceExistsError(status_code=409, message="conflict")
        self.docs[slot] = self._stamp(body)
        return dict(self.docs[slot])

    async def upsert_item(self, body: dict[str, Any]) -> dict[str, Any]:
        self._enter("upsert_item")
        self.docs[(self._pk_of(body), body["id"])] = self._stamp(body)
        return dict(self.docs[(self._pk_of(body), body["id"])])

    async def read_item(self, item: str, partition_key: Any) -> dict[str, Any]:
        self._enter("read_item")
        found = self.docs.get((self._pk_arg(partition_key), item))
        if found is None:
            raise CosmosResourceNotFoundError(status_code=404, message="not found")
        return dict(found)

    async def replace_item(self, item: str, body: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        self._enter("replace_item")
        slot = (self._pk_of(body), item)
        current = self.docs.get(slot)
        if current is None:
            raise CosmosResourceNotFoundError(status_code=404, message="not found")
        assert "etag" in kwargs, "replace must be ETag-conditional"
        if kwargs["etag"] != current["_etag"]:
            raise CosmosAccessConditionFailedError(status_code=412, message="etag")
        self.docs[slot] = self._stamp(body)
        return dict(self.docs[slot])

    async def delete_item(self, item: str, partition_key: Any) -> None:
        self._enter("delete_item")
        slot = (self._pk_arg(partition_key), item)
        if slot not in self.docs:
            raise CosmosResourceNotFoundError(status_code=404, message="not found")
        del self.docs[slot]

    # -- queries --------------------------------------------------------------------------------

    def query_items(
        self,
        query: str,
        parameters: list[dict[str, Any]] | None = None,
        partition_key: Any = None,
        **_: Any,
    ) -> AsyncIterator[dict[str, Any]]:
        self._enter("query_items")
        params = {p["name"]: p["value"] for p in parameters or []}
        pk = None if partition_key is None else self._pk_arg(partition_key)
        self.queries.append((query, params, pk))
        rows = self._run(query, params, pk)

        async def iterate() -> AsyncIterator[dict[str, Any]]:
            for row in rows:
                yield row

        return iterate()

    def _run(
        self, query: str, params: dict[str, Any], pk: tuple[Any, ...] | None
    ) -> list[dict[str, Any]]:
        match = _SELECT.match(" ".join(query.split()))
        assert match is not None, f"unsupported query shape: {query!r}"
        used = set(re.findall(r"@\w+", query))
        assert used == set(params), f"parameters {sorted(params)} do not match query {sorted(used)}"
        predicates = [
            self._predicate(part.strip(), params)
            for part in re.split(r"\s+AND\s+", match["where"] or "", flags=re.IGNORECASE)
            if part.strip()
        ]
        rows = [
            dict(doc)
            for (doc_pk, _), doc in sorted(self.docs.items(), key=lambda kv: repr(kv[0]))
            if (pk is None or doc_pk == pk) and all(p(doc) for p in predicates)
        ]
        if match["order"]:
            order = match["order"]
            assert all(order in r for r in rows), f"ORDER BY field {order!r} is not defined"
            rows.sort(key=lambda r: r[order], reverse=(match["dir"] or "").upper() == "DESC")
        if match["top"]:
            top = match["top"]
            limit = int(params[top]) if top.startswith("@") else int(top)
            rows = rows[:limit]
        proj = match["proj"]
        if proj != "*":
            field = proj.split(".", 1)[1]
            rows = [{field: r[field]} for r in rows]
        return rows

    @staticmethod
    def _predicate(clause: str, params: dict[str, Any]) -> Any:
        if (m := _COMPARE.match(clause)) is not None:
            field, op, name = m.groups()
            wanted = params[name]
            compare = {
                "=": lambda a, b: a == b,
                "<": lambda a, b: a < b,
                "<=": lambda a, b: a <= b,
                ">": lambda a, b: a > b,
                ">=": lambda a, b: a >= b,
            }[op]
            return lambda doc: field in doc and compare(doc[field], wanted)
        if (m := _DEFINED.match(clause)) is not None:
            field = m.group(1)
            return lambda doc: field in doc
        if (m := _CONTAINS.match(clause)) is not None:
            name, field = m.groups()
            allowed = list(params[name])
            return lambda doc: field in doc and doc[field] in allowed
        raise AssertionError(f"unsupported WHERE clause: {clause!r}")


def throttled() -> CosmosHttpResponseError:
    return CosmosHttpResponseError(status_code=429, message="throttled")
