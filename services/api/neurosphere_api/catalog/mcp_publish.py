"""Publish and unpublish a catalog MCP server through a registered gateway (PRP-34 item 6).

Mounted at ``/api/v1/catalog/mcp-servers`` (registered by ``catalog.router.register``):

| Method | Path                                         | Permission (stored entity's domain) |
|--------|----------------------------------------------|-------------------------------------|
| GET    | ``/{entity_id}/publication``                 | ``data.read``                       |
| POST   | ``/{entity_id}/publish``                     | ``action.propose``                  |
| POST   | ``/{entity_id}/unpublish``                   | ``action.propose``                  |
| POST   | ``/{entity_id}/publication-record``          | ``action.propose``                  |

``publish`` and ``unpublish`` never touch the gateway: they DRAFT an ``mcp_server_publish`` or
``mcp_server_unpublish`` action intent through the one action plane (same ``ActionApi.draft`` as
``POST /api/v1/actions/.../intents``), so validate, confirmation, maker-checker approval and the
executor worker apply exactly as for any other action. The APIM connector's ``mcp_server``
translator plans and applies the stage; it is the authority on every refusal, the route only
refuses early what can never succeed.

Stages (deny first): an unpublished server is published in one ``publish`` stage. A published
server is changed or removed in two intents: a ``deny`` stage (API policy := 503), then, once the
deny is recorded, a ``change`` (publish route) or ``remove`` (unpublish route) stage. The
connector plans a change or removal only against a denied API, and a failed change or removal
reverses to the deny, never to the old enforcement.

``publication-record`` records a SUCCEEDED, verified publication intent on the catalog
``McpServer``: ``provenance`` names the gateway (``source_id = apim-gateway.<gateway id>``) and the
recording time, and ``attributes`` carry the state, the gateway id, the API path and the
ownership of every gateway resource (``created`` per-server resources, ``shared`` metadata API).
It is a catalog write recording a real, verified gateway change, never a stand-in for one: it
refuses an intent that did not succeed, did not verify, names another server, was drafted against
another publication state, or was applied before the last record (a superseded change). The
McpServer schema is unchanged
(``provenance`` is closed, so the detail lives in the schema's ``attributes`` extension point).

Grants: the enforcement admits only callers with a direct (``oid``) grant on the server that is
enabled, active and in its validity window, read with the caller's own scope; ``entra_group``
grants are not enforced (groups-claim overage would fail closed) and are reported in
``diagnostics``. Diagnostics always state that MCP APIs log zero body bytes.

No ``from __future__ import annotations``: FastAPI inspects these signatures.
"""

import hashlib
from collections.abc import Mapping
from datetime import datetime
from typing import Annotated, Any, Final, Literal, cast

from fastapi import APIRouter, Depends, Request, Response
from neurosphere_contracts.actions.v1.action_intent import ProposedDiff
from neurosphere_contracts.actions.v1.target_ref import TargetRef
from neurosphere_core.auth.scope import Permission
from neurosphere_core.catalog import CatalogEntity, CatalogRepository, EntityFilter
from neurosphere_core.catalog.repo.documents import dump
from neurosphere_core.catalog.rules import format_timestamp, parse_timestamp
from neurosphere_core.errors import (
    CapabilityUnavailableError,
    InvalidSchemaError,
    StaleVersionError,
)
from neurosphere_core.gateway.mode import GATEWAY_NOT_REGISTERED
from neurosphere_core.gateway.models import GATEWAY_ID_PATTERN
from neurosphere_core.paging import PageRequest
from neurosphere_core.paging.models import MAX_PAGE_SIZE
from pydantic import BaseModel, ConfigDict, Field

from neurosphere_api.actions.dependencies import ActionPlane, get_action_plane
from neurosphere_api.actions.models import ActionView, Channel, DraftIntentBody
from neurosphere_api.actions.service import ActionApi
from neurosphere_api.catalog.curation.dependencies import get_clock, get_repository
from neurosphere_api.catalog.curation.router import audit_correlation_id
from neurosphere_api.catalog.curation.service import Clock
from neurosphere_api.catalog.dependencies import EntityAccess, entity_access, get_service
from neurosphere_api.catalog.service import CatalogService
from neurosphere_api.gateway.dependencies import GatewayPlane, get_gateway_plane
from neurosphere_api.middleware import correlation_id_of

__all__ = [
    "BODY_BYTES_NOTE",
    "MCP_PUBLISH_PREFIX",
    "McpPublicationDraft",
    "McpPublicationRecordBody",
    "McpPublicationStatus",
    "McpPublishBody",
    "McpUnpublishBody",
    "build_mcp_publish_router",
    "publication_prefix",
    "publication_resources",
]

MCP_PUBLISH_PREFIX: Final = "/api/v1/catalog/mcp-servers"
PUBLISH_KIND: Final = "mcp_server_publish"
UNPUBLISH_KIND: Final = "mcp_server_unpublish"
ENTITY_TYPE: Final = "mcp_server"
#: Mirrors of the APIM connector's ``mcp`` module (the API does not import connectors; a test
#: asserts both sides agree).
METADATA_API: Final = "ns-mcp-metadata"
TENANT_NAMED_VALUE: Final = "ns-mcp-tenant-id"
STAGE_VERSIONS: Final[Mapping[str, str]] = {
    "publish": "mcp-absent",
    "deny": "mcp-published",
    "change": "mcp-denied",
    "remove": "mcp-denied",
}
STATE_VERSIONS: Final[Mapping[str, str]] = {
    "unpublished": "mcp-absent",
    "published": "mcp-published",
    "denied": "mcp-denied",
}
_AFTER: Final[Mapping[str, str]] = {
    "publish": "published",
    "deny": "denied",
    "change": "published",
    "remove": "unpublished",
}
_KIND_STAGES: Final[Mapping[str, frozenset[str]]] = {
    PUBLISH_KIND: frozenset({"publish", "deny", "change"}),
    UNPUBLISH_KIND: frozenset({"deny", "remove"}),
}
_PUBLISH_STAGE: Final[Mapping[str, str]] = {
    "unpublished": "publish",
    "published": "deny",
    "denied": "change",
}
_UNPUBLISH_STAGE: Final[Mapping[str, str | None]] = {
    "unpublished": None,
    "published": "deny",
    "denied": "remove",
}
CONNECTOR_SOURCE: Final = "apim-gateway"
CONNECTOR_VERSION: Final = "0.1.0"
_ATTR: Final = "mcp_publication_"
_MAX_GRANT_PAGES: Final = 20
_API_PATH = r"^[a-z0-9][a-z0-9-]{0,62}$"
_NAMED_VALUE = r"^[A-Za-z0-9._-]{1,256}$"
_UUID = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"

BODY_BYTES_NOTE: Final = (
    "MCP APIs log zero body bytes: no gateway policy of this publication reads a request or "
    "response body, forwarding is unbuffered (streamable HTTP), and gateway diagnostics for MCP "
    "APIs must keep payload logging at 0 bytes."
)
_DENY_NOTE: Final = (
    "Deny first: this stage replaces the MCP API policy with a 503 deny. Record it, then draft "
    "the change or removal; a failed change or removal leaves the deny in place."
)
_NAMED_VALUES_NOTE: Final = (
    "Named values {tenant} (Entra tenant id) and {audience} (token audience) must exist on the "
    "gateway; NeuroSphere references them and never writes their values."
)

Stage = Literal["publish", "deny", "change", "remove"]
State = Literal["unpublished", "published", "denied"]

ReadAccess = Annotated[EntityAccess, Depends(entity_access(Permission.DATA_READ))]
ProposeAccess = Annotated[EntityAccess, Depends(entity_access(Permission.ACTION_PROPOSE))]
Actions = Annotated[ActionPlane, Depends(get_action_plane)]
Gateways = Annotated[GatewayPlane, Depends(get_gateway_plane)]
Repository = Annotated[CatalogRepository, Depends(get_repository)]
Service = Annotated[CatalogService, Depends(get_service)]
ClockDep = Annotated[Clock, Depends(get_clock)]
IdempotencyKey = Annotated[str, Field(pattern=r"^[A-Za-z0-9._:-]{16,128}$")]


# -- naming (mirrors the connector) -----------------------------------------------------------


def publication_prefix(server_id: str) -> str:
    """Resource-name prefix of one catalog MCP server on a gateway (``ns-mcp-`` + 16 hex)."""
    return "ns-mcp-" + hashlib.sha256(server_id.encode("utf-8")).hexdigest()[:16]


def publication_resources(server_id: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """``(created per-server resources, shared resources)`` as relative ARM paths."""
    prefix = publication_prefix(server_id)
    created = (
        f"backends/{prefix}",
        f"policyFragments/{prefix}-enforce",
        f"apis/{prefix}",
        f"apis/{METADATA_API}/operations/{prefix}-prm",
        f"apis/{prefix}/policies/policy",
    )
    shared = (f"apis/{METADATA_API}", f"apis/{METADATA_API}/policies/policy")
    return created, shared


# -- bodies and views -------------------------------------------------------------------------


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class McpPublishBody(_Body):
    """``POST .../publish``. The gateway, path and audience named value are needed only for the
    first publication; later stages reuse what the catalog recorded."""

    gateway_id: Annotated[str | None, Field(pattern=GATEWAY_ID_PATTERN)] = None
    api_path: Annotated[str | None, Field(pattern=_API_PATH)] = None
    audience_named_value: Annotated[str | None, Field(pattern=_NAMED_VALUE)] = None
    idempotency_key: IdempotencyKey
    channel: Channel = "rest"


class McpUnpublishBody(_Body):
    idempotency_key: IdempotencyKey
    channel: Channel = "rest"


class McpPublicationRecordBody(_Body):
    """``POST .../publication-record``: the succeeded intent whose outcome is recorded."""

    intent_id: Annotated[str, Field(pattern=_UUID)]


class McpPublicationDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: ActionView
    stage: Stage
    state: State
    diagnostics: list[str]


class McpPublicationStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    server_id: str
    state: State
    gateway_id: str | None
    api_path: str | None
    created_resources: list[str]
    shared_resources: list[str]
    next_publish_stage: Stage | None
    next_unpublish_stage: Stage | None
    diagnostics: list[str]


# -- helpers ----------------------------------------------------------------------------------


def _bad(reason: str, detail: str) -> InvalidSchemaError:
    return InvalidSchemaError(detail, reason=reason)


def _server(entity: CatalogEntity) -> dict[str, Any]:
    doc = dump(entity)
    if doc.get("entity_type") != ENTITY_TYPE:
        raise _bad("not_mcp_server", "the entity is not an MCP server")
    return doc


def _attributes(doc: Mapping[str, Any]) -> dict[str, Any]:
    raw = doc.get("attributes")
    return dict(cast(Mapping[str, Any], raw)) if isinstance(raw, Mapping) else {}


def _attr(doc: Mapping[str, Any], key: str) -> str | None:
    value = _attributes(doc).get(_ATTR + key)
    return value if isinstance(value, str) and value else None


def _state(doc: Mapping[str, Any]) -> State:
    value = _attr(doc, "state")
    if value in ("published", "denied"):
        return cast(State, value)
    return "unpublished"


def _split(value: str | None) -> list[str]:
    return [v for v in (value or "").split(",") if v]


def _correlation(request: Request) -> str:
    return audit_correlation_id(correlation_id_of(request.scope))


def _refuse_unpublishable(doc: Mapping[str, Any]) -> None:
    """Early refusals; the connector re-checks every one of them when it plans."""
    auth = doc.get("auth")
    auth_map = cast(Mapping[str, Any], auth) if isinstance(auth, Mapping) else {}
    if doc.get("transport") == "sse":
        raise CapabilityUnavailableError(
            "mcp_sse_unsupported", "only streamable HTTP MCP servers can be published"
        )
    if auth_map.get("kind") == "api_key":
        raise CapabilityUnavailableError(
            "mcp_api_key_upstream", "an API-key upstream cannot be published"
        )
    if not auth_map.get("audience"):
        raise _bad("mcp_audience_missing", "the server has no Entra audience to validate")
    if doc.get("publishable") is not True:
        raise CapabilityUnavailableError(
            "mcp_not_publishable", "the catalog marks this server as not publishable"
        )


async def _grants(
    access: EntityAccess, repository: CatalogRepository, now: datetime
) -> tuple[list[dict[str, Any]], int]:
    """Direct grants on the server (merged per principal) and the number of group grants."""
    by_oid: dict[str, int | None] = {}
    groups = 0
    cursor: str | None = None
    for _ in range(_MAX_GRANT_PAGES):
        page = await repository.list_entities(
            access.scope,
            EntityFilter(entity_types=["grant"], lifecycle_statuses=["active"]),
            PageRequest(page_size=MAX_PAGE_SIZE, cursor=cursor),
        )
        for entity in page.items:
            grant = dump(entity)
            target = cast(Mapping[str, Any], grant.get("target") or {})
            if target.get("kind") != ENTITY_TYPE or target.get("ref") != access.entity.id:
                continue
            if grant.get("enabled") is not True or not _in_window(grant, now):
                continue
            principal = cast(Mapping[str, Any], grant.get("principal") or {})
            if principal.get("kind") == "entra_group":
                groups += 1
                continue
            oid = str(principal.get("object_id"))
            limits = cast(Mapping[str, Any], grant.get("limits") or {})
            calls = limits.get("mcp_calls_per_minute")
            calls = calls if isinstance(calls, int) else None
            # Two grants for one principal: the more permissive applies (no limit wins).
            if oid in by_oid:
                prior = by_oid[oid]
                calls = None if prior is None or calls is None else max(prior, calls)
            by_oid[oid] = calls
        cursor = page.next_cursor
        if cursor is None:
            return [{"oid": oid, "calls_per_minute": by_oid[oid]} for oid in sorted(by_oid)], groups
    raise CapabilityUnavailableError("too_many_grants", "too many grants to publish in one stage")


def _in_window(grant: Mapping[str, Any], now: datetime) -> bool:
    start, end = grant.get("valid_from"), grant.get("valid_until")
    if isinstance(start, str) and parse_timestamp(start) > now:
        return False
    return not (isinstance(end, str) and parse_timestamp(end) <= now)


async def _require_gateway(
    gateways: GatewayPlane, access: EntityAccess, domain: str, gateway_id: str
) -> None:
    """The gateway must be registered in the server's own domain (no cross-domain publish)."""
    registration = await gateways.store.get(access.scope.customer_id, domain, gateway_id)
    if registration is None:
        raise _bad(GATEWAY_NOT_REGISTERED, "the gateway is not registered in this domain")


async def _draft(
    actions: ActionPlane,
    access: EntityAccess,
    domain: str,
    *,
    kind: str,
    stage: Stage,
    publication: dict[str, Any],
    key: str,
    channel: Channel,
    correlation_id: str,
) -> ActionView:
    body = DraftIntentBody(
        action_kind=kind,
        target=TargetRef(canonical_id=access.entity.id, entity_type=ENTITY_TYPE),
        target_version=STAGE_VERSIONS[stage],
        proposed_diff=ProposedDiff.model_validate(
            {
                "format": "json_patch",
                "operations": [{"op": "replace", "path": "/publication", "value": publication}],
            }
        ),
        idempotency_key=key,
        channel=channel,
    )
    view, _ = await ActionApi(actions).draft(access.scope, domain, body, correlation_id)
    return view


def _status(doc: Mapping[str, Any], server_id: str) -> McpPublicationStatus:
    state = _state(doc)
    unpublish_stage = _UNPUBLISH_STAGE[state]
    return McpPublicationStatus(
        server_id=server_id,
        state=state,
        gateway_id=_attr(doc, "gateway_id"),
        api_path=_attr(doc, "api_path"),
        created_resources=_split(_attr(doc, "created")),
        shared_resources=_split(_attr(doc, "shared")),
        next_publish_stage=cast(Stage, _PUBLISH_STAGE[state]),
        next_unpublish_stage=cast(Stage | None, unpublish_stage),
        diagnostics=[BODY_BYTES_NOTE],
    )


def _publication_of(diff: Any) -> Mapping[str, Any]:
    ops = [op for op in diff.operations if op.path == "/publication"]
    value = ops[0].value if len(ops) == 1 else None
    if not isinstance(value, Mapping):
        raise _bad("intent_mismatch", "the intent is not an MCP publication")
    return cast(Mapping[str, Any], value)


def _recorded(
    doc: Mapping[str, Any],
    server_id: str,
    stage: Stage,
    publication: Mapping[str, Any],
    intent_id: str,
    now: datetime,
) -> dict[str, Any]:
    """The McpServer document after recording ``stage``: attributes plus provenance."""
    attributes = {k: v for k, v in _attributes(doc).items() if not k.startswith(_ATTR)}
    state = _AFTER[stage]
    attributes[_ATTR + "state"] = state
    attributes[_ATTR + "intent_id"] = intent_id
    gateway_id = str(publication.get("gateway_id"))
    if state != "unpublished":
        created, shared = publication_resources(server_id)
        previous = _attr(doc, "api_path")
        api_path = publication.get("api_path") or previous
        attributes[_ATTR + "gateway_id"] = gateway_id
        attributes[_ATTR + "api_path"] = api_path if isinstance(api_path, str) else None
        attributes[_ATTR + "audience_named_value"] = publication.get(
            "audience_named_value"
        ) or _attr(doc, "audience_named_value")
        attributes[_ATTR + "created"] = ",".join(created)
        attributes[_ATTR + "shared"] = ",".join(shared)
    out = dict(doc)
    out["attributes"] = attributes
    out["provenance"] = {
        "method": "declared",
        "source_id": f"{CONNECTOR_SOURCE}.{gateway_id}",
        "connector_version": CONNECTOR_VERSION,
        "recorded_at": format_timestamp(now),
    }
    return out


# -- router -----------------------------------------------------------------------------------


def build_mcp_publish_router() -> APIRouter:
    router = APIRouter(tags=["catalog"])

    @router.get("/{entity_id:path}/publication", response_model=McpPublicationStatus)
    async def mcp_publication_status(access: ReadAccess) -> McpPublicationStatus:
        """Publication state of the server, the gateway resources it owns, and diagnostics."""
        return _status(_server(access.entity), access.entity.id)

    @router.post(
        "/{entity_id:path}/publish",
        response_model=McpPublicationDraft,
        response_model_exclude_unset=True,
        status_code=201,
    )
    async def publish_mcp_server(
        request: Request,
        body: McpPublishBody,
        access: ProposeAccess,
        actions: Actions,
        gateways: Gateways,
        repository: Repository,
        clock: ClockDep,
    ) -> McpPublicationDraft:
        """Draft the next publish stage (``publish``, or ``deny`` then ``change``)."""
        doc = _server(access.entity)
        domain = str(doc["domain_id"])
        state = _state(doc)
        stage = cast(Stage, _PUBLISH_STAGE[state])
        recorded_gateway = _attr(doc, "gateway_id")
        gateway_id = body.gateway_id or recorded_gateway
        if gateway_id is None:
            raise _bad("gateway_required", "name the gateway to publish through")
        if recorded_gateway is not None and gateway_id != recorded_gateway:
            raise _bad("mcp_published_elsewhere", "the server is published on another gateway")
        await _require_gateway(gateways, access, domain, gateway_id)
        diagnostics = [BODY_BYTES_NOTE]
        publication: dict[str, Any] = {"stage": stage, "gateway_id": gateway_id}
        if stage == "deny":
            diagnostics.append(_DENY_NOTE)
        else:
            _refuse_unpublishable(doc)
            api_path = body.api_path or _attr(doc, "api_path")
            if api_path is None:
                raise _bad("api_path_required", "name the gateway API path")
            audience_nv = (
                body.audience_named_value
                or _attr(doc, "audience_named_value")
                or f"{publication_prefix(access.entity.id)}-audience"
            )
            grants, groups = await _grants(access, repository, clock())
            auth = cast(Mapping[str, Any], doc.get("auth") or {})
            publication.update(
                url=doc.get("url"),
                transport=doc.get("transport"),
                auth_kind=auth.get("kind"),
                audience=auth.get("audience"),
                api_path=api_path,
                audience_named_value=audience_nv,
                grants=grants,
            )
            diagnostics.append(
                _NAMED_VALUES_NOTE.format(tenant=TENANT_NAMED_VALUE, audience=audience_nv)
            )
            if not grants:
                diagnostics.append(
                    "No direct grant targets this server: every caller gets 403 until one does."
                )
            if groups:
                diagnostics.append(
                    f"{groups} group grant(s) are not enforced on MCP publications (groups-claim "
                    "overage fails closed); give those principals a direct grant."
                )
        view = await _draft(
            actions,
            access,
            domain,
            kind=PUBLISH_KIND,
            stage=stage,
            publication=publication,
            key=body.idempotency_key,
            channel=body.channel,
            correlation_id=_correlation(request),
        )
        return McpPublicationDraft(action=view, stage=stage, state=state, diagnostics=diagnostics)

    @router.post(
        "/{entity_id:path}/unpublish",
        response_model=McpPublicationDraft,
        response_model_exclude_unset=True,
        status_code=201,
    )
    async def unpublish_mcp_server(
        request: Request,
        body: McpUnpublishBody,
        access: ProposeAccess,
        actions: Actions,
        gateways: Gateways,
    ) -> McpPublicationDraft:
        """Draft the next unpublish stage (``deny``, then ``remove``)."""
        doc = _server(access.entity)
        domain = str(doc["domain_id"])
        state = _state(doc)
        stage = _UNPUBLISH_STAGE[state]
        gateway_id = _attr(doc, "gateway_id")
        if stage is None or gateway_id is None:
            raise _bad("mcp_not_published", "the server is not published")
        await _require_gateway(gateways, access, domain, gateway_id)
        diagnostics = [BODY_BYTES_NOTE]
        if stage == "deny":
            diagnostics.append(_DENY_NOTE)
        view = await _draft(
            actions,
            access,
            domain,
            kind=UNPUBLISH_KIND,
            stage=cast(Stage, stage),
            publication={"stage": stage, "gateway_id": gateway_id},
            key=body.idempotency_key,
            channel=body.channel,
            correlation_id=_correlation(request),
        )
        return McpPublicationDraft(
            action=view, stage=cast(Stage, stage), state=state, diagnostics=diagnostics
        )

    @router.post("/{entity_id:path}/publication-record", response_model=CatalogEntity)
    async def record_mcp_publication(
        request: Request,
        response: Response,
        body: McpPublicationRecordBody,
        access: ProposeAccess,
        actions: Actions,
        service: Service,
        clock: ClockDep,
    ) -> CatalogEntity:
        """Record a succeeded, verified publication stage on the catalog McpServer."""
        doc = _server(access.entity)
        domain = str(doc["domain_id"])
        stored = await actions.intents.get(access.scope.customer_id, domain, body.intent_id)
        if stored is None:
            raise _bad("intent_not_found", "no such intent in this domain")
        intent = stored.intent
        if intent.target.canonical_id != access.entity.id or intent.action_kind not in _KIND_STAGES:
            raise _bad("intent_mismatch", "the intent is not a publication of this server")
        publication = _publication_of(intent.proposed_diff)
        stage = publication.get("stage")
        if stage not in _KIND_STAGES[intent.action_kind]:
            raise _bad("intent_mismatch", "the stage does not belong to this action kind")
        execution = stored.execution
        if (
            stored.state != "succeeded"
            or intent.dry_run
            or execution is None
            or execution.verify_matched is not True
            or execution.apply_finished_at is None
        ):
            raise _bad("intent_not_succeeded", "only a succeeded, verified intent is recorded")
        applied_at = execution.apply_finished_at
        state = _state(doc)
        if intent.target_version != STATE_VERSIONS[state]:
            raise StaleVersionError(
                "the publication state changed since the intent was drafted",
                reason="publication_state_changed",
            )
        recorded_gateway = _attr(doc, "gateway_id")
        if recorded_gateway is not None and publication.get("gateway_id") != recorded_gateway:
            raise _bad("mcp_published_elsewhere", "the intent names another gateway")
        # An intent applied before the last record is history (its effect was superseded):
        # replaying it would record a state the gateway no longer has.
        provenance = cast(Mapping[str, Any], doc.get("provenance") or {})
        source = provenance.get("source_id")
        recorded_at = provenance.get("recorded_at")
        if (
            isinstance(source, str)
            and source.startswith(CONNECTOR_SOURCE + ".")
            and isinstance(recorded_at, str)
            and applied_at < parse_timestamp(recorded_at)
        ):
            raise StaleVersionError(
                "the intent was applied before the last recorded publication",
                reason="stale_intent",
            )
        updated = _recorded(
            doc,
            access.entity.id,
            cast(Stage, stage),
            publication,
            body.intent_id,
            clock(),
        )
        entity = await service.update(
            access.scope,
            access.entity,
            updated,
            access.entity.etag.root,
            correlation_id=_correlation(request),
        )
        etag = entity.etag.root
        response.headers["ETag"] = etag if etag.startswith('"') else f'"{etag}"'
        return entity

    return router
