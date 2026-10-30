"""Grant publish and unpublish routes (PRP-34 item 5), included by the catalog router.

| Method | Path (under ``/api/v1/catalog``)           | Permission                              |
|--------|---------------------------------------------|-----------------------------------------|
| POST   | ``/grants/{entity_id}/publish``             | ``action.propose`` (grant's domain)     |
| POST   | ``/grants/{entity_id}/unpublish``           | ``action.propose`` (grant's domain)     |
| POST   | ``/grants/{entity_id}/publication``         | ``catalog.curate`` (grant's domain)     |

Publish and unpublish never touch the gateway: they DRAFT a ``grant_publish`` /
``grant_unpublish`` action intent through the one action plane (the same
``ActionApi.draft`` as ``POST /api/v1/actions/domains/{domain}/intents``), so validate,
confirmation, maker-checker approval and the executor worker apply as for any other action. The
authorization target is the STORED grant's domain (``entity_access``); the permission set is the
shipped one (no new permission).

The draft carries the connector's own ``dry_run`` diff (planned against the live gateway, with
the plan digest bound in as ``test /plan_digest``), so the approver confirms the exact plan and
the executor refuses a gateway that moved since.

``.../publication`` records a REAL gateway change in the catalog and nothing else: it accepts
only an intent id and re-reads that intent, which must be a ``succeeded``, verified, non-dry-run
``grant_publish`` / ``grant_unpublish`` of THIS grant whose diff has the grammar of its kind (a
``grant_publish`` carrying a remove diff is never recorded as an unpublish). It then writes the
publication into the Grant through the catalog service (audited, ETag-guarded): ``provenance``
names the gateway (``source_id``), the connector and the time; the closed ``provenance`` object
has no room for resource names or ownership, so those go in the Grant's existing scalar
``attributes`` (``apim_*``). The Grant schema is unchanged. Ownership comes from the connector's
apply record, read through ``app.state.apim_apply_records`` (wired by the gateway runtime builder
to the ``gateways`` container the executor writes to); without it ownership is recorded as
``unrecorded`` and an unpublish is refused (it would otherwise not know which resources the
publication created). The rules are shared with the worker's post-success recorder
(``neurosphere_workers.publication``), which normally records the publication without anyone
calling this route; the route stays the manual and retry path. Replaying an already recorded
intent is a no-op.

The unpublish draft names the publish apply record (``test /publication/apply_record``) so the
connector re-checks, while it plans, that every listed resource was recorded ``created``.

No ``from __future__ import annotations``: FastAPI inspects these signatures.
"""

from typing import Annotated, Any, Final, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from neurosphere_connector.write import WriteRequest
from neurosphere_contracts.actions.v1.action_intent import PatchOperation, ProposedDiff
from neurosphere_contracts.actions.v1.target_ref import TargetRef
from neurosphere_core.actions import IntentKey, StoredIntent
from neurosphere_core.auth.scope import Permission
from neurosphere_core.catalog import CatalogEntity, format_timestamp
from neurosphere_core.catalog.repo.documents import dump, entity_domain
from neurosphere_core.errors import CapabilityUnavailableError, InvalidSchemaError
from neurosphere_workers.publication import ApplyRecordReader, reader_for
from neurosphere_workers.publication.grant import (
    check_grant_intent,
    grant_attributes,
    grant_publication_update,
    grant_recorded,
)
from pydantic import BaseModel, ConfigDict, Field

from neurosphere_api.actions.common import load_intent
from neurosphere_api.actions.dependencies import ActionPlane, get_action_plane
from neurosphere_api.actions.models import ActionView, DraftIntentBody
from neurosphere_api.actions.service import ActionApi
from neurosphere_api.catalog.dependencies import EntityAccess, entity_access, get_clock, get_service
from neurosphere_api.catalog.service import CatalogService
from neurosphere_api.gateway.dependencies import GatewayPlane, get_gateway_plane
from neurosphere_api.middleware import correlation_id_of

__all__ = [
    "APPLY_RECORDS_STATE",
    "PUBLISH_KIND",
    "UNPUBLISH_KIND",
    "GrantPublishBody",
    "GrantUnpublishBody",
    "PublicationRecordBody",
    "add_routes",
    "build_router",
]

PUBLISH_KIND: Final = "grant_publish"
UNPUBLISH_KIND: Final = "grant_unpublish"
GRANT_TARGET_TYPE: Final = "grant"
APPLY_RECORDS_STATE: Final = "apim_apply_records"
VERSION_UNPUBLISHED: Final = "grant-unpublished"
VERSION_PUBLISHED: Final = "grant-published"

_QUOTA_PERIODS: Final = {
    "hour": "Hourly",
    "day": "Daily",
    "week": "Weekly",
    "month": "Monthly",
    "year": "Yearly",
}
_GATEWAY_ID: Final = r"^gw-[0-9a-f]{32}$"
_IDEMPOTENCY: Final = r"^[A-Za-z0-9._:-]{16,128}$"

ProposeAccess = Annotated[EntityAccess, Depends(entity_access(Permission.ACTION_PROPOSE))]
CurateAccess = Annotated[EntityAccess, Depends(entity_access(Permission.CATALOG_CURATE))]
Actions = Annotated[ActionPlane, Depends(get_action_plane)]
Gateways = Annotated[GatewayPlane, Depends(get_gateway_plane)]
Service = Annotated[CatalogService, Depends(get_service)]


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GrantPublishBody(_Body):
    """``POST .../publish``. Identity, target, version and the diff are server-side."""

    gateway_id: Annotated[str, Field(pattern=_GATEWAY_ID)]
    api_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")]
    access: Literal["subscription", "entra"]
    tenant_named_value: Annotated[str, Field(pattern=r"^[A-Za-z0-9._-]{1,256}$")] | None = None
    audience_named_value: Annotated[str, Field(pattern=r"^[A-Za-z0-9._-]{1,256}$")] | None = None
    idempotency_key: Annotated[str, Field(pattern=_IDEMPOTENCY)]
    channel: Literal["button", "chat", "rest", "mcp"] = "rest"


class GrantUnpublishBody(_Body):
    """``POST .../unpublish``: the gateway and resources come from the recorded publication."""

    idempotency_key: Annotated[str, Field(pattern=_IDEMPOTENCY)]
    channel: Literal["button", "chat", "rest", "mcp"] = "rest"


class PublicationRecordBody(_Body):
    """``POST .../publication``: the executed intent whose result is recorded."""

    intent_id: Annotated[
        str, Field(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
    ]


def _correlation(request: Request) -> str:
    return "corr-" + correlation_id_of(request.scope).replace("-", "")


def get_apply_records(request: Request) -> object | None:
    """``app.state.apim_apply_records``: an ``ApplyRecordLookup`` (production: the Cosmos
    ``gateways`` container the executor writes apply records to) or a store bound to one
    partition (tests). ``None`` when unwired: ownership is then recorded ``unrecorded``."""
    return getattr(request.app.state, APPLY_RECORDS_STATE, None)


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="not found")


def _grant_doc(access: EntityAccess) -> tuple[dict[str, Any], str]:
    doc = dump(access.entity)
    domain = entity_domain(doc)
    if doc.get("entity_type") != GRANT_TARGET_TYPE or domain is None:
        raise InvalidSchemaError("the entity is not a grant", reason="not_a_grant")
    return doc, domain


def _publish_value(doc: dict[str, Any], body: GrantPublishBody) -> dict[str, Any]:
    if doc.get("enabled") is not True:
        raise InvalidSchemaError("a disabled grant is not published", reason="grant_disabled")
    target = doc["target"]
    if target["kind"] not in ("model_api", "model_deployment"):
        raise InvalidSchemaError(
            "only grants on a model API or deployment are published as products",
            reason="grant_target_not_model",
        )
    principal = doc["principal"]
    if body.access == "subscription" and principal["kind"] == "entra_group":
        raise InvalidSchemaError(
            "a group grant is enforced by Entra claims, not a subscription key",
            reason="group_needs_entra_access",
        )
    limits = doc["limits"]
    value: dict[str, Any] = {
        "gateway_id": body.gateway_id,
        "api_id": body.api_id,
        "access": body.access,
        "principal_kind": principal["kind"],
        "principal_object_id": principal["object_id"],
        "tokens_per_minute": limits.get("tokens_per_minute"),
        "token_quota": limits.get("token_quota"),
        "token_quota_period": None,
    }
    period = limits.get("quota_period")
    if period is not None:
        mapped = _QUOTA_PERIODS.get(period)
        if mapped is None:
            raise InvalidSchemaError("quota period is not enforceable", reason="bad_quota_period")
        value["token_quota_period"] = mapped
    if value["tokens_per_minute"] is None and value["token_quota"] is None:
        raise InvalidSchemaError(
            "the grant declares no token limit", reason="grant_needs_token_limit"
        )
    if body.tenant_named_value is not None:
        value["tenant_named_value"] = body.tenant_named_value
    if body.audience_named_value is not None:
        value["audience_named_value"] = body.audience_named_value
    return {k: v for k, v in value.items() if v is not None}


async def _planned(
    plane: ActionPlane, kind: str, target: TargetRef, version: str, ops: list[PatchOperation]
) -> ProposedDiff:
    """The connector ``dry_run`` diff (live plan, digest bound); the API never applies."""
    connector = plane.connector_for(kind)
    if connector is None:
        raise CapabilityUnavailableError(
            "write_connector_unsupported_target", "no write connector is registered for this kind"
        )
    request = WriteRequest(
        target=target,
        target_version=version,
        proposed_diff=ProposedDiff(format="json_patch", operations=ops),
    )
    return (await connector.dry_run(request)).planned_diff


def _attrs(doc: dict[str, Any]) -> dict[str, Any]:
    return grant_attributes(doc)


async def _draft(
    plane: ActionPlane,
    access: EntityAccess,
    kind: str,
    version: str,
    ops: list[PatchOperation],
    body: GrantPublishBody | GrantUnpublishBody,
    domain: str,
    correlation_id: str,
) -> tuple[ActionView, bool]:
    target = TargetRef(canonical_id=access.entity.id, entity_type=GRANT_TARGET_TYPE)
    diff = await _planned(plane, kind, target, version, ops)
    draft = DraftIntentBody(
        action_kind=kind,
        target=target,
        target_version=version,
        proposed_diff=diff,
        idempotency_key=body.idempotency_key,
        channel=body.channel,
    )
    return await ActionApi(plane).draft(access.scope, domain, draft, correlation_id)


async def _record(
    service: CatalogService,
    access: EntityAccess,
    stored: StoredIntent,
    records: ApplyRecordReader | None,
    now: str,
    correlation_id: str,
) -> CatalogEntity:
    """Write the shared publication record (``neurosphere_workers.publication.grant``)."""
    doc = dump(access.entity)
    if grant_recorded(doc, str(stored.intent.intent_id.root)):
        return access.entity
    updated = await grant_publication_update(doc, stored, records, now)
    return await service.update(
        access.scope,
        access.entity,
        updated,
        access.entity.etag.root,
        correlation_id=correlation_id,
    )


def build_router() -> APIRouter:
    router = APIRouter(tags=["catalog"])
    add_routes(router)
    return router


def add_routes(router: APIRouter) -> None:
    """Declare the routes on ``router`` (the catalog router: ``include_router`` is not usable
    there because the deprecated ``/catalog`` alias re-declares plain ``APIRoute`` objects)."""

    @router.post("/grants/{entity_id:path}/publish", response_model=ActionView)
    async def publish_grant(
        request: Request,
        response: Response,
        body: GrantPublishBody,
        access: ProposeAccess,
        plane: Actions,
        gateways: Gateways,
    ) -> ActionView:
        doc, domain = _grant_doc(access)
        registration = await gateways.store.get(access.scope.customer_id, domain, body.gateway_id)
        if registration is None:
            raise _not_found()
        value = _publish_value(doc, body)
        ops = [PatchOperation(op="add", path="/publication", value=value)]
        view, created = await _draft(
            plane,
            access,
            PUBLISH_KIND,
            VERSION_UNPUBLISHED,
            ops,
            body,
            domain,
            _correlation(request),
        )
        response.status_code = 201 if created else 200
        return view

    @router.post("/grants/{entity_id:path}/unpublish", response_model=ActionView)
    async def unpublish_grant(
        request: Request,
        response: Response,
        body: GrantUnpublishBody,
        access: ProposeAccess,
        plane: Actions,
    ) -> ActionView:
        doc, domain = _grant_doc(access)
        attrs = _attrs(doc)
        gateway_id = attrs.get("apim_gateway_id")
        if attrs.get("apim_published") is not True or not isinstance(gateway_id, str):
            raise InvalidSchemaError("the grant is not published", reason="grant_not_published")
        created = attrs.get("apim_created")
        if attrs.get("apim_ownership") != "recorded" or not isinstance(created, str) or not created:
            raise InvalidSchemaError(
                "the publication has no recorded ownership; nothing may be deleted",
                reason="ownership_unrecorded",
            )
        record_id = attrs.get("apim_apply_record")
        if not isinstance(record_id, str) or not record_id:
            raise InvalidSchemaError(
                "the publication names no apply record; nothing may be deleted",
                reason="ownership_unrecorded",
            )
        ops = [
            PatchOperation(op="test", path="/publication/gateway_id", value=gateway_id),
            PatchOperation(op="test", path="/publication/apply_record", value=record_id),
            PatchOperation(op="test", path="/publication/resources", value=created.split(",")),
            PatchOperation(op="remove", path="/publication"),
        ]
        view, new = await _draft(
            plane,
            access,
            UNPUBLISH_KIND,
            VERSION_PUBLISHED,
            ops,
            body,
            domain,
            _correlation(request),
        )
        response.status_code = 201 if new else 200
        return view

    @router.post("/grants/{entity_id:path}/publication", response_model=CatalogEntity)
    async def record_publication(
        request: Request,
        body: PublicationRecordBody,
        access: CurateAccess,
        plane: Actions,
        service: Service,
        records: Annotated[object | None, Depends(get_apply_records)],
        clock: Annotated[Any, Depends(get_clock)],
    ) -> CatalogEntity:
        _, domain = _grant_doc(access)
        stored = await load_intent(
            plane, IntentKey(access.scope.customer_id, domain, body.intent_id)
        )
        check_grant_intent(stored, access.entity.id)
        reader = reader_for(records, access.scope.customer_id, domain)
        return await _record(
            service, access, stored, reader, format_timestamp(clock()), _correlation(request)
        )
