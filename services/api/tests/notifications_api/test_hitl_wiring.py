"""PRP-107 item 6: HITL assignment and escalation queue outbox rows; HITL never breaks on them."""

from __future__ import annotations

import hashlib
import itertools
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from neurosphere_contracts.actions.v1.actor import Actor
from neurosphere_core.actions.permissions import GrantTablePermissionRechecker
from neurosphere_core.admin.store import InMemoryAdminConfigRepository
from neurosphere_core.audit import AuditRepository, InMemoryAuditStore
from neurosphere_core.auth.scope import InMemoryPolicyRepository
from neurosphere_core.auth.scope.permissions import Permission
from neurosphere_core.auth.scope.revocation_hook import NoRevocationCheck
from neurosphere_core.cloud import CloudName
from neurosphere_core.hitl import (
    DecisionLog,
    EmailNotifierStub,
    HitlService,
    InMemoryDecisionStore,
    InMemoryHitlStore,
    ReviewPolicy,
    ReviewPolicyRegistry,
)
from neurosphere_core.hitl.policy import default_policies
from neurosphere_core.notifications import (
    ChannelRegistry,
    InMemoryOutboxStore,
    NotificationPublisher,
    Outbox,
    SubscriptionResolver,
)
from neurosphere_core.notifications.hitl import OutboxNotifier

CUSTOMER = "contoso"
DOMAIN = "commercial:contoso:catalog:domain:retail"
OTHER_DOMAIN = "commercial:contoso:catalog:domain:finance"
EDGE = "commercial:contoso:catalog:edge:e-0001"
OWNER = "commercial:contoso:entra:principal:p-" + "a" * 64
CHECKER_ID = "commercial:contoso:entra:person:psn_checker00000002"
CHECKER = Actor(principal_pseudonym="p-checker", principal_kind="user", on_behalf_of=None)
SCOPE_HASH = "sha256:" + hashlib.sha256(b"scope").hexdigest()
T0 = datetime(2026, 11, 26, 9, 0, 0, tzinfo=UTC)
POLICY = ReviewPolicy(
    approver_permission=Permission.CATALOG_CURATE,
    assignment_timeout=timedelta(hours=1),
    sla=timedelta(hours=4),
    escalation_step=timedelta(hours=2),
    max_escalations=2,
    expiry=timedelta(hours=24),
    policy_version="test-notify-1",
)


class AllowAll:
    async def can_review(self, *args: Any, **kwargs: Any) -> bool:
        return True


def _ids(prefix: str) -> Callable[[], str]:
    counter = itertools.count(1)
    return lambda: f"{prefix}-{next(counter):012d}"


class Rig:
    def __init__(self, *, publisher: Any = None, with_stub: bool = False) -> None:
        self.admin = InMemoryAdminConfigRepository(cloud="commercial")
        self.grants = GrantTablePermissionRechecker()
        self.store = InMemoryOutboxStore()
        self.registry = ChannelRegistry(self.admin)
        self.publisher = NotificationPublisher(
            SubscriptionResolver(self.registry, self.grants),
            Outbox(self.store),
            self.registry,
        )
        audit = AuditRepository(InMemoryAuditStore(), id_factory=_ids("00000000-0000-4000-8000"))
        notifiers: list[Any] = [OutboxNotifier(publisher or self.publisher)]
        if with_stub:
            notifiers.append(EmailNotifierStub(audit))
        self.service = HitlService(
            InMemoryHitlStore(),
            DecisionLog(audit, InMemoryDecisionStore()),
            audit,
            ReviewPolicyRegistry(kind_defaults={**default_policies(), "relationship": POLICY}),
            AllowAll(),
            notifiers=notifiers,
            id_factory=_ids("22222222-2222-4222-8222"),
        )

    async def subscribe(self, *classes: str, domain: str = DOMAIN) -> None:
        channel = {
            "schema_version": "1.0.0",
            "channel_id": "ch-1",
            "cloud": "commercial",
            "customer_id": CUSTOMER,
            "domain_id": domain,
            "display_name": "ch-1",
            "kind": "webhook",
            "allowed_host": "localhost",
            "local_sink": True,
            "local_sink_url": "http://127.0.0.1:9000/hook",
            "enabled": True,
        }
        sub = {
            "schema_version": "1.0.0",
            "subscription_id": "sub-1",
            "cloud": "commercial",
            "customer_id": CUSTOMER,
            "domain_id": domain,
            "channel_id": "ch-1",
            "event_classes": list(classes),
            "audience_roles": ["domain_steward"],
            "min_severity": "medium",
            "enabled": True,
        }
        await self.admin.create(CUSTOMER, "notification_channel", "ch-1", channel, updated_by=OWNER)
        await self.admin.create(
            CUSTOMER, "notification_subscription", "sub-1", sub, updated_by=OWNER
        )
        self.grants.grant(OWNER, CUSTOMER, domain, "data.read")

    async def open_item(self) -> Any:
        return await self.service.open_item(
            kind="relationship",
            customer_id=CUSTOMER,
            domain_id=DOMAIN,
            subject_ref=EDGE,
            now=T0,
            correlation_id="corr-open-1",
        )

    async def claim(self, item: Any) -> Any:
        return await self.service.assign(
            item.item_id,
            None,
            CHECKER_ID,
            T0,
            by=CHECKER,
            scope_hash=SCOPE_HASH,
            correlation_id="corr-claim-1",
        )

    async def rows(self) -> list[Any]:
        return [e.delivery for e in await self.store.list_deliveries(CUSTOMER)]


async def test_assignment_with_a_subscription_writes_one_pending_row() -> None:
    rig = Rig()
    await rig.subscribe("hitl_item_assigned")
    item = await rig.open_item()
    await rig.claim(item)
    rows = await rig.rows()
    assert [(r.event_class.root, r.status) for r in rows] == [("hitl_item_assigned", "pending")]
    row = rows[0]
    assert row.link.startswith("/review/item?")
    assert item.item_id in row.link
    assert row.subject.entity_type == "review_item"
    assert row.title == "Review item assigned"


async def test_timer_escalation_writes_an_escalated_row() -> None:
    rig = Rig()
    await rig.subscribe("hitl_item_escalated")
    item = await rig.open_item()
    outcome = await rig.service.apply_timers(item, T0 + POLICY.sla, correlation_id="corr-timer")
    assert outcome.notifications_failed == 0
    rows = await rig.rows()
    assert [r.event_class.root for r in rows] == ["hitl_item_escalated"]
    assert rows[0].status == "pending"


async def test_no_subscription_means_no_row_and_hitl_succeeds() -> None:
    rig = Rig()
    item = await rig.open_item()
    claimed = await rig.claim(item)
    assert claimed.state_name == "assigned"
    assert await rig.rows() == []


async def test_a_subscription_for_another_domain_gets_no_row() -> None:
    rig = Rig()
    await rig.subscribe("hitl_item_assigned", domain=OTHER_DOMAIN)
    item = await rig.open_item()
    await rig.claim(item)
    assert await rig.rows() == []


class _Exploding:
    async def publish(self, event: Any) -> list[Any]:
        raise RuntimeError("outbox store down")


async def test_a_raising_publisher_never_breaks_hitl() -> None:
    rig = Rig(publisher=_Exploding())
    item = await rig.open_item()
    claimed = await rig.claim(item)
    assert claimed.state_name == "assigned"  # the assignment stands
    outcome = await rig.service.apply_timers(
        claimed, T0 + timedelta(hours=1), correlation_id="corr-timer"
    )
    assert outcome.applied  # the timer applied
    assert outcome.notifications_failed == 1  # counted, not raised


async def test_stub_notifiers_still_return_recorded_beside_the_outbox() -> None:
    rig = Rig(with_stub=True)
    await rig.subscribe("hitl_item_assigned")
    item = await rig.open_item()
    await rig.claim(item)
    assert len(await rig.rows()) == 1


async def test_receipt_is_recorded_never_delivered() -> None:
    rig = Rig()
    await rig.subscribe("hitl_item_assigned")
    notifier = OutboxNotifier(rig.publisher)
    from neurosphere_core.hitl import Notification

    receipt = await notifier.send(
        Notification(
            notification_id="55555555-5555-4555-8555-555555555555",
            event="review_assigned",
            review_item_id="66666666-6666-4666-8666-666666666666",
            cloud="commercial",
            customer_id=CUSTOMER,
            domain_id=DOMAIN,
            recipient_ref="p-checker",
            correlation_id="corr-1",
        )
    )
    assert receipt.channel == "outbox"
    assert receipt.status == "recorded"


# -- the API builder -------------------------------------------------------------------------


class _FakeOverrides:
    clock = None

    def backend(self, name: str) -> object | None:
        return None


class _FakeCtx:
    """The slice of ``BuildContext`` ``data._hitl_service`` reads."""

    def __init__(self, plane: Any) -> None:
        from neurosphere_api.runtime.builders import (
            AUDIT_REPOSITORY,
            POLICY_REPOSITORY,
            REVOCATION_CHECKER,
        )

        self.overrides = _FakeOverrides()
        self.settings = SimpleNamespace(cloud_profile=SimpleNamespace(cloud=CloudName.COMMERCIAL))
        self._shared: dict[str, object] = {
            AUDIT_REPOSITORY.name: AuditRepository(InMemoryAuditStore()),
            POLICY_REPOSITORY.name: InMemoryPolicyRepository(),
            REVOCATION_CHECKER.name: NoRevocationCheck(),
        }
        if plane is not None:
            from neurosphere_api.runtime.builders.notifications import NOTIFICATIONS

            self._shared[NOTIFICATIONS.name] = plane
        self.published: dict[str, object] = {}

    def shared(self, key: Any) -> Any:
        return self._shared[key.name]

    def maybe_shared(self, key: Any) -> Any:
        return self._shared.get(key.name)

    def publish(self, key: Any, value: Any) -> None:
        self.published[key.name] = value

    def cosmos_client(self) -> Any:
        from unittest.mock import MagicMock

        return MagicMock()

    def store_settings(self) -> Any:
        return SimpleNamespace(database="neurosphere")


def test_data_builder_hands_the_outbox_notifier_to_hitl_service() -> None:
    from neurosphere_api.runtime.builders import data
    from neurosphere_api.runtime.builders.notifications import NotificationsPlane

    rig = Rig()
    plane = NotificationsPlane(
        registry=rig.registry,
        store=rig.store,
        outbox=Outbox(rig.store),
        resolver=SubscriptionResolver(rig.registry, rig.grants),
        publisher=rig.publisher,
        notifier=OutboxNotifier(rig.publisher),
    )
    service = data._hitl_service(_FakeCtx(plane))  # type: ignore[arg-type]
    assert service._notifiers == (plane.notifier,)  # pyright: ignore[reportPrivateUsage]
    bare = data._hitl_service(_FakeCtx(None))  # type: ignore[arg-type]
    assert bare._notifiers == ()  # pyright: ignore[reportPrivateUsage]


def test_builder_installs_the_plane_with_test_backends(monkeypatch: pytest.MonkeyPatch) -> None:
    from authz.authz_helpers import FakeClock  # pyright: ignore[reportMissingImports]
    from neurosphere_api.runtime.builders import authz as authz_builder
    from neurosphere_api.runtime.builders import notifications as builder
    from runtime_api import runtime_helpers  # pyright: ignore[reportMissingImports]

    runtime_helpers.configure_auth_env(monkeypatch)
    clock = FakeClock()
    overrides = runtime_helpers.configured_overrides(
        clock,
        backends={
            "admin_config_repository": InMemoryAdminConfigRepository(cloud="commercial"),
            "notification_outbox_store": InMemoryOutboxStore(),
        },
    )
    composed = runtime_helpers.compose(
        overrides, builders=(authz_builder.BUILDER, builder.BUILDER), clock=clock
    )
    assert composed.registry.get("notifications").state == "ok"
    plane = composed.app.state.notifications
    assert isinstance(plane, builder.NotificationsPlane)
    assert plane.notifier.channel == "outbox"


def test_builder_is_disabled_without_cosmos(monkeypatch: pytest.MonkeyPatch) -> None:
    from authz.authz_helpers import FakeClock  # pyright: ignore[reportMissingImports]
    from neurosphere_api.runtime.builders import authz as authz_builder
    from neurosphere_api.runtime.builders import notifications as builder
    from runtime_api import runtime_helpers  # pyright: ignore[reportMissingImports]

    runtime_helpers.configure_auth_env(monkeypatch)
    clock = FakeClock()
    composed = runtime_helpers.compose(
        runtime_helpers.configured_overrides(clock),
        builders=(authz_builder.BUILDER, builder.BUILDER),
        clock=clock,
    )
    assert getattr(composed.app.state, "notifications", None) is None
    assert composed.app.state.notifications_off_reason == "cosmos_unconfigured"
    assert composed.registry.get("notifications").state == "disabled"
