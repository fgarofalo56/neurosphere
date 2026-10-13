"""Admin revoke: permission checked and audited through injected interfaces; no allow on error."""

from __future__ import annotations

import pytest
from neurosphere_core.auth.revocation import (
    REVOKE_ACTION,
    InMemoryRevocationStore,
    RevocationAuditor,
    RevocationAuthorizer,
    RevocationHookRegistry,
    RevocationService,
    ScopePermissionRevocationAuthorizer,
)
from neurosphere_core.errors import DependencyTransientError, ForbiddenError, InvalidSchemaError
from neurosphere_core.scope import IdentityScope

from .revocation_helpers import (
    ADMIN_OID,
    OBJECT_ID,
    UPN,
    FakeClock,
    RecordingAuditor,
    admin_scope,
    analyst_scope,
    principal_id_for,
    service_for,
)

TARGET = principal_id_for(OBJECT_ID)


class _Authorizer:
    def __init__(self, answer: object = True, error: BaseException | None = None) -> None:
        self.answer = answer
        self.error = error

    async def authorize_revocation(self, actor: IdentityScope, target_principal_id: str) -> bool:
        if self.error is not None:
            raise self.error
        return self.answer  # type: ignore[return-value]


def _service(
    store: InMemoryRevocationStore, clock: FakeClock, authorizer: _Authorizer
) -> tuple[RevocationService, RecordingAuditor, list[str]]:
    auditor = RecordingAuditor()
    hooks = RevocationHookRegistry()
    called: list[str] = []
    hooks.register_cache_invalidator("cache", called.append)
    service = RevocationService(
        store=store, authorizer=authorizer, auditor=auditor, hooks=hooks, clock=clock
    )
    return service, auditor, called


def test_protocols_are_satisfied_by_reference_implementations() -> None:
    assert isinstance(ScopePermissionRevocationAuthorizer(), RevocationAuthorizer)
    assert isinstance(RecordingAuditor(), RevocationAuditor)


async def test_admin_revoke_writes_intent_then_outcome_with_pseudonymous_ids() -> None:
    clock = FakeClock()
    store = InMemoryRevocationStore(clock=clock)
    service, _, auditor = service_for(store, clock)
    actor = await admin_scope(clock)
    outcome = await service.revoke(actor, TARGET, reason="compromised")

    assert outcome.entry.revoked_at == clock.datetime()
    assert [e.phase for e in auditor.events] == ["intent", "outcome"]
    for event in auditor.events:
        assert event.action == REVOKE_ACTION
        assert event.actor_principal_id == principal_id_for(ADMIN_OID)
        assert event.actor_scope_hash == actor.scope_hash
        assert event.target_principal_id == TARGET
        assert event.reason == "compromised"
        assert ADMIN_OID not in repr(event) and OBJECT_ID not in repr(event)


async def test_analyst_is_denied_audited_and_nothing_changes() -> None:
    clock = FakeClock()
    store = InMemoryRevocationStore(clock=clock)
    service, hooks, auditor = service_for(store, clock)
    called: list[str] = []
    hooks.register_cache_invalidator("cache", called.append)

    with pytest.raises(ForbiddenError) as info:
        await service.revoke(await analyst_scope(clock), TARGET, reason="compromised")
    assert info.value.reason == "missing_permission"
    assert auditor.phases == ["denied"]
    assert auditor.events[0].deny_reason == "missing_permission"
    assert store.put_calls == 0
    assert called == []


async def test_cross_customer_target_is_denied_even_for_admin() -> None:
    clock = FakeClock()
    store = InMemoryRevocationStore(clock=clock)
    service, _, auditor = service_for(store, clock)
    foreign = TARGET.replace(":contoso:", ":fabrikam:", 1)
    gov = TARGET.replace("commercial:", "government:", 1)
    for target in (foreign, gov):
        with pytest.raises(ForbiddenError) as info:
            await service.revoke(await admin_scope(clock), target, reason="compromised")
        assert info.value.reason == "cross_scope_target"
    assert auditor.phases == ["denied", "denied"]
    assert store.put_calls == 0


@pytest.mark.parametrize("answer", [False, None, 1, "yes"])
async def test_authorizer_must_return_exactly_true(answer: object) -> None:
    clock = FakeClock()
    store = InMemoryRevocationStore(clock=clock)
    service, auditor, called = _service(store, clock, _Authorizer(answer=answer))
    with pytest.raises(ForbiddenError) as info:
        await service.revoke(await admin_scope(clock), TARGET, reason="compromised")
    assert info.value.reason == "not_authorized"
    assert auditor.phases == ["denied"]
    assert store.put_calls == 0 and called == []


@pytest.mark.parametrize(
    ("error", "status"),
    [(RuntimeError("policy bug"), 503), (DependencyTransientError("policy store down"), 503)],
)
async def test_authorizer_error_fails_closed(error: BaseException, status: int) -> None:
    clock = FakeClock()
    store = InMemoryRevocationStore(clock=clock)
    service, _, called = _service(store, clock, _Authorizer(error=error))
    with pytest.raises(DependencyTransientError) as info:
        await service.revoke(await admin_scope(clock), TARGET, reason="compromised")
    assert info.value.status == status
    assert store.put_calls == 0 and called == []


async def test_intent_audit_failure_blocks_the_revocation() -> None:
    clock = FakeClock()
    store = InMemoryRevocationStore(clock=clock)
    service, auditor, called = _service(store, clock, _Authorizer())
    auditor.fail_on.add("intent")
    with pytest.raises(RuntimeError):
        await service.revoke(await admin_scope(clock), TARGET, reason="compromised")
    assert store.put_calls == 0 and called == []


async def test_outcome_audit_failure_surfaces_after_the_revocation_happened() -> None:
    clock = FakeClock()
    store = InMemoryRevocationStore(clock=clock)
    service, auditor, called = _service(store, clock, _Authorizer())
    auditor.fail_on.add("outcome")
    with pytest.raises(RuntimeError):
        await service.revoke(await admin_scope(clock), TARGET, reason="compromised")
    assert await store.get(TARGET) is not None
    assert called == [TARGET]


@pytest.mark.parametrize(
    ("target", "reason"),
    [
        (UPN, "compromised"),
        (OBJECT_ID, "compromised"),
        (TARGET, f"requested by {UPN}"),
    ],
)
async def test_invalid_input_is_rejected_without_echo_or_audit(target: str, reason: str) -> None:
    clock = FakeClock()
    store = InMemoryRevocationStore(clock=clock)
    service, auditor, _ = _service(store, clock, _Authorizer())
    with pytest.raises(InvalidSchemaError) as info:
        await service.revoke(await admin_scope(clock), target, reason=reason)
    rendered = str(info.value) + repr([(i.pointer, i.detail) for i in info.value.errors or ()])
    assert UPN not in rendered and OBJECT_ID not in rendered
    assert auditor.events == [] and store.put_calls == 0


async def test_revoke_requires_a_derived_scope() -> None:
    clock = FakeClock()
    service, _, _ = _service(InMemoryRevocationStore(clock=clock), clock, _Authorizer())
    with pytest.raises(TypeError):
        await service.revoke(object(), TARGET, reason="compromised")  # type: ignore[arg-type]


async def test_expired_admin_assignment_cannot_revoke() -> None:
    clock = FakeClock()
    actor = await admin_scope(clock)  # admin role expires 7200 s after T0
    clock.advance(7200)
    service, _, auditor = service_for(InMemoryRevocationStore(clock=clock), clock)
    with pytest.raises(ForbiddenError):
        await service.revoke(actor, TARGET, reason="compromised")
    assert auditor.phases == ["denied"]
