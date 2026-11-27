"""Notification channel and subscription admin routes, at ``/api/v1/admin/notifications``.

Routes (``If-Match`` guards every PUT and DELETE; a DELETE answers 204 with an empty body):

- ``GET /channel-kinds``: kind status (buildable, degraded, not_built).
- ``GET|POST /channels``: views with per-status delivery counts; POST is 201 with ``ETag``.
- ``GET|PUT|DELETE /channels/{id}``: the ``ETag`` header equals the view ``etag``; DELETE retires.
- ``POST /channels/{id}/test``: synchronous test send through the real sender.
- ``GET|POST /subscriptions`` and ``GET|PUT|DELETE /subscriptions/{id}``: the channel must exist.
- ``GET /deliveries``: ``?status&channel_id&limit``, newest first.

Every route needs customer-level (deployment-scoped) ``config.manage``: another caller gets 403
and a denial record from the shared dependency. Until the ``notifications`` component is built
every route answers 503 ``dependency_transient`` reason ``capability_unavailable``. The error
taxonomy is closed, so a refusal keeps its taxonomy ``code`` and carries the specific code in
``reason`` (``channel_kind_not_built``, ``host_not_allowed``, ``cloud_boundary``,
``notifications_not_configured``, ``precondition_required``); a stale ``If-Match`` is 409
``stale_version``.

No ``from __future__ import annotations``: FastAPI inspects these signatures.
"""

from typing import Annotated, Any, Final

from fastapi import APIRouter, Depends, Header, Path, Query, Request, Response, status
from fastapi import Body as BodyParam
from neurosphere_core.audit import AuditRepository
from neurosphere_core.auth.scope import Permission
from neurosphere_core.errors import DependencyTransientError
from neurosphere_core.scope import IdentityScope

from neurosphere_api.authz.deployment_scope import require_deployment_admin
from neurosphere_api.middleware import correlation_id_of
from neurosphere_api.notifications.models import (
    DELIVERY_STATUSES,
    ChannelList,
    ChannelTestResult,
    ChannelView,
    DeliveryList,
    KindList,
    SubscriptionList,
    SubscriptionView,
)
from neurosphere_api.notifications.service import (
    AdminHooks,
    NotificationsAdmin,
    parse_channel,
    parse_subscription,
)
from neurosphere_api.routers import RouterRegistry
from neurosphere_api.runtime.builders.notifications import (
    STATE_ATTRIBUTE as PLANE_ATTRIBUTE,
)
from neurosphere_api.runtime.builders.notifications import NotificationsPlane

__all__ = ["HOOKS_ATTRIBUTE", "PREFIX", "build_router", "register"]

PREFIX: Final = "/api/v1/admin/notifications"
HOOKS_ATTRIBUTE: Final = "notifications_admin_hooks"
CAPABILITY_UNAVAILABLE: Final = "capability_unavailable"
_AUDIT_ATTRIBUTE: Final = "audit_repository"

#: Customer-level ``config.manage`` (the control domain), reads included.
AdminScope = Annotated[IdentityScope, Depends(require_deployment_admin(Permission.CONFIG_MANAGE))]
Body = Annotated[dict[str, Any], BodyParam()]
IfMatch = Annotated[str | None, Header(alias="If-Match", max_length=300)]
IdPath = Annotated[str, Path(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")]


def _correlation(request: Request) -> str:
    return "corr-" + correlation_id_of(request.scope).replace("-", "")


def _admin(request: Request, scope: AdminScope) -> NotificationsAdmin:
    state = request.app.state
    plane = getattr(state, PLANE_ATTRIBUTE, None)
    if not isinstance(plane, NotificationsPlane):
        raise DependencyTransientError(
            "notifications are not enabled in this deployment", reason=CAPABILITY_UNAVAILABLE
        )
    audit = getattr(state, _AUDIT_ATTRIBUTE, None)
    hooks = getattr(state, HOOKS_ATTRIBUTE, None)
    return NotificationsAdmin(
        plane,
        scope,
        audit=audit if isinstance(audit, AuditRepository) else None,
        cloud=state.settings.cloud_profile.cloud.value,
        ns_env=state.settings.env,
        hooks=hooks if isinstance(hooks, AdminHooks) else None,
    )


Admin = Annotated[NotificationsAdmin, Depends(_admin)]


def _set_etag(response: Response, etag: str) -> None:
    response.headers["ETag"] = etag


def build_router() -> APIRouter:
    router = APIRouter(tags=["admin-notifications"])

    @router.get("/channel-kinds", response_model=KindList)
    async def channel_kinds(admin: Admin) -> KindList:
        return admin.kinds()

    @router.get("/channels", response_model=ChannelList)
    async def list_channels(admin: Admin) -> ChannelList:
        return await admin.list_channels()

    @router.post("/channels", response_model=ChannelView, status_code=status.HTTP_201_CREATED)
    async def create_channel(
        request: Request, response: Response, body: Body, admin: Admin
    ) -> ChannelView:
        view, etag = await admin.create_channel(_correlation(request), parse_channel(body))
        _set_etag(response, etag)
        return view

    @router.get("/channels/{channel_id}", response_model=ChannelView)
    async def get_channel(response: Response, channel_id: IdPath, admin: Admin) -> ChannelView:
        view, etag = await admin.get_channel(channel_id)
        _set_etag(response, etag)
        return view

    @router.put("/channels/{channel_id}", response_model=ChannelView)
    async def replace_channel(
        request: Request,
        response: Response,
        channel_id: IdPath,
        body: Body,
        admin: Admin,
        if_match: IfMatch = None,
    ) -> ChannelView:
        view, etag = await admin.replace_channel(
            _correlation(request), channel_id, parse_channel(body), if_match
        )
        _set_etag(response, etag)
        return view

    @router.delete("/channels/{channel_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_channel(
        request: Request, channel_id: IdPath, admin: Admin, if_match: IfMatch = None
    ) -> Response:
        await admin.delete_channel(_correlation(request), channel_id, if_match)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.post("/channels/{channel_id}/test", response_model=ChannelTestResult)
    async def test_channel(request: Request, channel_id: IdPath, admin: Admin) -> ChannelTestResult:
        return await admin.test_channel(_correlation(request), channel_id)

    @router.get("/subscriptions", response_model=SubscriptionList)
    async def list_subscriptions(admin: Admin) -> SubscriptionList:
        return await admin.list_subscriptions()

    @router.post(
        "/subscriptions", response_model=SubscriptionView, status_code=status.HTTP_201_CREATED
    )
    async def create_subscription(
        request: Request, response: Response, body: Body, admin: Admin
    ) -> SubscriptionView:
        view, etag = await admin.create_subscription(
            _correlation(request), parse_subscription(body)
        )
        _set_etag(response, etag)
        return view

    @router.get("/subscriptions/{subscription_id}", response_model=SubscriptionView)
    async def get_subscription(
        response: Response, subscription_id: IdPath, admin: Admin
    ) -> SubscriptionView:
        view, etag = await admin.get_subscription(subscription_id)
        _set_etag(response, etag)
        return view

    @router.put("/subscriptions/{subscription_id}", response_model=SubscriptionView)
    async def replace_subscription(
        request: Request,
        response: Response,
        subscription_id: IdPath,
        body: Body,
        admin: Admin,
        if_match: IfMatch = None,
    ) -> SubscriptionView:
        view, etag = await admin.replace_subscription(
            _correlation(request), subscription_id, parse_subscription(body), if_match
        )
        _set_etag(response, etag)
        return view

    @router.delete("/subscriptions/{subscription_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_subscription(
        request: Request, subscription_id: IdPath, admin: Admin, if_match: IfMatch = None
    ) -> Response:
        await admin.delete_subscription(_correlation(request), subscription_id, if_match)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.get("/deliveries", response_model=DeliveryList)
    async def list_deliveries(
        admin: Admin,
        status_filter: Annotated[
            str | None, Query(alias="status", pattern=f"^({'|'.join(DELIVERY_STATUSES)})$")
        ] = None,
        channel_id: Annotated[str | None, Query(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")] = None,
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
    ) -> DeliveryList:
        return await admin.list_deliveries(
            status=status_filter, channel_id=channel_id or None, limit=limit
        )

    return router


def register(registry: RouterRegistry) -> None:
    """Router-registry hook (see ``neurosphere_api/routers.py``)."""
    registry.register(PREFIX, build_router())
