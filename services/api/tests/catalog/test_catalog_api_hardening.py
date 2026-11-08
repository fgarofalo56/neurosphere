"""PRP-10 item 10 (#53, API parts of #56): lock-actor attribution, 403 before 422 on create,
stale-agent last-observed paging. One regression per bullet."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from authz.authz_helpers import (  # pyright: ignore[reportMissingImports]
    FINANCE,
    OPERATIONS,
    principal_id_for,
)
from catalog_api_helpers import (  # pyright: ignore[reportMissingImports]
    STEWARD_FINANCE as API_STEWARD,
)
from catalog_api_helpers import (  # pyright: ignore[reportMissingImports]
    agent_doc,
    make_api,
    make_edge,
)
from curation_helpers import (  # pyright: ignore[reportMissingImports]
    EDGE_ID,
    PERSON,
    STEWARD_FINANCE,
    decision_body,
    make_curation,
)
from curation_helpers import make_edge as curation_edge  # pyright: ignore[reportMissingImports]
from neurosphere_api.catalog.service import MAX_SCAN_PAGES, CatalogService
from neurosphere_core.audit import AuditRepository, InMemoryAuditStore
from neurosphere_core.catalog.repo.documents import parse_entity
from neurosphere_core.paging import Page

# 1. curation actor attribution covers lock.actor


def test_lock_actor_that_is_not_the_caller_is_refused() -> None:
    edge = curation_edge()
    c = make_curation(edge)
    me = principal_id_for(STEWARD_FINANCE)
    body = decision_body("lock", edge=edge, actor=me)
    assert body["lock"]["actor"] == PERSON  # somebody else
    refused = c.post(STEWARD_FINANCE, edge, body)
    assert refused.status_code == 403
    assert refused.json()["code"] == "forbidden"
    assert EDGE_ID not in c.repo.overrides


def test_lock_actor_is_stamped_from_the_principal() -> None:
    edge = curation_edge()
    c = make_curation(edge)
    me = principal_id_for(STEWARD_FINANCE)
    body = decision_body("lock", edge=edge, actor=me)
    body["lock"] = {**body["lock"], "actor": me}
    ok = c.post(STEWARD_FINANCE, edge, body)
    assert ok.status_code == 201, ok.text
    stored = c.repo.overrides[EDGE_ID][0]
    assert stored.actor.root == me
    assert stored.lock is not None
    assert stored.lock.actor is not None
    assert stored.lock.actor.root == me


# 6. create: 403 before schema feedback


def test_out_of_scope_create_gets_403_without_schema_feedback() -> None:
    api = make_api()
    broken_elsewhere = {"entity_type": "agent", "id": "nope", "domain_id": OPERATIONS}
    denied = api.post(API_STEWARD, "/entities", broken_elsewhere)
    assert denied.status_code == 403
    assert denied.json()["code"] == "forbidden"
    assert denied.json()["detail"] == "the target domain is outside the caller's scope"
    no_domain = api.post(API_STEWARD, "/entities", {"entity_type": "agent", "id": "nope"})
    assert no_domain.status_code == 403
    # an in-scope caller still gets the contract error
    in_scope = api.post(
        API_STEWARD, "/entities", {"entity_type": "agent", "id": "nope", "domain_id": FINANCE}
    )
    assert in_scope.status_code == 422
    assert in_scope.json()["code"] == "invalid_schema"
    # a valid document for an out-of-scope domain is refused the same way
    valid_elsewhere = api.post(API_STEWARD, "/entities", agent_doc("x-bot", OPERATIONS))
    assert valid_elsewhere.status_code == 403


# 7. stale-agent reconcile pages every edge


class _PagedEdges:
    """Repository stub: one edge per page, so the newest edge is on the last page."""

    def __init__(self, pages: list[Any], *, endless: bool = False) -> None:
        self.pages = pages
        self.endless = endless
        self.requested = 0

    async def list_edges_by_node(
        self, scope: Any, node_id: str, direction: str, flt: Any, page: Any
    ) -> Page[Any]:
        index = int(page.cursor) if page.cursor else 0
        self.requested += 1
        edge = self.pages[index % len(self.pages)]
        more = self.endless or index + 1 < len(self.pages)
        return Page(items=(edge,), next_cursor=str(index + 1) if more else None)


def _service(repo: Any, now: datetime) -> CatalogService:
    return CatalogService(repo, AuditRepository(InMemoryAuditStore()), lambda: now)


async def test_last_observed_reads_past_the_first_edge_page() -> None:
    agent = parse_entity(agent_doc("busy", FINANCE))
    old = make_edge("old", "busy", "busy", FINANCE, last_observed="2026-01-01T00:00:00Z")
    new = make_edge("new", "busy", "busy", FINANCE, last_observed="2027-01-10T00:00:00Z")
    repo = _PagedEdges([old, old, new])
    now = datetime(2027, 1, 15, tzinfo=UTC)
    seen = await _service(repo, now)._last_observed(  # pyright: ignore[reportPrivateUsage]
        object(),  # type: ignore[arg-type]
        agent,
    )
    assert seen == datetime(2027, 1, 10, tzinfo=UTC)
    assert repo.requested == 3


async def test_last_observed_that_cannot_be_exhausted_is_never_stale() -> None:
    agent = parse_entity(agent_doc("hub", FINANCE))
    old = make_edge("old", "hub", "hub", FINANCE, last_observed="2026-01-01T00:00:00Z")
    repo = _PagedEdges([old], endless=True)
    now = datetime(2027, 1, 15, tzinfo=UTC)
    seen = await _service(repo, now)._last_observed(  # pyright: ignore[reportPrivateUsage]
        object(),  # type: ignore[arg-type]
        agent,
    )
    assert seen == now  # not provably stale: reported as observed now
    assert repo.requested == MAX_SCAN_PAGES
