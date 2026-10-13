"""Revocation fans out to every cache invalidator and push registry (C13).

A failing closer is logged (hook kind, name and exception class only; no principal id, object
id or UPN) and never aborts the remaining closers.
"""

from __future__ import annotations

import asyncio
import logging

import pytest
from neurosphere_core.auth.revocation import (
    CachedRevocationChecker,
    FanoutReport,
    InMemoryRevocationStore,
    PushSessionRegistry,
    RevocationHookRegistry,
)

from .revocation_helpers import (
    ADMIN_OID,
    OBJECT_ID,
    UPN,
    FakeClock,
    FakePushRegistry,
    admin_scope,
    make_claims,
    make_deriver,
    policy_repo,
    principal_id_for,
    service_for,
)

TARGET = principal_id_for(OBJECT_ID)
FANOUT_LOGGER = "neurosphere_core.auth.revocation.fanout"


class _Invalidator:
    def __init__(self, error: BaseException | None = None) -> None:
        self.calls: list[str] = []
        self.error = error

    def __call__(self, principal_id: str) -> int:
        self.calls.append(principal_id)
        if self.error is not None:
            raise self.error
        return 1


class _AsyncInvalidator(_Invalidator):
    async def invalidate(self, principal_id: str) -> int:
        return self(principal_id)


def _sensitive_error() -> RuntimeError:
    # An exception whose message carries everything that must never be logged.
    return RuntimeError(f"close failed for {UPN} oid={OBJECT_ID} pid={TARGET}")


async def test_revoke_calls_every_invalidator_and_every_push_registry() -> None:
    clock = FakeClock()
    store = InMemoryRevocationStore(clock=clock)
    service, hooks, auditor = service_for(store, clock)
    sync_inv, async_inv = _Invalidator(), _AsyncInvalidator()
    hooks.register_cache_invalidator("sync-cache", sync_inv)
    hooks.register_cache_invalidator("async-cache", async_inv.invalidate)
    ws, sse = FakePushRegistry(sessions=2), FakePushRegistry(sessions=3)
    hooks.register_push_registry("websocket", ws)
    hooks.register_push_registry("sse", sse)

    outcome = await service.revoke(await admin_scope(clock), TARGET, reason="compromised")

    assert sync_inv.calls == [TARGET]
    assert async_inv.calls == [TARGET]
    assert ws.closed_for == [TARGET]
    assert sse.closed_for == [TARGET]
    assert outcome.fanout == FanoutReport(
        invalidators_called=2,
        invalidators_failed=(),
        push_registries_called=2,
        push_registries_failed=(),
        sessions_closed=5,
    )
    assert outcome.fanout.complete
    assert outcome.entry.principal_id == TARGET
    assert outcome.entry.revoked_by == principal_id_for(ADMIN_OID)
    assert auditor.phases == ["intent", "outcome"]
    assert auditor.events[-1].fanout == outcome.fanout


async def test_failing_closer_is_logged_without_identifiers_and_does_not_abort_others(
    caplog: pytest.LogCaptureFixture,
) -> None:
    clock = FakeClock()
    store = InMemoryRevocationStore(clock=clock)
    service, hooks, auditor = service_for(store, clock)
    bad_inv, good_inv = _Invalidator(error=_sensitive_error()), _Invalidator()
    hooks.register_cache_invalidator("broken-cache", bad_inv)
    hooks.register_cache_invalidator("good-cache", good_inv)
    first = FakePushRegistry(error=_sensitive_error())
    second = FakePushRegistry(error=ValueError(UPN))
    last = FakePushRegistry(sessions=4)
    hooks.register_push_registry("ws-a", first)
    hooks.register_push_registry("ws-b", second)
    hooks.register_push_registry("ws-c", last)

    with caplog.at_level(logging.WARNING, logger=FANOUT_LOGGER):
        outcome = await service.revoke(await admin_scope(clock), TARGET, reason="compromised")

    assert good_inv.calls == [TARGET]
    assert first.closed_for == second.closed_for == last.closed_for == [TARGET]
    assert outcome.fanout.invalidators_failed == ("broken-cache",)
    assert outcome.fanout.push_registries_failed == ("ws-a", "ws-b")
    assert outcome.fanout.sessions_closed == 4
    assert not outcome.fanout.complete
    assert await store.get(TARGET) is not None  # the revocation itself stands
    assert auditor.phases == ["intent", "outcome"]

    records = [r for r in caplog.records if r.name == FANOUT_LOGGER]
    assert [(r.__dict__["hook_kind"], r.__dict__["hook"]) for r in records] == [
        ("cache_invalidator", "broken-cache"),
        ("push_registry", "ws-a"),
        ("push_registry", "ws-b"),
    ]
    assert [r.__dict__["error_type"] for r in records] == [
        "RuntimeError",
        "RuntimeError",
        "ValueError",
    ]
    rendered = caplog.text + "".join(repr(r.__dict__) for r in records)
    pseudonym = TARGET.rsplit(":", 1)[-1]
    for secret in (UPN, OBJECT_ID, TARGET, pseudonym):
        assert secret not in rendered
    assert all(r.exc_info is None for r in records)


async def test_hanging_closer_times_out_and_later_closers_still_run() -> None:
    hooks = RevocationHookRegistry(hook_timeout_seconds=0.01)
    never = asyncio.Event()

    async def _hang(_: str) -> None:
        await never.wait()

    hanging = FakePushRegistry(on_close=_hang)
    after = FakePushRegistry(sessions=1)
    hooks.register_push_registry("hanging", hanging)
    hooks.register_push_registry("after", after)

    report = await hooks.fan_out(TARGET)

    assert report.push_registries_failed == ("hanging",)
    assert after.closed_for == [TARGET]
    assert report.sessions_closed == 1


async def test_scope_deriver_and_checker_caches_are_invalidated() -> None:
    clock = FakeClock()
    store = InMemoryRevocationStore(clock=clock)
    checker = CachedRevocationChecker(store, ttl_seconds=300, clock=clock)
    repo = policy_repo()
    deriver = make_deriver(
        repo, clock=clock, revocation_checker=checker, policy_cache_ttl_seconds=300
    )
    bystander_claims = make_claims(object_id=ADMIN_OID)
    await deriver.from_verified_claims(make_claims())
    await deriver.from_verified_claims(bystander_claims)
    reads_before = repo.principal_reads
    store_reads_before = store.get_calls

    service, _, _ = service_for(store, clock, checker=checker, deriver=deriver)
    await service.revoke(await admin_scope(clock), TARGET, reason="offboarded")

    # The bystander is still served from both caches; nothing re-read.
    await deriver.from_verified_claims(bystander_claims)
    assert repo.principal_reads == reads_before
    assert store.get_calls == store_reads_before
    # The revoked principal's cached answers are gone: the check re-reads the store and denies.
    assert await checker.is_revoked(TARGET, clock.datetime()) is True
    assert store.get_calls == store_reads_before + 1
    assert deriver.invalidate_principal(TARGET) == 0  # policy cache entry already dropped


async def test_store_is_written_before_push_sessions_close() -> None:
    clock = FakeClock()
    store = InMemoryRevocationStore(clock=clock)
    service, hooks, _ = service_for(store, clock)
    seen: list[object] = []

    async def _observe(principal_id: str) -> None:
        seen.append(await store.get(principal_id))

    hooks.register_push_registry("ws", FakePushRegistry(on_close=_observe))
    await service.revoke(await admin_scope(clock), TARGET, reason="compromised")
    assert seen and seen[0] is not None  # a reconnect at this point is already denied


def test_registration_rules() -> None:
    hooks = RevocationHookRegistry()
    hooks.register_cache_invalidator("scope-deriver", _Invalidator())
    with pytest.raises(ValueError, match="already registered"):
        hooks.register_cache_invalidator("scope-deriver", _Invalidator())
    with pytest.raises(ValueError, match="hook name"):
        hooks.register_cache_invalidator("Has Spaces", _Invalidator())
    with pytest.raises(TypeError):
        hooks.register_cache_invalidator("not-callable", 42)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        hooks.register_push_registry("no-close", object())  # type: ignore[arg-type]
    hooks.register_push_registry("ws", FakePushRegistry())
    assert isinstance(FakePushRegistry(), PushSessionRegistry)
    assert hooks.cache_invalidator_names == ("scope-deriver",)
    assert hooks.push_registry_names == ("ws",)
    with pytest.raises(ValueError):
        RevocationHookRegistry(hook_timeout_seconds=0)


async def test_fan_out_with_no_hooks_is_an_empty_complete_report() -> None:
    report = await RevocationHookRegistry().fan_out(TARGET)
    assert report == FanoutReport(0, (), 0, (), 0)
    assert report.complete
