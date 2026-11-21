"""Allowed-read audit on the access routes (PRP-73 item 3): domains and count only."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from typing import Any

import pytest
from authz.authz_helpers import FINANCE, OPERATIONS  # pyright: ignore[reportMissingImports]
from catalog_access_support import (  # pyright: ignore[reportMissingImports]
    ACCESS,
    DEPENDENTS,
    REGION_GROUPS,
    asset_id,
    build_world,
)
from neurosphere_api.authz.read_audit import (
    STATS_ATTRIBUTE,
    ReadAuditStats,
    read_audit_chain_id,
)
from neurosphere_core.audit import ALLOW_DETAIL, AuditRepository, InMemoryAuditStore, sha256_digest
from ui_adapters_api.adapter_support import (  # pyright: ignore[reportMissingImports]
    AUDITOR,
    STEWARD_BOTH,
    VIEWER,
    World,
    agent_id,
)

#: A filter value and a term that must never reach an audit record.
SENTINEL = "zq-sentinel-region-73"
FIN_CHAIN = "contoso.finance"
READ_CHAIN = read_audit_chain_id("contoso")


@pytest.fixture
def world() -> World:
    return build_world()


@pytest.fixture
def read_log(caplog: pytest.LogCaptureFixture) -> Iterator[pytest.LogCaptureFixture]:
    logger = logging.getLogger("neurosphere_api.authz.read_audit")
    logger.addHandler(caplog.handler)  # the JSON logger does not propagate to root
    caplog.set_level(logging.DEBUG, logger="neurosphere_api.authz.read_audit")
    try:
        yield caplog
    finally:
        logger.removeHandler(caplog.handler)


def _allow_records(world: World, chain: str) -> list[Any]:
    return [
        r
        for r in world.records(chain)
        if r.kind == "after" and r.outcome is not None and r.outcome.detail == ALLOW_DETAIL
    ]


def _dump(record: Any) -> str:
    return json.dumps(record.model_dump(mode="json"))


def test_query_appends_one_record_with_domains_and_count_only(world: World) -> None:
    body = {
        "asset_ids": [asset_id("customers")],
        "filters": {"classifications": [SENTINEL], "region_group": "eu"},
    }
    response = world.post(VIEWER, ACCESS, body)
    assert response.status_code == 200, response.text
    count = len(response.json()["rows"])
    records = _allow_records(world, FIN_CHAIN)
    assert len(records) == 1
    record = records[0]
    assert record.operation == "catalog.access_query"
    assert record.channel == "rest"
    assert record.subject.target.canonical_id == FINANCE
    assert record.subject.state_digest.root == sha256_digest(
        {"domain_ids": [FINANCE], "result_count": count}
    )
    dumped = _dump(record)
    assert SENTINEL not in dumped
    assert asset_id("customers") not in dumped
    for row in response.json()["rows"]:
        assert row["accessor_id"] not in dumped
    assert "Asset customers" not in dumped and "westeurope" not in dumped


def test_query_over_several_domains_uses_the_read_audit_chain(world: World) -> None:
    response = world.post(STEWARD_BOTH, ACCESS, {})
    assert response.status_code == 200
    count = len(response.json()["rows"])
    records = _allow_records(world, READ_CHAIN)
    assert len(records) == 1
    assert records[0].subject.state_digest.root == sha256_digest(
        {"domain_ids": sorted([FINANCE, OPERATIONS]), "result_count": count}
    )
    assert _allow_records(world, FIN_CHAIN) == []


def test_requested_out_of_scope_domain_is_not_recorded_as_read(world: World) -> None:
    body = {"filters": {"domain_ids": [FINANCE, OPERATIONS]}}
    response = world.post(VIEWER, ACCESS, body)
    assert response.status_code == 200
    count = len(response.json()["rows"])
    assert count > 0
    records = _allow_records(world, FIN_CHAIN)
    assert len(records) == 1
    assert records[0].subject.state_digest.root == sha256_digest(
        {"domain_ids": [FINANCE], "result_count": count}
    )


def test_dependents_appends_one_record(world: World) -> None:
    body = {"node_id": agent_id("fin-a2"), "max_depth": 2}
    response = world.post(VIEWER, DEPENDENTS, body)
    assert response.status_code == 200, response.text
    records = _allow_records(world, FIN_CHAIN)
    assert len(records) == 1
    assert records[0].operation == "catalog.dependents"
    assert records[0].subject.state_digest.root == sha256_digest(
        {"domain_ids": [FINANCE], "result_count": response.json()["total"]}
    )
    assert agent_id("fin-a2") not in _dump(records[0])


def test_region_groups_is_not_audited(world: World) -> None:
    assert world.get(VIEWER, REGION_GROUPS).status_code == 200
    assert _allow_records(world, FIN_CHAIN) == []
    assert _allow_records(world, READ_CHAIN) == []


def test_denied_and_invalid_requests_write_no_allowed_record(world: World) -> None:
    assert world.post(AUDITOR, ACCESS, {}).status_code == 403
    assert world.post(VIEWER, ACCESS, {"filters": {"region_group": "mars"}}).status_code == 422
    assert _allow_records(world, FIN_CHAIN) == []
    assert _allow_records(world, READ_CHAIN) == []


def test_failed_audit_write_is_logged_counted_and_changes_nothing(
    world: World, read_log: pytest.LogCaptureFixture
) -> None:
    body = {"asset_ids": [asset_id("customers")], "filters": {"classifications": [SENTINEL]}}
    baseline = world.post(VIEWER, ACCESS, body)
    assert baseline.status_code == 200

    class Failing(AuditRepository):
        def __init__(self) -> None:
            super().__init__(InMemoryAuditStore())

        async def append(self, chain_id: str, draft: Any) -> Any:  # type: ignore[override]
            raise ConnectionError("audit store down")

    world.h.app.state.audit_repository = Failing()
    response = world.post(VIEWER, ACCESS, body)
    assert response.status_code == 200
    assert response.json() == baseline.json()
    stats = getattr(world.h.app.state, STATS_ATTRIBUTE)
    assert isinstance(stats, ReadAuditStats)
    assert stats.snapshot() == {"audit_write_failed": 1}
    warnings = [r for r in read_log.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    rendered = warnings[0].getMessage() + repr(warnings[0].__dict__)
    assert SENTINEL not in rendered and FINANCE not in rendered


def test_unconfigured_audit_store_is_counted_never_blocks(world: World) -> None:
    del world.h.app.state.audit_repository
    body = {"node_id": agent_id("fin-a2"), "max_depth": 2}
    assert world.post(VIEWER, DEPENDENTS, body).status_code == 200
    stats = getattr(world.h.app.state, STATS_ATTRIBUTE)
    assert stats.snapshot() == {"audit_store_unconfigured": 1}
