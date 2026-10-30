"""Steward decision adapter for the browser (PRP-31 item 2), added to the
``/api/v1/catalog/domains`` router.

| Method | Path                                             | Permission                         |
|--------|--------------------------------------------------|------------------------------------|
| GET    | ``/{domain}/curation/edges/{edge_id}``           | ``data.read`` on ``{domain}``      |
| POST   | ``/{domain}/curation/edges/{edge_id}/decisions`` | ``catalog.curate`` on ``{domain}`` |

The GET returns the presented edge plus the stored ``edge_version``/``edge_etag`` (and an ``ETag``
header) a browser must echo as the decision's ``expected_edge_*`` preconditions.

The browser sends only the decision and its preconditions (:class:`CurationDecisionRequest`,
``extra="forbid"``). The server fills everything else before PRP-10's
``CurationService.decide(..., channel="button")`` sees it:

* ``edge_id``, ``relation_type``, ``cloud``, ``customer_id`` and ``domain_id`` from the STORED
  edge, loaded with the caller's scope. An edge that is missing, out of scope or not in
  ``{domain}`` is 404 (after the permission check on ``{domain}``, so 404 never reveals more than a
  caller who may curate ``{domain}`` could learn).
* ``actor`` and ``lock.actor`` from the authenticated principal. Only ``principal_kind: user`` may
  decide; any other kind is refused with 403 (``principal_not_user``) inside the permission
  dependency, so the refusal is recorded like every other denial.
* ``id`` (a fresh override id) and ``decided_at`` (server clock).

Preconditions, lock rules, actor verification, audit before/after/denied and immutable history
are the curation service's: a stale edge is 409 ``stale_edge``.

No ``from __future__ import annotations``: FastAPI inspects these signatures.
"""

import re
import uuid
from typing import Annotated, Any, Final

from fastapi import APIRouter, Depends, HTTPException, Path, Request, Response, status
from neurosphere_contracts.catalog.v1.edge_override import EdgeOverride
from neurosphere_core.auth.scope import Permission
from neurosphere_core.catalog import CatalogEdge, CatalogRepository, format_timestamp
from neurosphere_core.errors import ForbiddenError, InvalidSchemaError
from neurosphere_core.scope import IdentityScope
from pydantic import ValidationError

from neurosphere_api.authz import AuthzTarget, domain_from_path, require
from neurosphere_api.catalog.curation import (
    Clock,
    CurationService,
    DecisionResult,
    get_clock,
    get_repository,
    get_service,
)
from neurosphere_api.catalog.curation.router import audit_correlation_id
from neurosphere_api.middleware import correlation_id_of
from neurosphere_api.ui_adapters.catalog import DomainPath, ReadScope
from neurosphere_api.ui_adapters.models import CurationDecisionRequest, CurationEdgeView

__all__ = ["add_routes", "stamp_decision"]

_PINNING: Final = frozenset({"lock", "override"})
_OVERRIDE_SOURCE: Final = "neurosphere"
_SCHEMA_VERSION: Final = "1.0.0"
_PERSON_ID: Final = re.compile(r"^(commercial|government):[a-z0-9._-]+:[a-z0-9._-]+:person:")
_by_path = domain_from_path("domain")


def _caller_person(scope: IdentityScope) -> str:
    """The caller's principal id, when it is a user (a ``person`` id); else ``ForbiddenError``."""
    principal = scope.to_contract().principal
    if principal.principal_kind != "user":
        raise ForbiddenError(
            "only a user may record a steward decision", reason="principal_not_user"
        )
    principal_id = principal.principal_id.root
    if _PERSON_ID.match(principal_id) is None:
        raise ForbiddenError(
            "only a user may record a steward decision", reason="principal_not_user"
        )
    return principal_id


def _steward_domain(request: Request, scope: IdentityScope) -> AuthzTarget | None:
    """``{domain}`` from the path, for user principals only (refusals are recorded denials)."""
    _caller_person(scope)
    return _by_path(request, scope)


CurateScope = Annotated[
    IdentityScope, Depends(require(Permission.CATALOG_CURATE, resource=_steward_domain))
]
EdgeIdPath = Annotated[str, Path(min_length=1, max_length=512)]
Repository = Annotated[CatalogRepository, Depends(get_repository)]
Service = Annotated[CurationService, Depends(get_service)]
Now = Annotated[Clock, Depends(get_clock)]


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")


def stamp_decision(
    body: CurationDecisionRequest, edge: CatalogEdge, *, actor: str, decided_at: str
) -> EdgeOverride:
    """Assemble the full ``EdgeOverride`` from the browser's fields plus server-owned values."""
    if body.lock_expiry is not None and body.decision not in _PINNING:
        raise InvalidSchemaError(
            "lock_expiry applies to lock and override only", reason="lock_not_allowed"
        )
    raw: dict[str, Any] = {
        "schema_version": _SCHEMA_VERSION,
        "id": (
            f"{edge.cloud.root}:{edge.customer_id.root}:{_OVERRIDE_SOURCE}"
            f":edge_override:{uuid.uuid4().hex}"
        ),
        "edge_id": edge.id,
        "relation_type": edge.relation_type,
        "expected_edge_version": body.expected_edge_version,
        "expected_edge_etag": body.expected_edge_etag,
        "cloud": edge.cloud.root,
        "customer_id": edge.customer_id.root,
        "domain_id": edge.domain_id.root,
        "decision": body.decision,
        "actor": actor,
        "reason": body.reason,
        "decided_at": decided_at,
    }
    if body.decision in _PINNING:
        raw["lock"] = {
            "locked": True,
            "reason": body.reason,
            "expiry": body.lock_expiry,
            "actor": actor,
        }
    if body.set_confidence is not None:
        raw["set_confidence"] = body.set_confidence
    if body.set_validity is not None:
        raw["set_validity"] = body.set_validity.model_dump(exclude_none=True)
    try:
        return EdgeOverride.model_validate(raw)
    except ValidationError as exc:
        # For example an edge type the decision contract does not cover; value-free message.
        raise InvalidSchemaError(
            "the decision cannot be applied to this edge", reason="edge_not_curatable"
        ) from exc


def add_routes(router: APIRouter) -> None:
    """Add the edge read and decision routes to the ``/api/v1/catalog/domains`` adapter router."""

    @router.get(
        "/{domain}/curation/edges/{edge_id:path}",
        response_model=CurationEdgeView,
    )
    async def read_edge_in_domain(
        response: Response,
        domain: DomainPath,
        edge_id: EdgeIdPath,
        scope: ReadScope,
        repository: Repository,
        service: Service,
    ) -> CurationEdgeView:
        edge = await repository.get_edge(scope, edge_id)
        if edge is None or edge.domain_id.root != domain:
            raise _not_found()
        etag = edge.etag.root
        response.headers["ETag"] = etag
        return CurationEdgeView(
            edge=await service.presented(scope, edge),
            edge_version=edge.version.root,
            edge_etag=etag,
        )

    @router.post(
        "/{domain}/curation/edges/{edge_id:path}/decisions",
        response_model=DecisionResult,
        status_code=status.HTTP_201_CREATED,
    )
    async def decide_in_domain(
        request: Request,
        domain: DomainPath,
        edge_id: EdgeIdPath,
        body: CurationDecisionRequest,
        scope: CurateScope,
        repository: Repository,
        service: Service,
        clock: Now,
    ) -> DecisionResult:
        edge = await repository.get_edge(scope, edge_id)
        if edge is None or edge.domain_id.root != domain:
            raise _not_found()
        decision = stamp_decision(
            body,
            edge,
            actor=_caller_person(scope),
            decided_at=format_timestamp(clock()),
        )
        return await service.decide(
            scope,
            edge,
            decision,
            correlation_id=audit_correlation_id(correlation_id_of(request.scope)),
            channel="button",
        )
