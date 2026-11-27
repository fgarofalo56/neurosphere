"""Notification channel and subscription administration (PRP-107 item 7).

Every route is deployment-scoped ``config.manage`` (the router's dependency); this module holds
the rules behind it:

* a channel is validated as the contract ``NotificationChannel`` plus the ``if/then`` rules the
  generated model drops (``local_sink`` <-> ``local_sink_url``; ``endpoint_credential`` null only
  with ``local_sink``; a webhook needs ``hmac_credential`` unless ``local_sink``), then its kind
  must have a sender (``channel_kind_not_built``), a ``NotificationsSetting`` must exist
  (``notifications_not_configured``) and the egress guard must accept its host
  (:meth:`EgressGuard.check_channel_host`: cloud boundary, local sink only on ``NS_ENV=local``,
  host on the allow-list); the refusal's reason code is the problem ``reason``;
* a subscription must name an existing channel of the same customer and cloud;
* every write is an ``If-Match``-guarded ``admin_config`` write (versions and ETags from the
  store; a delete retires the document) inside ``run_audited_mutation``: a ``before`` record, the
  write, an ``after`` record on ``<customer>.admin-config``; a failed audit write aborts the
  change. The test send is audited the same way. Audit state names the operation, the id and the
  version, never a credential reference, URL or secret.

Credentials are references only. A test send reads them through the injected ``SecretReader``
(Key Vault with the workload identity in production) and the real sender over the egress guard.
"""

from __future__ import annotations

import asyncio
import re
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final, TypeVar, cast

from neurosphere_contracts.admin.v1.admin_config_document import AdminConfigDocument
from neurosphere_contracts.admin.v1.credential_reference import CredentialReference
from neurosphere_core.admin import admin_config_chain_id
from neurosphere_core.admin.connectors import parse_key_vault_secret
from neurosphere_core.audit import (
    AuditContext,
    AuditDraft,
    AuditRepository,
    build_after,
    build_before,
    make_subject,
    run_audited_mutation,
)
from neurosphere_core.cloud import CloudName
from neurosphere_core.errors import (
    CapabilityUnavailableError,
    DependencyTransientError,
    InvalidSchemaError,
    NotFoundError,
    ValidationIssue,
)
from neurosphere_core.notifications.egress import EgressGuard, EgressRefusedError
from neurosphere_core.notifications.message import MessageSubject, NotificationMessage
from neurosphere_core.notifications.models import (
    NotificationChannel,
    NotificationsSetting,
    NotificationSubscription,
)
from neurosphere_core.notifications.registry import CHANNEL_KIND, SUBSCRIPTION_KIND
from neurosphere_core.notifications.senders import (
    KindNotBuildableError,
    SecretReader,
    build_sender,
    kind_status,
    require_buildable,
)
from neurosphere_core.scope import IdentityScope
from pydantic import BaseModel, ValidationError

from neurosphere_api.notifications.keyvault import KeyVaultSecretReader
from neurosphere_api.notifications.models import (
    DELIVERY_STATUSES,
    ChannelList,
    ChannelTestResult,
    ChannelView,
    DeliveryCounts,
    DeliveryList,
    KindInfo,
    KindList,
    SubscriptionList,
    SubscriptionView,
    etag_of,
    quoted,
)
from neurosphere_api.runtime.builders.notifications import NotificationsPlane

__all__ = ["AdminHooks", "NotificationsAdmin", "parse_channel", "parse_subscription"]

_T = TypeVar("_T")
_DETAIL_OK: Final = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_KINDS: Final = ("webhook", "teams_webhook", "email")
_TEST_TITLE: Final = "NeuroSphere test notification"
_TEST_EVENT: Final = "channel_test"


@dataclass(frozen=True)
class AdminHooks:
    """Test seams on ``app.state.notifications_admin_hooks``; production leaves them unset."""

    secrets: SecretReader | None = None
    guard: EgressGuard | None = None
    clock: Callable[[], datetime] | None = None


def _refuse(pointer: str, detail: str, reason: str) -> InvalidSchemaError:
    return InvalidSchemaError(
        "notification configuration is invalid",
        errors=[ValidationIssue(pointer, detail)],
        reason=reason,
    )


def _reason_of(exc: BaseException) -> str:
    reason = getattr(exc, "reason", None)
    return reason if isinstance(reason, str) and _DETAIL_OK.fullmatch(reason) else "error"


class NotificationsAdmin:
    """One request's view of the administration plane (scope, cloud, environment)."""

    def __init__(
        self,
        plane: NotificationsPlane,
        scope: IdentityScope,
        *,
        audit: AuditRepository | None,
        cloud: str,
        ns_env: str,
        hooks: AdminHooks | None = None,
    ) -> None:
        self._plane = plane
        self._scope = scope
        self._audit = audit
        self._cloud = cloud
        self._env = ns_env
        self._hooks = hooks or AdminHooks()
        self._repo = plane.registry.repository
        self._customer = scope.customer_id

    # -- reads --------------------------------------------------------------------------------

    @staticmethod
    def kinds() -> KindList:
        items: list[KindInfo] = []
        for kind in _KINDS:
            status, reason = kind_status(kind)
            items.append(KindInfo(kind=kind, status=status, reason=reason))
        return KindList(items=items)

    async def list_channels(self) -> ChannelList:
        docs = await self._repo.list_by_kind(self._customer, CHANNEL_KIND, limit=1000)
        active = sorted((d for d in docs if d.status == "active"), key=lambda d: d.id.root)
        return ChannelList(
            items=list(await asyncio.gather(*(self._channel_view(d) for d in active)))
        )

    async def get_channel(self, channel_id: str) -> tuple[ChannelView, str]:
        document = await self._active(CHANNEL_KIND, channel_id, "channel_not_found")
        return await self._channel_view(document), etag_of(document)

    async def list_subscriptions(self) -> SubscriptionList:
        docs = await self._repo.list_by_kind(self._customer, SUBSCRIPTION_KIND, limit=1000)
        active = sorted((d for d in docs if d.status == "active"), key=lambda d: d.id.root)
        return SubscriptionList(items=[self._subscription_view(d) for d in active])

    async def get_subscription(self, subscription_id: str) -> tuple[SubscriptionView, str]:
        document = await self._active(SUBSCRIPTION_KIND, subscription_id, "subscription_not_found")
        return self._subscription_view(document), etag_of(document)

    async def list_deliveries(
        self, *, status: str | None, channel_id: str | None, limit: int
    ) -> DeliveryList:
        entries = await self._plane.store.list_deliveries(
            self._customer,
            status=status,
            channel_id=channel_id,
            limit=limit,
            newest_first=True,
        )
        return DeliveryList(
            items=[e.delivery.model_dump(mode="json", exclude_none=True) for e in entries]
        )

    # -- channel writes -----------------------------------------------------------------------

    async def create_channel(
        self, correlation_id: str, body: NotificationChannel
    ) -> tuple[ChannelView, str]:
        await self._check_channel(body)
        channel_id = body.channel_id.root
        document = await self._run(
            "notification.channel.create",
            "notification_channel",
            channel_id,
            correlation_id,
            lambda: self._repo.create(
                self._customer, CHANNEL_KIND, channel_id, body, updated_by=self._actor
            ),
            outcome=_written("notification_channel_created"),
        )
        return await self._channel_view(document), etag_of(document)

    async def replace_channel(
        self, correlation_id: str, channel_id: str, body: NotificationChannel, if_match: str | None
    ) -> tuple[ChannelView, str]:
        guard = _require_if_match(if_match)
        if body.channel_id.root != channel_id:
            raise _refuse("/channel_id", "must equal the id in the path", "path_body_mismatch")
        await self._active(CHANNEL_KIND, channel_id, "channel_not_found")
        await self._check_channel(body)
        document = await self._run(
            "notification.channel.update",
            "notification_channel",
            channel_id,
            correlation_id,
            lambda: self._repo.replace(
                self._customer,
                CHANNEL_KIND,
                channel_id,
                body,
                if_match=guard,
                updated_by=self._actor,
            ),
            outcome=_written("notification_channel_updated"),
        )
        return await self._channel_view(document), etag_of(document)

    async def delete_channel(
        self, correlation_id: str, channel_id: str, if_match: str | None
    ) -> None:
        guard = _require_if_match(if_match)
        await self._active(CHANNEL_KIND, channel_id, "channel_not_found")
        await self._run(
            "notification.channel.delete",
            "notification_channel",
            channel_id,
            correlation_id,
            lambda: self._repo.retire(
                self._customer, CHANNEL_KIND, channel_id, if_match=guard, updated_by=self._actor
            ),
            outcome=_written("notification_channel_deleted"),
        )

    async def test_channel(self, correlation_id: str, channel_id: str) -> ChannelTestResult:
        document = await self._active(CHANNEL_KIND, channel_id, "channel_not_found")
        channel = cast(NotificationChannel, document.body)
        setting = await self._setting()
        try:
            sender = build_sender(
                channel.kind,
                self._hooks.guard or EgressGuard(),
                self._hooks.secrets or KeyVaultSecretReader(cloud=CloudName(self._cloud)),
                setting=setting,
                deployment_cloud=self._cloud,
                ns_env=self._env,
                clock=self._now,
            )
        except KindNotBuildableError as exc:
            raise CapabilityUnavailableError("channel_kind_not_built") from exc
        notification_id = str(uuid.uuid4())
        message = NotificationMessage(
            event_class=_TEST_EVENT,
            notification_id=notification_id,
            subject=MessageSubject(
                canonical_id=(
                    f"{self._cloud}:{self._customer}:notifications:notification_channel:{channel_id}"
                ),
                entity_type="notification_channel",
            ),
            title=_TEST_TITLE,
            domain_id=channel.domain_id.root,
            severity="low",
            link="/admin/notifications",
            timestamp=self._now().strftime("%Y-%m-%dT%H:%M:%SZ"),
        )

        async def send() -> ChannelTestResult:
            outcome = await sender.send(channel, message, notification_id=notification_id)
            return ChannelTestResult(
                ok=outcome.delivered,
                status_code=outcome.status_code,
                reason_code=None if outcome.delivered else (outcome.reason_code or "send_failed"),
            )

        def verdict(result: ChannelTestResult) -> tuple[str | None, str, bool, str]:
            if result.ok:
                return None, "succeeded", True, "notification_channel_tested"
            return None, "failed", False, f"test_failed_{_slug(result.reason_code)}"

        return await self._run(
            "notification.channel.test",
            "notification_channel",
            channel_id,
            correlation_id,
            send,
            outcome=verdict,
        )

    # -- subscription writes ------------------------------------------------------------------

    async def create_subscription(
        self, correlation_id: str, body: NotificationSubscription
    ) -> tuple[SubscriptionView, str]:
        await self._check_subscription(body)
        subscription_id = body.subscription_id.root
        document = await self._run(
            "notification.subscription.create",
            "notification_subscription",
            subscription_id,
            correlation_id,
            lambda: self._repo.create(
                self._customer, SUBSCRIPTION_KIND, subscription_id, body, updated_by=self._actor
            ),
            outcome=_written("notification_subscription_created"),
        )
        return self._subscription_view(document), etag_of(document)

    async def replace_subscription(
        self,
        correlation_id: str,
        subscription_id: str,
        body: NotificationSubscription,
        if_match: str | None,
    ) -> tuple[SubscriptionView, str]:
        guard = _require_if_match(if_match)
        if body.subscription_id.root != subscription_id:
            raise _refuse("/subscription_id", "must equal the id in the path", "path_body_mismatch")
        await self._active(SUBSCRIPTION_KIND, subscription_id, "subscription_not_found")
        await self._check_subscription(body)
        document = await self._run(
            "notification.subscription.update",
            "notification_subscription",
            subscription_id,
            correlation_id,
            lambda: self._repo.replace(
                self._customer,
                SUBSCRIPTION_KIND,
                subscription_id,
                body,
                if_match=guard,
                updated_by=self._actor,
            ),
            outcome=_written("notification_subscription_updated"),
        )
        return self._subscription_view(document), etag_of(document)

    async def delete_subscription(
        self, correlation_id: str, subscription_id: str, if_match: str | None
    ) -> None:
        guard = _require_if_match(if_match)
        await self._active(SUBSCRIPTION_KIND, subscription_id, "subscription_not_found")
        await self._run(
            "notification.subscription.delete",
            "notification_subscription",
            subscription_id,
            correlation_id,
            lambda: self._repo.retire(
                self._customer,
                SUBSCRIPTION_KIND,
                subscription_id,
                if_match=guard,
                updated_by=self._actor,
            ),
            outcome=_written("notification_subscription_deleted"),
        )

    # -- validation ---------------------------------------------------------------------------

    @property
    def _actor(self) -> str:
        return self._scope.to_contract().principal.principal_id.root

    def _now(self) -> datetime:
        clock = self._hooks.clock
        return clock() if clock is not None else datetime.now(UTC)

    def _check_tenancy(self, customer: str, cloud: str, domain_id: str) -> None:
        if customer != self._customer:
            raise _refuse("/customer_id", "not the caller's customer", "cross_customer")
        if cloud != self._cloud:
            raise _refuse("/cloud", "not the deployment's cloud", "cloud_boundary")
        if not domain_id.startswith(f"{cloud}:{customer}:"):
            raise _refuse("/domain_id", "not a domain of this customer", "cross_customer")

    def _check_reference(self, pointer: str, reference: CredentialReference | Any) -> None:
        uri = getattr(reference, "secret_uri", None)
        if getattr(reference, "kind", None) != "key_vault_secret" or not isinstance(uri, str):
            raise _refuse(
                pointer, "must be a Key Vault secret reference", "invalid_credential_reference"
            )
        try:
            parse_key_vault_secret(uri, self._cloud)
        except InvalidSchemaError as exc:
            reason = (
                "cloud_boundary" if exc.reason == "cross_cloud" else "invalid_credential_reference"
            )
            raise _refuse(pointer, "not a Key Vault secret of this cloud", reason) from None

    async def _setting(self) -> NotificationsSetting:
        setting = await self._plane.registry.settings(self._customer)
        if setting is None:
            raise CapabilityUnavailableError("notifications_not_configured")
        return setting

    async def _check_channel(self, body: NotificationChannel) -> None:
        self._check_tenancy(body.customer_id.root, body.cloud.root, body.domain_id.root)
        if body.local_sink:
            if body.local_sink_url is None:
                raise _refuse(
                    "/local_sink_url", "required with local_sink", "local_sink_url_required"
                )
        else:
            if body.local_sink_url is not None:
                raise _refuse(
                    "/local_sink_url", "only with local_sink", "local_sink_url_not_allowed"
                )
            if body.endpoint_credential is None:
                raise _refuse(
                    "/endpoint_credential",
                    "required unless local_sink",
                    "endpoint_credential_required",
                )
            if body.kind == "webhook" and body.hmac_credential is None:
                raise _refuse(
                    "/hmac_credential",
                    "required for a webhook unless local_sink",
                    "hmac_credential_required",
                )
        if body.endpoint_credential is not None:
            self._check_reference("/endpoint_credential", body.endpoint_credential)
        if body.hmac_credential is not None:
            self._check_reference("/hmac_credential", body.hmac_credential)
        try:
            require_buildable(body.kind)
        except KindNotBuildableError as exc:
            raise CapabilityUnavailableError("channel_kind_not_built") from exc
        setting = await self._setting()
        guard = self._hooks.guard or EgressGuard()
        try:
            guard.check_channel_host(body, setting, deployment_cloud=self._cloud, ns_env=self._env)
        except EgressRefusedError as exc:
            raise _refuse(
                "/allowed_host", "refused by the egress policy", exc.reason_code
            ) from None

    async def _check_subscription(self, body: NotificationSubscription) -> None:
        self._check_tenancy(body.customer_id.root, body.cloud.root, body.domain_id.root)
        channel = await self._plane.registry.channel(self._customer, body.channel_id.root)
        if channel is None:
            raise _refuse("/channel_id", "no such channel", "unknown_channel")
        if channel.cloud.root != body.cloud.root or channel.customer_id.root != self._customer:
            raise _refuse("/channel_id", "channel is in another cloud", "cloud_boundary")

    # -- plumbing -----------------------------------------------------------------------------

    async def _active(self, kind: str, config_id: str, reason: str) -> AdminConfigDocument:
        document = await self._repo.get(self._customer, kind, config_id)
        if document is None or document.status != "active":
            raise NotFoundError("no such notification configuration", reason=reason)
        return document

    async def _channel_view(self, document: AdminConfigDocument) -> ChannelView:
        channel = cast(NotificationChannel, document.body)
        channel_id = channel.channel_id.root
        store = self._plane.store
        counts = await asyncio.gather(
            *(
                store.count_deliveries(self._customer, channel_id=channel_id, status=status)
                for status in DELIVERY_STATUSES
            )
        )
        last_error = await store.last_error_code(self._customer, channel_id)
        return ChannelView(
            channel=channel.model_dump(mode="json"),
            version=document.version.root,
            etag=etag_of(document),
            updated_at=document.updated_at.root,
            updated_by=document.updated_by.root,
            delivery_counts=DeliveryCounts(**dict(zip(DELIVERY_STATUSES, counts, strict=True))),
            last_error_code=last_error,
        )

    @staticmethod
    def _subscription_view(document: AdminConfigDocument) -> SubscriptionView:
        return SubscriptionView(
            subscription=cast(NotificationSubscription, document.body).model_dump(mode="json"),
            version=document.version.root,
            etag=etag_of(document),
            updated_at=document.updated_at.root,
            updated_by=document.updated_by.root,
        )

    def _repository(self) -> AuditRepository:
        if self._audit is None:
            raise DependencyTransientError(
                "audit store is not configured", reason="audit_store_unconfigured"
            )
        return self._audit

    def _subject(
        self, entity_type: str, entity_id: str, operation: str, stage: str, etag: str | None
    ) -> Any:
        canonical = f"{self._cloud}:{self._customer}:notifications:{entity_type}:{entity_id}"
        state = {"operation": operation, "target": entity_id, "stage": stage}
        return make_subject(canonical, entity_type, target_version=etag, state=state)

    async def _run(
        self,
        operation: str,
        entity_type: str,
        entity_id: str,
        correlation_id: str,
        mutate: Callable[[], Awaitable[_T]],
        *,
        outcome: Callable[[_T], tuple[str | None, str, bool, str]],
    ) -> _T:
        ctx = AuditContext.from_scope(
            self._scope, correlation_id=correlation_id, operation=operation, channel="rest"
        )

        def after(result: _T) -> AuditDraft:
            etag, status, verified, detail = outcome(result)
            return build_after(
                ctx,
                self._subject(entity_type, entity_id, operation, "after", etag),
                result=status,  # type: ignore[arg-type]
                verified=verified,
                detail=detail,
            )

        def failed(exc: BaseException) -> AuditDraft:
            return build_after(
                ctx,
                self._subject(entity_type, entity_id, operation, "failed", None),
                result="failed",
                verified=False,
                detail=_reason_of(exc),
            )

        return await run_audited_mutation(
            self._repository(),
            admin_config_chain_id(self._customer),
            before=build_before(
                ctx, self._subject(entity_type, entity_id, operation, "before", None)
            ),
            mutate=mutate,
            after=after,
            on_error=failed,
        )


def _written(detail: str) -> Callable[[AdminConfigDocument], tuple[str | None, str, bool, str]]:
    def outcome(document: AdminConfigDocument) -> tuple[str | None, str, bool, str]:
        return etag_of(document), "succeeded", True, detail

    return outcome


def _slug(reason: str | None) -> str:
    text = re.sub(r"[^a-z0-9_]", "_", (reason or "unknown").lower())[:48]
    return text or "unknown"


def _require_if_match(if_match: str | None) -> str:
    if if_match is None or not if_match.strip():
        raise InvalidSchemaError(
            "If-Match is required to change an existing configuration",
            errors=[ValidationIssue("/headers/If-Match", "required")],
            reason="precondition_required",
        )
    return quoted(if_match.strip())


def _parsed[M: BaseModel](model: type[M], raw: Mapping[str, Any]) -> M:
    """``raw`` as the contract ``model``; the refusal names pointers and rules, never values."""
    try:
        return model.model_validate(raw)
    except ValidationError as exc:
        issues = [
            ValidationIssue("/" + "/".join(str(p) for p in e["loc"]), str(e["msg"])[:200])
            for e in exc.errors()[:50]
        ]
        raise InvalidSchemaError(
            "notification configuration is invalid", errors=issues, reason="invalid_body"
        ) from None


def parse_channel(raw: Mapping[str, Any]) -> NotificationChannel:
    return _parsed(NotificationChannel, raw)


def parse_subscription(raw: Mapping[str, Any]) -> NotificationSubscription:
    return _parsed(NotificationSubscription, raw)
