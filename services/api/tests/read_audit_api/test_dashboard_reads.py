"""Allowed-read audit on the dashboards route (PRP-48 item 4, #69)."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from neurosphere_api.authz import route_inventory
from neurosphere_api.authz.read_audit import STATS_ATTRIBUTE
from neurosphere_api.dashboards.tests.support import (
    ALICE,
    FINANCE,
    METRICS,
    OPERATIONS,
    Api,
    cost_point,
    make_api,
)
from neurosphere_core.audit import (
    ALLOW_DETAIL,
    AuditRepository,
    InMemoryAuditStore,
    sha256_digest,
)

FIN_CHAIN = "contoso.finance"


def _with_audit() -> tuple[Api, AuditRepository]:
    api = make_api()
    repository = AuditRepository(InMemoryAuditStore())
    api.h.app.state.audit_repository = repository
    return api, repository


def _records(repository: AuditRepository, chain: str) -> list[Any]:
    return list(asyncio.run(repository.read_range(chain, start=0, limit=100)))


@pytest.mark.parametrize("metric", METRICS)
def test_allowed_dashboard_read_appends_one_record(metric: str) -> None:
    api, repository = _with_audit()
    api.seed(cost_point(FINANCE, 1, "31337.42"))
    response = api.get(ALICE, FINANCE, metric)
    assert response.status_code == 200, response.text
    series = len(response.json()["series"])
    records = _records(repository, FIN_CHAIN)
    assert len(records) == 1
    record = records[0]
    assert record.kind == "after"
    assert record.outcome.detail == ALLOW_DETAIL
    assert record.operation == "dashboard.read"
    assert record.subject.target.canonical_id == FINANCE
    assert record.subject.state_digest.root == sha256_digest(
        {"domain_ids": [FINANCE], "result_count": series}
    )
    dumped = json.dumps(record.model_dump(mode="json"))
    assert "31337" not in dumped  # no row values


def test_denied_dashboard_read_writes_no_allowed_record() -> None:
    api, repository = _with_audit()
    assert api.get(ALICE, OPERATIONS, "cost").status_code == 403
    assert _records(repository, "contoso.operations") == []


def test_audit_failure_never_blocks_the_dashboard() -> None:
    api = make_api()  # no audit repository installed
    response = api.get(ALICE, FINANCE, "cost")
    assert response.status_code == 200
    stats = getattr(api.h.app.state, STATS_ATTRIBUTE)
    assert stats.snapshot() == {"audit_store_unconfigured": 1}


def test_route_inventory_still_declares_data_read() -> None:
    api = make_api()
    entries = {e.path: e.permissions for e in route_inventory(api.h.app)}
    assert entries["/api/v1/dashboards/domains/{domain}/{metric}"] == ("data.read",)
