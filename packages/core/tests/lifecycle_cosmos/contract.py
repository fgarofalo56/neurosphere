"""Protocol-conformance suites for the lifecycle mapping store, hold registry and request queue.

Self-contained so ``tests/integration/stores_hitl`` can load it by path and run the same
assertions against the Cosmos emulator. Each contract needs one fixture: ``mappings``, ``holds``
or ``queue`` (an empty store bound to the ``CUSTOMER`` partition).
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

from neurosphere_contracts.scope.v1.identity_scope import IdentityScope as ContractScope
from neurosphere_core.audit import AuditContext
from neurosphere_core.lifecycle import (
    ActionKind,
    HoldRegistry,
    LegalHold,
    LifecycleRequest,
    PseudonymMappingStore,
    QueuedRequest,
    RequestQueue,
    Rule,
    TargetRef,
)
from neurosphere_core.scope import IdentityScope

CUSTOMER = "contoso"
NOW = datetime(2026, 10, 23, 12, 0, 0, tzinfo=UTC)


def make_ctx() -> AuditContext:
    contract = ContractScope.model_validate(
        {
            "schema_version": "1.0.0",
            "cloud": "commercial",
            "customer_id": CUSTOMER,
            "principal": {
                "principal_id": "commercial:contoso:entra:person:psn_0123456789abcdef",
                "principal_pseudonym": "p-7f3a9c21",
                "principal_kind": "user",
            },
            "roles": [],
            "allowed_domains": [],
            "allowed_resources": [],
            "policy_version": "v1",
            "derived_at": "2026-10-10T00:00:00Z",
            "scope_hash": "sha256:" + hashlib.sha256(b"scope").hexdigest(),
        }
    )
    scope = IdentityScope._from_verified_contract(contract)  # pyright: ignore[reportPrivateUsage]
    return AuditContext.from_scope(
        scope, correlation_id="corr-23a1", operation="lifecycle.run", channel="worker"
    )


def make_hold(hold_id: str, **overrides: object) -> LegalHold:
    fields: dict[str, object] = {
        "hold_id": hold_id,
        "reason_code": "litigation",
        "subject_id": "subject/with:odd chars?#1",
        "custodians": ("p-custodian",),
        "placed_at": NOW,
    }
    fields.update(overrides)
    return LegalHold.model_validate(fields)


def make_queued(
    record_id: str, *, minutes: int = 0, action: ActionKind = ActionKind.DELETE
) -> QueuedRequest:
    return QueuedRequest(
        request=LifecycleRequest(
            request_id=f"req-{record_id}",
            action=action,
            target=TargetRef(
                target_kind="conversation", container="conversations", record_id=record_id
            ),
        ),
        ctx=make_ctx(),
        blocked_by=Rule.LEGAL_HOLD,
        reason="legal_hold",
        queued_at=NOW + timedelta(minutes=minutes),
        not_before=NOW + timedelta(days=1),
    )


class MappingStoreContract:
    """Needs a ``mappings`` fixture exposing ``register`` besides the protocol."""

    async def test_satisfies_protocol(self, mappings: PseudonymMappingStore) -> None:
        assert isinstance(mappings, PseudonymMappingStore)

    async def test_exists_destroy_round_trip(self, mappings) -> None:  # type: ignore[no-untyped-def]
        subject = "subject/with:odd chars?#1"
        assert await mappings.exists(subject) is False
        await mappings.register(subject)
        await mappings.register(subject)  # idempotent
        assert await mappings.exists(subject) is True
        assert await mappings.exists("someone-else") is False
        await mappings.destroy(subject)
        assert await mappings.exists(subject) is False
        await mappings.destroy(subject)  # destroying nothing is not an error


class HoldRegistryContract:
    async def test_satisfies_protocol(self, holds: HoldRegistry) -> None:
        assert isinstance(holds, HoldRegistry)

    async def test_place_active_release(self, holds: HoldRegistry) -> None:
        assert await holds.active() == []
        first, second = (
            make_hold("hold-1"),
            make_hold("hold-2", subject_id=None, data_class="telemetry"),
        )
        await holds.place(first)
        await holds.place(second)
        assert sorted(await holds.active(), key=lambda h: h.hold_id) == [first, second]
        assert await holds.release("hold-1") is True
        assert await holds.release("hold-1") is False
        assert await holds.active() == [second]

    async def test_placing_the_same_hold_again_overwrites(self, holds: HoldRegistry) -> None:
        await holds.place(make_hold("hold-1"))
        updated = make_hold("hold-1", reason_code="regulatory")
        await holds.place(updated)
        assert await holds.active() == [updated]

    async def test_hold_ids_with_reserved_characters_work(self, holds: HoldRegistry) -> None:
        odd = make_hold("case/2026?x#y\\z")
        await holds.place(odd)
        assert await holds.active() == [odd]
        assert await holds.release("case/2026?x#y\\z") is True


class RequestQueueContract:
    async def test_satisfies_protocol(self, queue: RequestQueue) -> None:
        assert isinstance(queue, RequestQueue)

    async def test_enqueue_pending_remove(self, queue: RequestQueue) -> None:
        a, b = make_queued("c-1"), make_queued("c-2", minutes=1)
        assert await queue.pending() == []
        assert await queue.enqueue(a) is True
        assert await queue.enqueue(b) is True
        assert await queue.pending() == [a, b]
        await queue.remove(a.request.request_id)
        assert await queue.pending() == [b]
        await queue.remove(a.request.request_id)  # removing nothing is not an error

    async def test_equal_requests_are_not_queued_twice(self, queue: RequestQueue) -> None:
        first = make_queued("c-1")
        same_target = QueuedRequest(
            request=first.request.model_copy(update={"request_id": "req-other"}),
            ctx=first.ctx,
            blocked_by=first.blocked_by,
            reason=first.reason,
            queued_at=first.queued_at + timedelta(minutes=5),
        )
        assert await queue.enqueue(first) is True
        assert await queue.enqueue(same_target) is False
        assert await queue.pending() == [first]

    async def test_a_removed_request_can_be_queued_again(self, queue: RequestQueue) -> None:
        item = make_queued("c-1")
        await queue.enqueue(item)
        await queue.remove(item.request.request_id)
        assert await queue.enqueue(item) is True

    async def test_a_subject_erasure_request_round_trips(self, queue: RequestQueue) -> None:
        item = QueuedRequest(
            request=LifecycleRequest(
                request_id="req-erase", action=ActionKind.ERASE_SUBJECT, subject_id="subject-9"
            ),
            ctx=make_ctx(),
            blocked_by=None,
            reason="deferred",
            queued_at=NOW,
        )
        assert await queue.enqueue(item) is True
        assert await queue.pending() == [item]
