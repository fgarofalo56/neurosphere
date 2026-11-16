"""Allowed-read audit on both catalog search routes (PRP-48 item 4, #69)."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from typing import Any

import pytest
from authz.authz_helpers import (  # pyright: ignore[reportMissingImports]
    FINANCE,
    OPERATIONS,
    principal_id_for,
)
from neurosphere_api.authz.read_audit import (
    STATS_ATTRIBUTE,
    ReadAuditStats,
    read_audit_chain_id,
)
from neurosphere_core.audit import ALLOW_DETAIL, sha256_digest
from ui_adapters_api.adapter_support import (  # pyright: ignore[reportMissingImports]
    STEWARD_BOTH,
    VIEWER,
    World,
    agent_doc,
    make_world,
)

DOMAIN_SEARCH = "/api/v1/catalog/domains/{domain}/search"
SEARCH = "/api/v1/catalog/search"
BUDGET = {"timeout_ms": 1000, "limit": 10, "max_depth": 0}
#: A term that must never reach an audit record.
SENTINEL = "zq-sentinel-term-48"
FIN_CHAIN = "contoso.finance"
READ_CHAIN = read_audit_chain_id("contoso")


@pytest.fixture
def world() -> World:
    w = make_world()
    w.seed(
        agent_doc("fin-bot", FINANCE),
        agent_doc("fin-helper", FINANCE),
        agent_doc("ops-bot", OPERATIONS),
    )
    w.reindex()
    return w


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


def _pseudonym(object_id: str) -> str:
    return principal_id_for(object_id).rsplit(":", 1)[-1]


def test_domain_search_appends_one_allowed_record(world: World) -> None:
    body = {"term": SENTINEL, "budget": BUDGET}
    response = world.post(VIEWER, DOMAIN_SEARCH.format(domain=FINANCE), body)
    assert response.status_code == 200, response.text
    count = len(response.json()["nodes"])
    records = _allow_records(world, FIN_CHAIN)
    assert len(records) == 1
    record = records[0]
    assert record.operation == "catalog.domain_search"
    assert record.channel == "rest"
    assert record.actor.principal_pseudonym == _pseudonym(VIEWER)
    assert record.subject.target.canonical_id == FINANCE
    assert record.subject.target.entity_type == "domain"
    assert record.subject.state_digest.root == sha256_digest(
        {"domain_ids": [FINANCE], "result_count": count}
    )
    assert SENTINEL not in _dump(record)


def test_matching_rows_never_reach_the_record(world: World) -> None:
    body = {"term": "bot", "budget": BUDGET}
    response = world.post(VIEWER, DOMAIN_SEARCH.format(domain=FINANCE), body)
    assert response.status_code == 200
    ids = [n["id"] for n in response.json()["nodes"]]
    assert ids, "the search must match something for this test to mean anything"
    dumped = _dump(_allow_records(world, FIN_CHAIN)[0])
    for entity_id in ids:
        assert entity_id not in dumped
    assert '"bot"' not in dumped


def test_collection_search_on_one_domain_uses_the_domain_chain(world: World) -> None:
    body = {"term": SENTINEL, "filters": {"domain_ids": [FINANCE]}, "budget": BUDGET}
    response = world.post(VIEWER, SEARCH, body)
    assert response.status_code == 200, response.text
    records = _allow_records(world, FIN_CHAIN)
    assert len(records) == 1
    assert records[0].operation == "catalog.search"
    assert SENTINEL not in _dump(records[0])


def test_collection_search_over_several_domains_uses_the_read_audit_chain(world: World) -> None:
    body = {"term": "bot", "budget": BUDGET}
    response = world.post(STEWARD_BOTH, SEARCH, body)
    assert response.status_code == 200, response.text
    count = len(response.json()["nodes"])
    records = _allow_records(world, READ_CHAIN)
    assert len(records) == 1
    subject = records[0].subject
    assert subject.target.entity_type == "service"
    assert subject.state_digest.root == sha256_digest(
        {"domain_ids": sorted([FINANCE, OPERATIONS]), "result_count": count}
    )
    assert _allow_records(world, FIN_CHAIN) == []


def test_requested_out_of_scope_domains_are_not_recorded_as_read(world: World) -> None:
    body = {"term": "bot", "filters": {"domain_ids": [FINANCE, OPERATIONS]}, "budget": BUDGET}
    response = world.post(VIEWER, SEARCH, body)
    assert response.status_code == 200, response.text
    count = len(response.json()["nodes"])
    records = _allow_records(world, FIN_CHAIN)
    assert len(records) == 1  # OPERATIONS was asked for but never readable
    assert records[0].subject.state_digest.root == sha256_digest(
        {"domain_ids": [FINANCE], "result_count": count}
    )


def test_denied_search_writes_no_allowed_record(world: World) -> None:
    body = {"term": "bot", "budget": BUDGET}
    response = world.post(VIEWER, DOMAIN_SEARCH.format(domain=OPERATIONS), body)
    assert response.status_code == 403
    assert _allow_records(world, "contoso.operations") == []
    assert _allow_records(world, READ_CHAIN) == []


def test_failed_audit_write_is_logged_and_counted_never_blocks(
    world: World, read_log: pytest.LogCaptureFixture
) -> None:
    from neurosphere_core.audit import AuditRepository, InMemoryAuditStore

    class Failing(AuditRepository):
        def __init__(self) -> None:
            super().__init__(InMemoryAuditStore())

        async def append(self, chain_id: str, draft: Any) -> Any:  # type: ignore[override]
            raise ConnectionError("audit store down")

    world.h.app.state.audit_repository = Failing()
    body = {"term": SENTINEL, "budget": BUDGET}
    response = world.post(VIEWER, DOMAIN_SEARCH.format(domain=FINANCE), body)
    assert response.status_code == 200, response.text
    stats = getattr(world.h.app.state, STATS_ATTRIBUTE)
    assert isinstance(stats, ReadAuditStats)
    assert stats.snapshot() == {"audit_write_failed": 1}
    warnings = [r for r in read_log.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    rendered = warnings[0].getMessage() + repr(warnings[0].__dict__)
    assert SENTINEL not in rendered and FINANCE not in rendered


def test_unconfigured_audit_store_is_counted_never_blocks(world: World) -> None:
    del world.h.app.state.audit_repository
    body = {"term": "bot", "budget": BUDGET}
    response = world.post(VIEWER, DOMAIN_SEARCH.format(domain=FINANCE), body)
    assert response.status_code == 200
    stats = getattr(world.h.app.state, STATS_ATTRIBUTE)
    assert stats.snapshot() == {"audit_store_unconfigured": 1}
