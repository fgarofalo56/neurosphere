"""Harness for curation tests: an in-test ``CatalogRepository`` fake, edge/decision builders and an
app wired with the PRP-06 authz harness. No network, no Cosmos; the fake is scope-filtered like
the protocol requires (out-of-scope edges read as missing)."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from authz.authz_helpers import (  # pyright: ignore[reportMissingImports]
    ALICE,
    BOB,
    CAROL,
    FINANCE,
    NOBODY,
    OPERATIONS,
    Harness,
    harness,
    policy,
    principal_id_for,
    role,
)
from neurosphere_api.catalog.curation import (
    build_router,
    get_clock,
    get_repository,
    get_review_queue,
)
from neurosphere_contracts.catalog.v1.edge_override import EdgeOverride
from neurosphere_contracts.catalog.v1.invokes import InvokesRelation
from neurosphere_core.audit import AuditRepository, InMemoryAuditStore
from neurosphere_core.auth.scope import Role
from neurosphere_core.catalog import (
    CatalogEdge,
    EdgeObservation,
    InMemoryReviewQueue,
)
from neurosphere_core.catalog.protocol import (
    AliasKey,
    CatalogEntity,
    EdgeFilter,
    EntityFilter,
)
from neurosphere_core.errors import ForbiddenError
from neurosphere_core.paging import Page, PageRequest
from neurosphere_core.scope import IdentityScope

PREFIX = "/catalog/curation"
EDGE_ID = "commercial:contoso:neurosphere:invokes:e-0001"
OPS_EDGE_ID = "commercial:contoso:neurosphere:invokes:e-0002"
PERSON = "commercial:contoso:entra:person:psn_0123456789abcdef"
SECURITY = "audit:sec-0042"
EXPIRY = "2027-03-01T00:00:00Z"
_EXAMPLES = Path(__file__).resolve().parents[4] / "packages/contracts/schemas/catalog/v1/examples"

#: Steward of FINANCE only (also a member of OPERATIONS and HR), viewer, auditor, steward of both.
STEWARD_FINANCE = ALICE
VIEWER = BOB
AUDITOR = CAROL
STEWARD_BOTH = NOBODY


def make_edge(edge_id: str = EDGE_ID, domain: str = FINANCE, **patch: Any) -> InvokesRelation:
    raw = json.loads((_EXAMPLES / "valid/invokes.inferred.json").read_text(encoding="utf-8"))
    raw.update(id=edge_id, domain_id=domain, **patch)
    return InvokesRelation.model_validate(raw)


def decision_body(
    decision: str,
    *,
    edge: CatalogEdge | None = None,
    ident: str = "ovr-1",
    **extra: Any,
) -> dict[str, Any]:
    edge = edge or make_edge()
    body: dict[str, Any] = {
        "schema_version": "1.0.0",
        "id": f"commercial:contoso:neurosphere:edge_override:{ident}",
        "edge_id": edge.id,
        "relation_type": edge.relation_type,
        "expected_edge_version": edge.version.root,
        "expected_edge_etag": edge.etag.root,
        "cloud": "commercial",
        "customer_id": "contoso",
        "domain_id": edge.domain_id.root,
        "decision": decision,
        "actor": PERSON,
        "reason": f"steward {decision}",
        "decided_at": "2020-01-01T00:00:00Z",
    }
    if decision in ("lock", "override"):
        body["lock"] = {"locked": True, "reason": "hold", "expiry": EXPIRY, "actor": PERSON}
    body.update(extra)
    return body


class FakeCatalogRepo:
    """Minimal ``CatalogRepository``: edges, overrides and observations, scope-filtered."""

    def __init__(self, *edges: CatalogEdge) -> None:
        self.edges: dict[str, CatalogEdge] = {e.id: e for e in edges}
        self.overrides: dict[str, list[EdgeOverride]] = {}
        self.observations: list[EdgeObservation] = []

    @staticmethod
    def _visible(scope: IdentityScope, edge: CatalogEdge) -> bool:
        return edge.domain_id.root in scope.allowed_domains

    async def get_entity(self, scope: IdentityScope, entity_id: str) -> CatalogEntity | None:
        return None

    async def create_entity(self, scope: IdentityScope, entity: CatalogEntity) -> CatalogEntity:
        raise NotImplementedError

    async def update_entity(
        self, scope: IdentityScope, entity: CatalogEntity, expected_etag: str
    ) -> CatalogEntity:
        raise NotImplementedError

    async def deprecate_entity(
        self, scope: IdentityScope, entity_id: str, expected_etag: str
    ) -> CatalogEntity:
        raise NotImplementedError

    async def list_entities(
        self, scope: IdentityScope, flt: EntityFilter, page: PageRequest
    ) -> Page[CatalogEntity]:
        return Page[CatalogEntity](items=())

    async def put_alias(self, scope: IdentityScope, alias: Any) -> Any:
        return alias

    async def resolve_alias(self, scope: IdentityScope, key: AliasKey) -> str | None:
        return None

    async def get_edge(self, scope: IdentityScope, edge_id: str) -> CatalogEdge | None:
        edge = self.edges.get(edge_id)
        return edge if edge is not None and self._visible(scope, edge) else None

    async def put_edge(
        self, scope: IdentityScope, edge: CatalogEdge, expected_etag: str | None
    ) -> CatalogEdge:
        current = self.edges.get(edge.id)
        if not self._visible(scope, edge):
            raise ForbiddenError("out of scope")
        if current is not None and expected_etag != current.etag.root:
            raise AssertionError("fake repo: etag mismatch")
        self.edges[edge.id] = edge
        return edge

    async def list_edges_by_node(
        self, scope: IdentityScope, node_id: str, direction: str, flt: EdgeFilter, page: PageRequest
    ) -> Page[CatalogEdge]:
        return Page[CatalogEdge](items=())

    async def record_observation(self, scope: IdentityScope, observation: EdgeObservation) -> bool:
        if any(o.id == observation.id for o in self.observations):
            return False
        self.observations.append(observation)
        return True

    async def list_observations(
        self, scope: IdentityScope, edge_id: str, page: PageRequest
    ) -> Page[EdgeObservation]:
        edge = self.edges.get(edge_id)
        audited = {
            d.root
            for r in scope.to_contract().roles
            if r.role == "security_auditor"
            for d in r.domain_ids
        }
        if edge is None or edge.domain_id.root not in audited:
            raise ForbiddenError("auditor scope required")
        found = [o for o in self.observations if o.edge_id == edge_id]
        return Page[EdgeObservation](items=tuple(found[: page.page_size]))

    async def put_override(self, scope: IdentityScope, override: EdgeOverride) -> EdgeOverride:
        edge = self.edges.get(override.edge_id)
        if edge is None or not self._visible(scope, edge):
            raise ForbiddenError("out of scope")
        stored = self.overrides.setdefault(override.edge_id, [])
        if all(o.id != override.id for o in stored):
            stored.append(override)
        return override

    async def list_overrides(self, scope: IdentityScope, edge_id: str) -> tuple[EdgeOverride, ...]:
        edge = self.edges.get(edge_id)
        if edge is None or not self._visible(scope, edge):
            return ()
        return tuple(self.overrides.get(edge_id, ()))

    async def list_overrides_for_edges(
        self, scope: IdentityScope, edge_ids: Sequence[str]
    ) -> dict[str, tuple[EdgeOverride, ...]]:
        return {e: await self.list_overrides(scope, e) for e in edge_ids}


@dataclass
class Curation:
    h: Harness
    repo: FakeCatalogRepo
    queue: InMemoryReviewQueue
    audit: AuditRepository

    def now(self) -> datetime:
        return datetime.fromtimestamp(self.h.clock.now, UTC)

    def post(self, who: str | None, edge: CatalogEdge, body: dict[str, Any]) -> Any:
        headers = self.h.auth(who) if who else {}
        if who and body.get("actor") == PERSON:
            # The server verifies the actor against the authenticated principal.
            me = principal_id_for(who)
            body = {**body, "actor": me}
            if isinstance(body.get("lock"), dict) and body["lock"].get("actor") == PERSON:
                body["lock"] = {**body["lock"], "actor": me}
        return self.h.client.post(f"{PREFIX}/edges/{edge.id}/decisions", json=body, headers=headers)

    def get(self, who: str | None, path: str) -> Any:
        headers = self.h.auth(who) if who else {}
        return self.h.client.get(f"{PREFIX}{path}", headers=headers)

    async def scope_of(self, who: str) -> IdentityScope:
        claims = await self.h.validator.authenticate(self.h.auth(who)["Authorization"])
        return (await self.h.deriver.derive(claims)).scope

    async def audit_records(self, chain: str = "contoso.finance") -> list[Any]:
        return list(await self.audit.read_range(chain, start=0, limit=500))


def make_curation(*edges: CatalogEdge) -> Curation:
    h = harness(
        policy(STEWARD_FINANCE, role(Role.DOMAIN_STEWARD, FINANCE)),
        policy(VIEWER, role(Role.VIEWER, FINANCE)),
        policy(AUDITOR, role(Role.SECURITY_AUDITOR, FINANCE)),
        policy(STEWARD_BOTH, role(Role.DOMAIN_STEWARD, FINANCE, OPERATIONS)),
        routers={PREFIX: build_router()},
    )
    repo = FakeCatalogRepo(*edges)
    queue = InMemoryReviewQueue()
    audit = AuditRepository(InMemoryAuditStore())
    curation = Curation(h=h, repo=repo, queue=queue, audit=audit)
    h.app.state.audit_repository = audit
    h.app.dependency_overrides[get_repository] = lambda: repo
    h.app.dependency_overrides[get_review_queue] = lambda: queue
    h.app.dependency_overrides[get_clock] = lambda: curation.now
    return curation
