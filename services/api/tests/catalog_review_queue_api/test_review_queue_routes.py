"""PRP-43 item 6: list and resolve routes for the relationship review queue."""

from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import quote

import pytest
from authz.authz_helpers import FINANCE, OPERATIONS  # pyright: ignore[reportMissingImports]
from neurosphere_core.catalog import ReviewItem
from ui_adapters_api.adapter_support import (  # pyright: ignore[reportMissingImports]
    STEWARD,
    STEWARD_BOTH,
    VIEWER,
    World,
    make_world,
)

BASE = "/api/v1/catalog/curation/review-queue"
EVIDENCE = "evidence-marker-should-never-be-audited"


def _item(item_id: str, domain: str, at: str = "2026-10-17T10:00:00Z") -> ReviewItem:
    return ReviewItem(
        id=item_id,
        edge_id=f"commercial:contoso:neurosphere:invokes:edge-{item_id}",
        relation_type="invokes",
        cloud="commercial",
        customer_id="contoso",
        domain_id=domain,
        reason="conflicts_with_lock",
        governing_override_id=f"commercial:contoso:neurosphere:edge_override:lock-{item_id}",
        observed_confidence=0.4,
        presented_confidence=0.9,
        new_evidence_ids=[EVIDENCE],
        created_at=at,
    )


@pytest.fixture
def world() -> World:
    w = make_world()

    async def seed() -> None:
        scope = await w.scope_of(STEWARD_BOTH)
        await w.queue.enqueue(scope, _item("fin-1", FINANCE, "2026-10-17T09:00:00Z"))
        await w.queue.enqueue(scope, _item("fin-2", FINANCE, "2026-10-17T10:00:00Z"))
        await w.queue.enqueue(scope, _item("ops-1", OPERATIONS))

    asyncio.run(seed())
    return w


def _resolve(world: World, who: str | None, item_id: str, body: Any) -> Any:
    return world.post(who, f"{BASE}/{quote(item_id, safe='')}/resolve", body)


def test_list_returns_open_items_in_the_callers_domains_oldest_first(world: World) -> None:
    response = world.get(STEWARD, BASE)
    assert response.status_code == 200, response.text
    assert [i["id"] for i in response.json()["items"]] == ["fin-1", "fin-2"]
    both = world.get(STEWARD_BOTH, BASE)
    assert {i["id"] for i in both.json()["items"]} == {"fin-1", "fin-2", "ops-1"}


def test_list_without_curate_is_403_and_unauthenticated_is_401(world: World) -> None:
    assert world.get(VIEWER, BASE).status_code == 403
    assert world.get(None, BASE).status_code == 401


def test_resolve_stamps_the_caller_and_audits_without_evidence(world: World) -> None:
    response = _resolve(world, STEWARD, "fin-1", {"resolution": "kept_curation"})
    assert response.status_code == 200, response.text
    stored = response.json()
    assert stored["status"] == "resolved"
    assert stored["resolution"] == "kept_curation"
    assert stored["resolved_by"].startswith("commercial:contoso:")
    assert stored["resolved_at"]
    assert [i["id"] for i in world.get(STEWARD, BASE).json()["items"]] == ["fin-2"]
    records = [r for r in world.records() if r.operation == "catalog.review_resolve"]
    assert [r.kind for r in records] == ["before", "after"]
    assert {r.channel for r in records} == {"rest"}
    assert EVIDENCE not in " ".join(r.model_dump_json() for r in records)
    assert any("item=fin-1" in r.model_dump_json() for r in records)


def test_resolving_twice_is_idempotent(world: World) -> None:
    first = _resolve(world, STEWARD, "fin-1", {"resolution": "accepted_inference"})
    second = _resolve(world, STEWARD, "fin-1", {"resolution": "kept_curation"})
    assert first.status_code == second.status_code == 200
    assert second.json() == first.json()
    records = [r for r in world.records() if r.operation == "catalog.review_resolve"]
    assert len(records) == 2  # one before/after pair only


def test_client_cannot_name_the_resolver(world: World) -> None:
    body = {"resolution": "kept_curation", "resolved_by": "someone-else"}
    assert _resolve(world, STEWARD, "fin-1", body).status_code == 422
    assert _resolve(world, STEWARD, "fin-1", {"resolution": "nonsense"}).status_code == 422


def test_viewer_cannot_resolve(world: World) -> None:
    assert _resolve(world, VIEWER, "fin-1", {"resolution": "kept_curation"}).status_code == 403
    assert _resolve(world, None, "fin-1", {"resolution": "kept_curation"}).status_code == 401


def test_out_of_scope_and_missing_items_answer_the_same_404(world: World) -> None:
    out_of_scope = _resolve(world, STEWARD, "ops-1", {"resolution": "kept_curation"})
    missing = _resolve(world, STEWARD, "no-such-item", {"resolution": "kept_curation"})
    assert out_of_scope.status_code == missing.status_code == 404
    assert out_of_scope.json()["code"] == missing.json()["code"] == "not_found"
    assert out_of_scope.json()["detail"] == missing.json()["detail"]
    still_open = world.get(STEWARD_BOTH, BASE).json()["items"]
    assert "ops-1" in {i["id"] for i in still_open}
