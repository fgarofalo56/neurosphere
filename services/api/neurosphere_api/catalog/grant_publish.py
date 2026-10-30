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
only an intent id and re-reads that intent, which must be a ``succeeded`` and verified
``grant_publish`` / ``grant_unpublish`` of THIS grant. It then writes the publication into the
Grant through the catalog service (audited, ETag-guarded): ``provenance`` names the gateway
(``source_id``), the connector and the time; the closed ``provenance`` object has no room for
resource names or ownership, so those go in the Grant's existing scalar ``attributes``
(``apim_*``). The Grant schema is unchanged. Ownership comes from the connector's apply record
when the deployment wires ``app.state.apim_apply_records``; without it ownership is recorded as
``unrecorded`` and an unpublish is refused (it would otherwise not know which resources the
publication created).

No ``from __future__ import annotations``: FastAPI inspects these signatures.
"""

from typing import Annotated, Any, Final, Literal, Protocol

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from neurosphere_connector.write import WriteRequest
from neurosphere_contracts.actions.v1.action_intent import PatchOperation, ProposedDiff
from neurosphere_contracts.actions.v1.target_ref import TargetRef
from neurosphere_core.actions import IntentKey, StoredIntent
from neurosphere_core.auth.scope import Permission
from neurosphere_core.catalog import CatalogEntity, format_timestamp
from neurosphere_core.catalog.repo.documents import dump, entity_domain
from neurosphere_core.errors import CapabilityUnavailableError, InvalidSchemaError
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
CONNECTOR_VERSION: Final = "apim-gateway/0.1.0"
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


class _ApplyRecords(Protocol):
    async def latest(self, record_id: str) -> Any: ...


def _correlation(request: Request) -> str:
    return "corr-" + correlation_id_of(request.scope).replace("-", "")


def get_apply_records(request: Request) -> _ApplyRecords | None:
    found = getattr(request.app.state, APPLY_RECORDS_STATE, None)
    return found if found is not None and hasattr(found, "latest") else None


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
    raw = doc.get("attributes")
    return dict(raw) if isinstance(raw, dict) else {}  # pyright: ignore[reportUnknownArgumentType]


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


def _created_names(record: Any) -> tuple[list[str], list[str]]:
    """(all upserted names, names recorded ``created``) of an apply record."""
    every: list[str] = []
    created: list[str] = []
    for step in getattr(record, "steps", ()):
        if getattr(step, "operation", None) != "upsert":
            continue
        name = str(step.name)
        every.append(name)
        if str(step.ownership) == "created":
            created.append(name)
    return every, created


def _succeeded(stored: StoredIntent, grant_id: str) -> None:
    intent = stored.intent
    execution = stored.execution
    if (
        intent.action_kind not in (PUBLISH_KIND, UNPUBLISH_KIND)
        or intent.target.canonical_id != grant_id
        or intent.state.root != "succeeded"
        or execution is None
        or execution.verify_matched is not True
    ):
        raise InvalidSchemaError(
            "the intent is not a verified publication of this grant", reason="intent_not_verified"
        )


def _publish_gateway(stored: StoredIntent) -> str:
    for op in stored.intent.proposed_diff.operations:
        value = op.value
        if op.path == "/publication" and isinstance(value, dict):
            gateway = value.get("gateway_id")  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
            if isinstance(gateway, str):
                return gateway
        if op.path == "/publication/gateway_id" and isinstance(value, str):
            return value
    raise InvalidSchemaError("the intent names no gateway", reason="intent_not_verified")


async def _record(
    service: CatalogService,
    access: EntityAccess,
    stored: StoredIntent,
    records: _ApplyRecords | None,
    now: str,
    correlation_id: str,
) -> CatalogEntity:
    doc = dump(access.entity)
    attrs = _attrs(doc)
    intent_id = str(stored.intent.intent_id.root)
    if attrs.get("apim_intent_id") == intent_id:
        return access.entity
    gateway_id = _publish_gateway(stored)
    publishing = stored.intent.action_kind == PUBLISH_KIND
    token = (
        (stored.execution.apply_result or {}).get("rollback_token") if stored.execution else None
    )
    attrs.update(
        apim_published=publishing,
        apim_gateway_id=gateway_id,
        apim_intent_id=intent_id,
        apim_apply_record=str(token) if token else None,
    )
    if publishing:
        found = await records.latest(str(token)) if records is not None and token else None
        if found is None:
            attrs.update(apim_ownership="unrecorded", apim_resources=None, apim_created=None)
        else:
            every, created = _created_names(found)
            attrs.update(
                apim_ownership="recorded",
                apim_resources=",".join(every),
                apim_created=",".join(created),
            )
    else:
        attrs.update(apim_ownership=None, apim_resources=None, apim_created=None)
    doc["attributes"] = attrs
    doc["provenance"] = {
        "method": "declared",
        "source_id": gateway_id,
        "connector_version": CONNECTOR_VERSION,
        "recorded_at": now,
    }
    return await service.update(
        access.scope,
        access.entity,
        doc,
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
        ops = [
            PatchOperation(op="test", path="/publication/gateway_id", value=gateway_id),
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
        records: Annotated[_ApplyRecords | None, Depends(get_apply_records)],
        clock: Annotated[Any, Depends(get_clock)],
    ) -> CatalogEntity:
        _, domain = _grant_doc(access)
        stored = await load_intent(
            plane, IntentKey(access.scope.customer_id, domain, body.intent_id)
        )
        _succeeded(stored, access.entity.id)
        return await _record(
            service, access, stored, records, format_timestamp(clock()), _correlation(request)
        )
