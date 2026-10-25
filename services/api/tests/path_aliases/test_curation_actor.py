"""PRP-29 item 4 (Clarification 20): the curation decision ``actor`` is the authenticated
principal. A matching value is stamped and stored; any other value is refused with 403 on both
path forms and audited as a denial, and nothing is stored."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from authz.authz_helpers import (  # pyright: ignore[reportMissingImports]
    ALICE,
    BOB,
    FINANCE,
    Harness,
    harness,
    policy,
    principal_id_for,
    role,
)
from neurosphere_api.catalog.curation import get_clock, get_repository, get_review_queue
from neurosphere_contracts.catalog.v1.edge_override import EdgeOverride
from neurosphere_contracts.catalog.v1.invokes import InvokesRelation
from neurosphere_core.audit import AuditRepository, InMemoryAuditStore
from neurosphere_core.auth.scope import Role
from neurosphere_core.catalog import CatalogEdge, InMemoryReviewQueue
from neurosphere_core.scope import IdentityScope

from .alias_support import normalized

EDGE_ID = "commercial:contoso:neurosphere:invokes:e-0001"
CHAIN = "contoso.finance"
FORMS = ("/catalog/curation", "/api/v1/catalog/curation")
_EXAMPLES = Path(__file__).resolve().parents[4] / "packages/contracts/schemas/catalog/v1/examples"


def _edge() -> InvokesRelation:
    raw = json.loads((_EXAMPLES / "valid/invokes.inferred.json").read_text(encoding="utf-8"))
    raw.update(id=EDGE_ID, domain_id=FINANCE)
    return InvokesRelation.model_validate(raw)


class _Repo:
    """The three ``CatalogRepository`` calls the decision route makes, scope-filtered."""

    def __init__(self, edge: CatalogEdge) -> None:
        self.edge = edge
        self.overrides: list[EdgeOverride] = []

    def _visible(self, scope: IdentityScope) -> bool:
        return self.edge.domain_id.root in scope.allowed_domains

    async def get_edge(self, scope: IdentityScope, edge_id: str) -> CatalogEdge | None:
        return self.edge if edge_id == self.edge.id and self._visible(scope) else None

    async def list_overrides(self, scope: IdentityScope, edge_id: str) -> tuple[EdgeOverride, ...]:
        return tuple(self.overrides) if self._visible(scope) else ()

    async def put_override(self, scope: IdentityScope, override: EdgeOverride) -> EdgeOverride:
        self.overrides.append(override)
        return override


class _World:
    def __init__(self) -> None:
        self.h: Harness = harness(policy(ALICE, role(Role.DOMAIN_STEWARD, FINANCE)), routers={})
        self.repo = _Repo(_edge())
        self.audit = AuditRepository(InMemoryAuditStore())
        queue = InMemoryReviewQueue()
        app = self.h.app
        app.state.audit_repository = self.audit
        app.dependency_overrides[get_repository] = lambda: self.repo
        app.dependency_overrides[get_review_queue] = lambda: queue
        app.dependency_overrides[get_clock] = lambda: self.now

    def now(self) -> datetime:
        return datetime.fromtimestamp(self.h.clock.now, UTC)

    def decide(self, prefix: str, actor: str, ident: str = "ovr-1") -> Any:
        edge = self.repo.edge
        body = {
            "schema_version": "1.0.0",
            "id": f"commercial:contoso:neurosphere:edge_override:{ident}",
            "edge_id": edge.id,
            "relation_type": edge.relation_type,
            "expected_edge_version": edge.version.root,
            "expected_edge_etag": edge.etag.root,
            "cloud": "commercial",
            "customer_id": "contoso",
            "domain_id": edge.domain_id.root,
            "decision": "accept",
            "actor": actor,
            "reason": "steward accept",
            "decided_at": "2020-01-01T00:00:00Z",
        }
        return self.h.client.post(
            f"{prefix}/edges/{edge.id}/decisions", json=body, headers=self.h.auth(ALICE)
        )

    async def records(self) -> list[Any]:
        return list(await self.audit.read_range(CHAIN, start=0, limit=500))


@pytest.mark.parametrize("prefix", FORMS)
async def test_own_principal_as_actor_is_stamped_and_stored(prefix: str) -> None:
    world = _World()
    me = principal_id_for(ALICE)
    response = world.decide(prefix, me)
    assert response.status_code == 201
    assert response.json()["override"]["actor"] == me
    assert [o.actor.root for o in world.repo.overrides] == [me]
    assert [r.kind for r in await world.records()] == ["before", "after"]


@pytest.mark.parametrize("prefix", FORMS)
@pytest.mark.parametrize(
    "actor",
    [
        principal_id_for(BOB),
        "commercial:contoso:entra:person:psn_0123456789abcdef",
        principal_id_for(ALICE).replace("commercial:contoso:", "commercial:fabrikam:"),
    ],
    ids=["other-steward", "made-up-person", "own-pseudonym-other-customer"],
)
async def test_mismatched_actor_is_403_audited_and_not_stored(prefix: str, actor: str) -> None:
    world = _World()
    response = world.decide(prefix, actor)
    assert response.status_code == 403
    assert response.json()["reason"] == "actor_mismatch"
    assert world.repo.overrides == []
    records = await world.records()
    assert [r.kind for r in records] == ["denied"]
    denied = records[0]
    assert denied.denial is not None
    assert (denied.denial.code, denied.denial.reason) == ("forbidden", "actor_mismatch")
    assert denied.operation == "catalog.curate"
    assert denied.subject is not None
    assert denied.subject.target.canonical_id == EDGE_ID


def test_mismatch_answers_identically_on_both_forms() -> None:
    world = _World()
    other = principal_id_for(BOB)
    old, new = (world.decide(prefix, other) for prefix in FORMS)
    assert old.status_code == new.status_code == 403
    assert normalized(old.json()) == normalized(new.json())


def test_accepted_decision_on_the_alias_carries_the_successor_link() -> None:
    world = _World()
    response = world.decide(FORMS[0], principal_id_for(ALICE))
    assert response.status_code == 201
    assert response.headers["deprecation"] == "true"
    successor = f"/api/v1/catalog/curation/edges/{EDGE_ID}/decisions"
    assert response.headers["link"] == f'<{successor}>; rel="successor-version"'
