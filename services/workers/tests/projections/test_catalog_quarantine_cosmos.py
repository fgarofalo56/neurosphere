"""PRP-43 item 1: ``CosmosCandidateQuarantine`` against a fake container (no emulator)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from azure.cosmos.exceptions import CosmosHttpResponseError
from neurosphere_core.errors import DependencyTransientError, RateLimitedError
from neurosphere_workers.projections.catalog.quarantine import CandidateQuarantineRecord
from neurosphere_workers.projections.catalog.quarantine_cosmos import CosmosCandidateQuarantine


class _Container:
    def __init__(self, fail: Exception | None = None) -> None:
        self.docs: dict[str, dict[str, Any]] = {}
        self.fail = fail

    async def upsert_item(self, body: dict[str, Any]) -> dict[str, Any]:
        if self.fail:
            raise self.fail
        self.docs[body["id"]] = body
        return body


def _record() -> CandidateQuarantineRecord:
    return CandidateQuarantineRecord(
        id="edge-1",
        reason="out_of_scope",
        relation_type="calls",
        source_id="a",
        target_id="b",
        cloud="commercial",
        customer_id="c1",
        domain_id="d1",
        rule="r",
        quarantined_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


async def test_write_is_idempotent_by_edge_id() -> None:
    container = _Container()
    sink = CosmosCandidateQuarantine(container)  # type: ignore[arg-type]
    await sink.write(_record())
    await sink.write(_record())
    assert list(container.docs) == ["edge-1"]
    assert container.docs["edge-1"]["customer_id"] == "c1"


async def test_store_failure_raises_transient() -> None:
    sink = CosmosCandidateQuarantine(_Container(RuntimeError("down")))  # type: ignore[arg-type]
    with pytest.raises(DependencyTransientError):
        await sink.write(_record())


async def test_throttle_maps_to_rate_limited() -> None:
    err = CosmosHttpResponseError(status_code=429, message="slow")
    sink = CosmosCandidateQuarantine(_Container(err))  # type: ignore[arg-type]
    with pytest.raises(RateLimitedError):
        await sink.write(_record())
