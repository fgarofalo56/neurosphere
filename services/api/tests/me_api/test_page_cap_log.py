"""PRP-48 item 2 (#91): ``/me/domains`` page-cap warning and the documented empty 200."""

from __future__ import annotations

import logging
from collections.abc import Iterator

import pytest
from authz.authz_helpers import (  # pyright: ignore[reportMissingImports]
    AGENT,
    ALICE,
    BOB,
    FINANCE,
    OPERATIONS,
    grant,
    harness,
    policy,
    role,
)
from neurosphere_api.app import create_app
from neurosphere_api.me import router as me_router
from neurosphere_core.auth.scope import Role
from neurosphere_core.catalog import EntityFilter
from neurosphere_core.catalog.repo import InMemoryCatalogRepository
from neurosphere_core.cloud import Settings
from neurosphere_core.paging import Page, PageRequest
from neurosphere_core.scope import IdentityScope

URL = "/api/v1/me/domains"


class _EndlessCatalog(InMemoryCatalogRepository):
    """Every page claims there is another one, so the lookup always reaches the cap."""

    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    async def list_entities(  # type: ignore[override]
        self, scope: IdentityScope, flt: EntityFilter, page: PageRequest
    ) -> Page[object]:
        self.calls += 1
        return Page[object](items=(), next_cursor=f"c{self.calls}")


@pytest.fixture
def me_log(caplog: pytest.LogCaptureFixture) -> Iterator[pytest.LogCaptureFixture]:
    logger = logging.getLogger("neurosphere_api.me")
    logger.addHandler(caplog.handler)  # the JSON logger does not propagate to root
    caplog.set_level(logging.WARNING, logger="neurosphere_api.me")
    try:
        yield caplog
    finally:
        logger.removeHandler(caplog.handler)


def test_page_cap_logs_one_warning_with_the_domain_count_only(
    me_log: pytest.LogCaptureFixture,
) -> None:
    h = harness(policy(ALICE, role(Role.VIEWER, FINANCE), role(Role.ANALYST, OPERATIONS)))
    catalog = _EndlessCatalog()
    h.app.state.catalog_repository = catalog
    response = h.client.get(URL, headers=h.auth(ALICE))
    assert response.status_code == 200
    assert {i["display_name_source"] for i in response.json()["items"]} == {"derived"}
    assert catalog.calls == me_router._MAX_CATALOG_PAGES  # pyright: ignore[reportPrivateUsage]
    warnings = [r for r in me_log.records if r.name == "neurosphere_api.me"]
    assert len(warnings) == 1
    record = warnings[0]
    assert record.levelno == logging.WARNING
    assert getattr(record, "domain_count", None) == 2
    rendered = record.getMessage() + repr(record.__dict__.get("domain_count"))
    for domain in (FINANCE, OPERATIONS, "finance", "operations"):
        assert domain not in rendered


def test_lookup_within_the_cap_logs_nothing(me_log: pytest.LogCaptureFixture) -> None:
    h = harness(policy(ALICE, role(Role.VIEWER, FINANCE)))
    h.app.state.catalog_repository = InMemoryCatalogRepository()
    assert h.client.get(URL, headers=h.auth(ALICE)).status_code == 200
    assert [r for r in me_log.records if r.name == "neurosphere_api.me"] == []


def test_resource_grant_only_caller_gets_an_empty_200() -> None:
    h = harness(policy(BOB, grants=(grant(AGENT, "read"),)))
    response = h.client.get(URL, headers=h.auth(BOB))
    assert response.status_code == 200
    assert response.json() == {"items": []}


def test_openapi_documents_the_empty_200() -> None:
    operation = create_app(Settings(env="local")).openapi()["paths"][URL]["get"]
    description = operation["description"]
    assert "resource-scoped grant" in description
    assert "200 with an empty `items` list" in description
