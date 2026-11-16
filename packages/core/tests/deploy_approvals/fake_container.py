"""A minimal in-memory stand-in for an async Cosmos ``ContainerProxy`` (point reads, create,
ETag-conditioned replace). Shared by the approvals tests; no network."""

from __future__ import annotations

import itertools
from typing import Any

from azure.core import MatchConditions
from azure.cosmos.exceptions import (
    CosmosAccessConditionFailedError,
    CosmosResourceExistsError,
    CosmosResourceNotFoundError,
)


class FakeContainer:
    def __init__(self, partition_field: str = "customer_id") -> None:
        self._field = partition_field
        self.docs: dict[tuple[str, str], dict[str, Any]] = {}
        self._etags = itertools.count(1)
        self.writes = 0

    async def read_item(self, item: str, partition_key: str) -> dict[str, Any]:
        found = self.docs.get((partition_key, item))
        if found is None:
            raise CosmosResourceNotFoundError(status_code=404, message="not found")
        return dict(found)

    def _stamp(self, body: dict[str, Any]) -> dict[str, Any]:
        return {**body, "_etag": f'"{next(self._etags)}"'}

    async def create_item(self, body: dict[str, Any]) -> dict[str, Any]:
        key = (str(body[self._field]), str(body["id"]))
        if key in self.docs:
            raise CosmosResourceExistsError(status_code=409, message="conflict")
        self.docs[key] = self._stamp(body)
        self.writes += 1
        return self.docs[key]

    async def replace_item(
        self,
        item: str,
        body: dict[str, Any],
        etag: str | None = None,
        match_condition: MatchConditions | None = None,
    ) -> dict[str, Any]:
        key = (str(body[self._field]), item)
        current = self.docs.get(key)
        if current is None:
            raise CosmosResourceNotFoundError(status_code=404, message="not found")
        if match_condition is MatchConditions.IfNotModified and current["_etag"] != etag:
            raise CosmosAccessConditionFailedError(status_code=412, message="precondition")
        self.docs[key] = self._stamp(body)
        self.writes += 1
        return self.docs[key]
